# -*- coding: utf-8 -*-
"""One trial rule for the student app, Record a walk-in and trial approval.

Independent QA, on 28082c1: a student bought the Reformer trial for cash,
a walk-in spent it, and a second walk-in gave her a FREE Reformer trial -
two Reformer trials. The walk-in followed approval's check, which counts
only free trials; the student app has always applied a stricter rule.

The rule, written once (fitness.trial.request._free_trial_refusal): a new
free trial of a discipline needs her free trial unused in either
discipline, that discipline's trial never had (paid or free), and the
offer open. The app, the walk-in and approval all ask it. A student who
bought the Reformer trial may still have a free Barre one, as the app
allows today. Approval refuses with the request untouched; a closed offer
is not an approval refusal (the trial is then charged at its price, as
before). The studio's free class and desk gift are not limited.

Clock pinned; refusals in en, es and ca; silence counted on every channel
for student and instructor with the real push send patched, on both the
walk-in and approval paths. The last class pins the helper to the
student app's previous expression for every combination it can meet.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged
from odoo.tools import float_is_zero

PINNED = datetime(2026, 10, 20, 9, 0, 0)       # Tuesday, 11:00 Madrid
WALKIN_REFUSED = {
    'en_US': 'has already had her free trial',
    'es_ES': 'ya ha tenido su prueba gratuita',
    'ca_ES': 'ja ha tingut la seva prova gratuïta',
}
TAKEN_REFUSED = {
    'en_US': 'so it cannot be given free again',
    'es_ES': 'no se le puede volver a dar gratis',
    'ca_ES': 'no se li pot tornar a donar gratis',
}


class OneTrialFixture(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.trial_offer_end', '2026-10-31')
        ICP.set_param(PARAM_PUBLIC, 'pub-for-test')
        ICP.set_param(PARAM_PRIVATE, 'priv-for-test')
        ICP.set_param('database.is_neutralized', 'False')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        self.TR = self.env['fitness.trial.request'].sudo()
        self.trial = {
            'reformer': self.env.ref('fitness_packages.product_reformer_trial'),
            'barre': self.env.ref('fitness_packages.product_barre_trial'),
        }
        for p in self.trial.values():
            # Free, as on production; a fresh install ships no promotion.
            p.write({'fitness_promo_mode': 'free', 'fitness_promo_start': False,
                     'fitness_promo_end': '2026-10-31'})
        self.types = {room: self.env['fitness.class.type'].create({
            'name': 'OR %s' % room, 'classroom_type': room, 'duration': 50,
            'level': 'all', 'session_type': 'group'})
            for room in ('reformer', 'barre')}
        self.manager = self._user('manager', ['base.group_user',
                                              'fitness_core.group_fitness_manager'])
        self.teacher = self._user('teacher', ['base.group_user',
                                              'fitness_core.group_fitness_teacher'])
        self._seq = 0

    def _user(self, tag, groups, lang='en_US'):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OR %s' % tag, 'login': 'or.%s@example.invalid' % tag,
            'email': 'or.%s@example.invalid' % tag, 'lang': lang,
            'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])]})
        self.env['fitness.push.subscription']._register_device(
            user.id, 'https://push.example.invalid/or.%s' % tag, 'pub', 'auth')
        return user

    def _student(self):
        self._seq += 1
        return self._user('student%d' % self._seq,
                          ['base.group_portal', 'fitness_core.group_fitness_student'])

    def _class(self, room, hours):
        """A class `hours` from now; negative is in the past."""
        start = PINNED + timedelta(hours=hours)
        return self.env['calendar.event'].sudo().create({
            'name': 'OR %s class' % room, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[room].id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group', 'user_id': self.teacher.id})

    def _trial_order(self, student, room, price, used=False):
        p = self.trial[room]
        order = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': p.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': price})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        line = order.order_line[:1]
        if used:
            line.fitness_remaining_classes = 0
        return line

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

    def _request(self, student, room):
        return self.TR.create({
            'name': student.name, 'email': student.email, 'phone': '600000000',
            'class_interest': room, 'partner_id': student.partner_id.id,
            'occurrence_id': self._class(room, 48 + self._seq).id})

    def _approve(self, req, lang='en_US'):
        req.with_user(self.manager).with_context(lang=lang).action_approve_and_book()

    def _trials(self, student):
        return self.env['sale.order.line'].sudo().search_count([
            ('order_partner_id', '=', student.partner_id.id),
            ('product_id.product_tmpl_id', 'in',
             [p.id for p in self.trial.values()])])


@tagged('post_install', '-at_install')
class TestOneTrialRuleWalkin(OneTrialFixture):

    def test_s1_a_bought_trial_spent_then_a_second_walkin_is_refused(self):
        student = self._student()
        held = self._trial_order(student, 'reformer', 15.0)
        first = self._walkin(student, self._class('reformer', -20))
        self.assertEqual(first.package_order_line_id, held)
        with self.assertRaises(UserError) as caught:
            self._walkin(student, self._class('reformer', -40))
        self.assertIn(WALKIN_REFUSED['en_US'], str(caught.exception))
        self.assertEqual(self._trials(student), 1, 'a second Reformer trial')

    def test_a_prior_free_barre_trial_refuses_a_free_reformer_one(self):
        student = self._student()
        self._trial_order(student, 'barre', 0.0, used=True)
        with self.assertRaises(UserError):
            self._walkin(student, self._class('reformer', -20))
        self.assertEqual(self._trials(student), 1)

    def test_reformer_then_barre_walkins_give_one_free_trial(self):
        student = self._student()
        self._walkin(student, self._class('reformer', -20))
        with self.assertRaises(UserError):
            self._walkin(student, self._class('barre', -40))
        self.assertEqual(self._trials(student), 1)

    def test_a_bought_reformer_trial_leaves_a_free_barre_one(self):
        """What the student app allows today: her free trial is unused."""
        student = self._student()
        self._trial_order(student, 'reformer', 15.0, used=True)
        booking = self._walkin(student, self._class('barre', -20))
        line = booking.package_order_line_id
        self.assertEqual(line.product_id.product_tmpl_id, self.trial['barre'])
        self.assertEqual(line.price_total, 0.0)

    def test_case_i_a_held_trial_is_spent_with_nothing_new(self):
        student = self._student()
        held = self._trial_order(student, 'barre', 0.0)
        booking = self._walkin(student, self._class('barre', -20))
        self.assertEqual(booking.package_order_line_id, held)
        self.assertEqual(self._trials(student), 1)

    def test_case_ii_a_new_free_trial_is_made_as_approval_makes_one(self):
        student = self._student()
        booking = self._walkin(student, self._class('reformer', -20))
        self.assertEqual(booking.package_order_line_id.price_total, 0.0)
        self.assertEqual(self._trials(student), 1)

    def test_the_offer_closed_on_the_class_day(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2026-10-18')
        student = self._student()
        with self.assertRaises(UserError) as caught:
            self._walkin(student, self._class('reformer', -20))
        self.assertIn('had closed', str(caught.exception))
        self.assertEqual(self._trials(student), 0)

    def test_the_refusal_in_three_languages(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for n, lang in enumerate(WALKIN_REFUSED):
            with self.subTest(lang=lang):
                student = self._student()
                self._trial_order(student, 'reformer', 15.0, used=True)
                with self.assertRaises(UserError) as caught:
                    self._walkin(student, self._class('reformer', -20 - n), lang)
                self.assertIn(WALKIN_REFUSED[lang], str(caught.exception))


@tagged('post_install', '-at_install')
class TestOneTrialRuleApproval(OneTrialFixture):

    def _refused(self, req, lang='en_US'):
        orders = self.env['sale.order'].sudo().search_count([])
        with self.assertRaises(UserError) as caught:
            self._approve(req, lang)
        req.invalidate_recordset()
        self.assertEqual(req.status, 'pending', 'the request was touched')
        self.assertEqual(self.env['sale.order'].sudo().search_count([]), orders)
        return str(caught.exception)

    def test_a_bought_and_used_reformer_trial_refuses_a_second_reformer(self):
        student = self._student()
        self._trial_order(student, 'reformer', 15.0, used=True)
        why = self._refused(self._request(student, 'reformer'))
        self.assertIn(TAKEN_REFUSED['en_US'], why)

    def test_a_used_free_trial_refuses_the_other_discipline(self):
        student = self._student()
        self._trial_order(student, 'barre', 0.0, used=True)
        why = self._refused(self._request(student, 'reformer'))
        self.assertIn('already used their free trial', why)

    def test_a_bought_reformer_trial_allows_a_free_barre_one(self):
        student = self._student()
        self._trial_order(student, 'reformer', 15.0, used=True)
        self._approve(self._request(student, 'barre'))
        barre = self.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', student.partner_id.id),
            ('product_id.product_tmpl_id', '=', self.trial['barre'].id)])
        self.assertEqual(len(barre), 1)
        self.assertEqual(barre.price_total, 0.0)

    def test_a_held_trial_is_approved_on_it(self):
        student = self._student()
        held = self._trial_order(student, 'reformer', 15.0)
        self._approve(self._request(student, 'reformer'))
        self.assertEqual(self._trials(student), 1)
        held.invalidate_recordset()
        self.assertEqual(held.fitness_remaining_classes, 0)

    def test_the_form_warns_before_approval_refuses(self):
        student = self._student()
        self._trial_order(student, 'reformer', 15.0, used=True)
        req = self._request(student, 'reformer')
        self.assertTrue(req.trial_already_used)
        self.env.company.partner_id.lang = 'en_US'
        req.invalidate_recordset(['trial_used_warning'])
        self.assertIn('Approving this will be refused',
                      req.with_context(lang='en_US').trial_used_warning)

    def test_the_refusal_in_three_languages(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for lang in TAKEN_REFUSED:
            with self.subTest(lang=lang):
                student = self._student()
                self._trial_order(student, 'reformer', 15.0, used=True)
                why = self._refused(self._request(student, 'reformer'), lang)
                self.assertIn(TAKEN_REFUSED[lang], why)


@tagged('post_install', '-at_install')
class TestOneTrialRuleIsSilent(OneTrialFixture):

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

    def _silent(self, action, student):
        self.env.flush_all()
        before = self._counts(student.partner_id, self.teacher.partner_id)
        sent = []
        with patch.object(web_push, 'send',
                          lambda *a, **k: sent.append(a) or (200, '')):
            action()
            self.env.flush_all()
        after = self._counts(student.partner_id, self.teacher.partner_id)
        self.assertEqual(sent, [], 'a push was sent')
        mails = self.env['mail.mail'].sudo().search([], order='id desc',
                                                    limit=3)
        for channel in sorted(before):
            self.assertEqual(
                after[channel], before[channel], '%s: newest mail %s' % (
                    channel, [(m.subject, m.email_to, m.model, m.res_id)
                              for m in mails]))

    def test_walkin_new_trial_and_refusal_tell_nobody(self):
        # Classes made before counting: creating one assigns the instructor,
        # which is its own notice and not the walk-in's doing.
        student = self._student()
        first, second = self._class('reformer', -20), self._class('reformer', -40)
        self._silent(lambda: self._walkin(student, first), student)

        def refused():
            with self.assertRaises(UserError):
                self._walkin(student, second)
        self._silent(refused, student)

    def test_an_approval_refusal_tells_nobody(self):
        student = self._student()
        self._trial_order(student, 'reformer', 15.0, used=True)
        req = self._request(student, 'reformer')

        def refused():
            with self.assertRaises(UserError):
                self._approve(req)
        self._silent(refused, student)


@tagged('post_install', '-at_install')
class TestStudentAppRuleUnchanged(OneTrialFixture):
    """The helper against the student app's previous expression.

    Before this change the shop card and the product page offered a free
    trial of a product when the offer was open and her free trial unused -
    and never showed a trial she had already had. The helper must say the
    same for every product the app would show, in every combination, with
    the offer open and closed. (The rendered pages are compared before and
    after by the automated check as well.)
    """

    def _old_entitlement_used(self, partner):
        trials = self.TR._all_trial_products()
        lines = self.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id', 'in', trials.mapped('product_variant_ids').ids)])
        return any(float_is_zero(l.price_total or 0.0, precision_rounding=0.01)
                   for l in lines)

    def test_every_combination_answers_as_before(self):
        shapes = {
            'nothing': [],
            'free used': [(0.0, True)],
            'free held': [(0.0, False)],
            'paid held': [(15.0, False)],
            'paid used': [(15.0, True)],
        }
        checked = 0
        for end in ('2026-10-31', '2026-10-18'):
            self.env['ir.config_parameter'].sudo().set_param(
                'fitness.trial_offer_end', end)
            for room in ('reformer', 'barre'):
                for label, orders in shapes.items():
                    student = self._student()
                    for price, used in orders:
                        self._trial_order(student, room, price, used=used)
                    partner = student.partner_id
                    for product in self.trial.values():
                        if self.TR._trial_taken(partner, product):
                            continue        # the app does not show it at all
                        old = (self.TR._trial_offer_open()
                               and not self._old_entitlement_used(partner))
                        new = not self.TR._free_trial_refusal(partner, product)
                        with self.subTest(end=end, room=room, shape=label,
                                          product=product.fitness_class_type):
                            self.assertEqual(new, old)
                        checked += 1
        # 2 offer states x 2 disciplines x 5 shapes x 2 products, less the
        # trial each shape has had (the app does not show it): 24.
        self.assertEqual(checked, 24)
