# -*- coding: utf-8 -*-
"""Record a walk-in pays with "her free trial" by the studio's one-trial rule.

Independent QA recorded walk-ins with "her free trial" and got a second
free trial every time it should have been refused: for a student who had
bought the Reformer trial and still held it, for one who had already had
a free Barre trial, and for one given a Reformer trial by a walk-in a
moment before and then a Barre one. The walk-in asked only whether she had
had a free trial of THIS class's discipline.

The rule is the studio's, and the one trial approval uses, in this order:
a trial credit she holds that covers the class is spent; otherwise, if her
one free trial (either discipline) is unused and the offer was open on the
class's day in Madrid, a trial is made by the code that approves requests;
otherwise it is refused, pointing at her own credit or a free class. The
free single class and the desk gift are not limited by any of this.

The walk-in stays silent on that path too: counted on every channel, for
the student and the instructor, with the real push send patched. Clock
pinned; English, Spanish and Catalan refusals.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 18, 0, 0)       # Wednesday, 19:00 Madrid
REFUSED = {
    'en_US': 'has already had her free trial',
    'es_ES': 'ya ha tenido su prueba gratuita',
    'ca_ES': 'ja ha tingut la seva prova gratuïta',
}


@tagged('post_install', '-at_install')
class TestWalkinOneFreeTrial(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.trial_offer_end', '2026-11-30')
        ICP.set_param(PARAM_PUBLIC, 'pub-for-test')
        ICP.set_param(PARAM_PRIVATE, 'priv-for-test')
        ICP.set_param('database.is_neutralized', 'False')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        # Free, as production runs them; a fresh install ships no promotion.
        self.trial = {
            'reformer': self.env.ref('fitness_packages.product_reformer_trial'),
            'barre': self.env.ref('fitness_packages.product_barre_trial'),
        }
        for p in self.trial.values():
            p.write({'fitness_promo_mode': 'free', 'fitness_promo_start': False,
                     'fitness_promo_end': False})
        self.types = {room: self.env['fitness.class.type'].create({
            'name': 'OT %s' % room, 'classroom_type': room, 'duration': 50,
            'level': 'all', 'session_type': 'group'})
            for room in ('reformer', 'barre')}
        self.manager = self._user('manager', ['base.group_user',
                                              'fitness_core.group_fitness_manager'])
        self.teacher = self._user('teacher', ['base.group_user',
                                              'fitness_core.group_fitness_teacher'])
        self._seq = 0

    # -- fixtures ------------------------------------------------------
    def _user(self, tag, groups, lang='en_US'):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OT %s' % tag, 'login': 'ot.%s@example.invalid' % tag,
            'email': 'ot.%s@example.invalid' % tag, 'lang': lang,
            'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])]})
        self.env['fitness.push.subscription']._register_device(
            user.id, 'https://push.example.invalid/ot.%s' % tag, 'pub', 'auth')
        return user

    def _student(self):
        self._seq += 1
        return self._user('student%d' % self._seq,
                          ['base.group_portal', 'fitness_core.group_fitness_student'])

    def _class(self, room='reformer', hours_ago=20):
        start = PINNED - timedelta(hours=hours_ago)
        return self.env['calendar.event'].sudo().create({
            'name': 'OT %s class' % room, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[room].id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group', 'user_id': self.teacher.id})

    def _trial_order(self, student, room, price):
        """A trial she already has: bought (price) or given free (0)."""
        p = self.trial[room]
        order = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': p.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': price})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order.order_line[:1]

    def _walkin(self, student, event, lang='en_US'):
        wiz = self.env['fitness.record.attendance.wizard'].with_user(
            self.manager).with_context(lang=lang).create({
                'calendar_event_id': event.id,
                'student_id': student.partner_id.id,
                'pay_with': 'trial', 'reason': 'Walked in'})
        wiz.action_record()
        return self.env['fitness.booking'].sudo().search([
            ('calendar_event_id', '=', event.id),
            ('student_id', '=', student.partner_id.id)])

    def _trial_orders(self, student):
        return self.env['sale.order.line'].sudo().search_count([
            ('order_partner_id', '=', student.partner_id.id),
            ('product_id.product_tmpl_id', 'in',
             [p.id for p in self.trial.values()])])

    # -- QA's three cases ----------------------------------------------
    def test_a_bought_trial_she_still_holds_is_spent_not_doubled(self):
        student = self._student()
        held = self._trial_order(student, 'reformer', 15.0)
        booking = self._walkin(student, self._class('reformer'))
        self.assertEqual(booking.package_order_line_id, held)
        self.assertEqual(self._trial_orders(student), 1, 'a second trial was made')
        held.invalidate_recordset()
        self.assertEqual(held.fitness_remaining_classes, 0)

    def test_a_free_trial_in_the_other_discipline_refuses(self):
        student = self._student()
        self._trial_order(student, 'barre', 0.0)
        event = self._class('reformer')
        with self.assertRaises(UserError) as caught:
            self._walkin(student, event)
        self.assertIn(REFUSED['en_US'], str(caught.exception))
        self.assertEqual(self._trial_orders(student), 1)
        self.assertFalse(self.env['fitness.booking'].sudo().search(
            [('student_id', '=', student.partner_id.id)]))

    def test_two_walkins_reformer_then_barre_give_one_trial(self):
        student = self._student()
        first = self._walkin(student, self._class('reformer'))
        self.assertEqual(first.package_order_line_id.price_total, 0.0)
        with self.assertRaises(UserError) as caught:
            self._walkin(student, self._class('barre', hours_ago=30))
        self.assertIn(REFUSED['en_US'], str(caught.exception))
        self.assertEqual(self._trial_orders(student), 1)

    # -- what still works ------------------------------------------------
    def test_an_approved_trial_she_holds_is_spent(self):
        student = self._student()
        held = self._trial_order(student, 'reformer', 0.0)
        booking = self._walkin(student, self._class('reformer'))
        self.assertEqual(booking.package_order_line_id, held)
        self.assertEqual(self._trial_orders(student), 1)

    def test_an_unused_entitlement_makes_a_free_trial_as_approval_does(self):
        student = self._student()
        booking = self._walkin(student, self._class('reformer'))
        line = booking.package_order_line_id
        self.assertEqual(line.product_id.product_tmpl_id, self.trial['reformer'])
        self.assertEqual(line.price_total, 0.0)
        self.assertEqual(line.order_id.state, 'sale')
        self.assertEqual(booking.state, 'attended')
        self.assertTrue(self.env['fitness.trial.request']._trial_already_claimed(
            student.partner_id))

    def test_the_offer_closed_on_the_class_day_refuses(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2026-11-02')
        student = self._student()
        with self.assertRaises(UserError) as caught:
            self._walkin(student, self._class('reformer', hours_ago=20))
        self.assertIn('had closed', str(caught.exception))
        self.assertEqual(self._trial_orders(student), 0)

    def test_the_free_class_is_not_limited(self):
        """The studio giving on purpose: a free class after a used trial."""
        student = self._student()
        self._trial_order(student, 'reformer', 0.0)
        wiz = self.env['fitness.record.attendance.wizard'].with_user(
            self.manager).create({
                'calendar_event_id': self._class('reformer').id,
                'student_id': student.partner_id.id, 'pay_with': 'free',
                'reason': 'Her friend brought her'})
        wiz.action_record()
        self.assertEqual(self.env['fitness.booking'].sudo().search_count(
            [('student_id', '=', student.partner_id.id)]), 1)

    def test_the_refusal_is_in_the_managers_language(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for n, lang in enumerate(('en_US', 'es_ES', 'ca_ES')):
            with self.subTest(lang=lang):
                student = self._student()
                self._trial_order(student, 'barre', 0.0)
                with self.assertRaises(UserError) as caught:
                    self._walkin(student, self._class('reformer', 20 + n), lang)
                self.assertIn(REFUSED[lang], str(caught.exception))

    # -- silence -----------------------------------------------------------
    def _counts(self, *partners):
        ids = [p.id for p in partners]
        return {
            'mail.mail': self.env['mail.mail'].sudo().search_count([]),
            'mail.message': self.env['mail.message'].sudo().search_count(
                [('message_type', '!=', 'notification')]),
            'mail.notification': self.env['mail.notification'].sudo(
                ).search_count([('res_partner_id', 'in', ids)]),
            'fitness.notification': self.env['fitness.notification'].sudo(
                ).search_count([('user_id', 'in',
                                 [u.id for p in partners for u in p.user_ids])]),
        }

    def test_a_trial_walkin_tells_nobody_on_any_channel(self):
        for case in ('new trial', 'held trial'):
            with self.subTest(case=case):
                student = self._student()
                if case == 'held trial':
                    self._trial_order(student, 'reformer', 0.0)
                event = self._class('reformer', hours_ago=20 + len(case))
                self.env.flush_all()
                before = self._counts(student.partner_id, self.teacher.partner_id)
                sent = []
                with patch.object(web_push, 'send',
                                  lambda *a, **k: sent.append(a) or (200, '')):
                    booking = self._walkin(student, event)
                    self.env.flush_all()
                after = self._counts(student.partner_id, self.teacher.partner_id)
                self.assertEqual(booking.state, 'attended')
                self.assertEqual(sent, [], 'a push was sent: %d' % len(sent))
                for channel in sorted(before):
                    self.assertEqual(after[channel], before[channel],
                                     '%s went from %d to %d' % (
                                         channel, before[channel], after[channel]))
