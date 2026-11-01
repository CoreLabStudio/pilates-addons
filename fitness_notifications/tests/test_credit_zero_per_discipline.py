# -*- coding: utf-8 -*-
""""No credits remaining" asks about the kind of class she just booked.

The bell was held back whenever ANY running membership still gave her
classes, whatever it was for. A student with a Reformer membership who
spent her last Barre credit was never told she had no Barre left - and
her Reformer membership cannot pay for a Barre class.

Now only a running membership that could pay for another class like the
one just booked holds it back: the same discipline (or 'any'), the same
session type - the rule the subscription engine itself books by.

"Running low" never looked at memberships at all - it counts only the
pack lines covering the class - so it had no such flaw. One test pins
that it still rings beside a membership of another discipline.

Clock pinned, language explicit.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)


@tagged('post_install', '-at_install')
class TestCreditZeroPerDiscipline(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.types = {
            (room, session): self.env['fitness.class.type'].create({
                'name': 'CZ %s %s' % (room, session), 'classroom_type': room,
                'duration': 50, 'level': 'all', 'session_type': session})
            for room in ('reformer', 'barre')
            for session in ('group', 'private')}
        self.plan = self.env['sale.subscription.plan'].sudo().create({
            'name': 'CZ Mensual', 'billing_period_value': 1,
            'billing_period_unit': 'month'})
        self._seq = 0

    def _student(self):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CZ Student %d' % self._seq,
                'login': 'cz.%d@example.invalid' % self._seq,
                'email': 'cz.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            }).partner_id

    def _membership(self, partner, room, session='group'):
        self._seq += 1
        tmpl = self.env['product.template'].sudo().create({
            'name': 'CZ %s unlimited (%d)' % (room, self._seq),
            'type': 'service', 'list_price': 100.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'is_unlimited': True, 'fitness_class_type': room,
            'fitness_session_type': session,
            'fitness_subscription_plan_id': self.plan.id})
        so = self.env['sale.order'].sudo().create({
            'partner_id': partner.id, 'plan_id': self.plan.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': so.id, 'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 100.0})
        so.with_context(skip_fitness_notification=True).action_confirm()
        self.assertEqual(so.subscription_state, '3_progress',
                         'fixture: the membership is not running')
        self.assertTrue(so.fitness_is_unlimited, 'fixture: not unlimited')
        return so

    def _pack(self, partner, count, room, session='group'):
        self._seq += 1
        tmpl = self.env['product.template'].create({
            'name': 'CZ %s %s %d (%d)' % (room, session, count, self._seq),
            'list_price': 10.0 * count, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': count,
            'fitness_validity_days': 60, 'fitness_class_type': room,
            'fitness_session_type': session,
        })
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': room,
        })
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order.order_line[:1]

    def _book(self, partner, line, room, session='group'):
        self._seq += 1
        start = PINNED + timedelta(days=1, hours=2 + self._seq)
        event = self.env['calendar.event'].sudo().create({
            'name': 'CZ class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[(room, session)].id,
            'is_fitness_class': True, 'capacity': 6,
            'session_type': session,
        })
        return self.env['fitness.booking'].sudo().create({
            'student_id': partner.id, 'calendar_event_id': event.id,
            'package_order_line_id': line.id,
        })

    def _bells(self, partner, kind):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', 'in', partner.user_ids.ids),
            ('notification_type', '=', kind)])

    def test_reformer_membership_does_not_hide_her_last_barre_credit(self):
        p = self._student()
        self._membership(p, 'reformer')
        pack = self._pack(p, 1, 'barre')
        self._book(p, pack, 'barre')               # Barre 1 -> 0
        self.assertEqual(pack.fitness_remaining_classes, 0)
        self.assertEqual(
            len(self._bells(p, 'credit_zero')), 1,
            'her last Barre credit went unannounced because a Reformer '
            'membership was running')

    def test_a_membership_of_the_same_discipline_still_holds_it_back(self):
        p = self._student()
        self._membership(p, 'barre')
        pack = self._pack(p, 1, 'barre')
        self._book(p, pack, 'barre')
        self.assertFalse(self._bells(p, 'credit_zero'),
                         '"No credits" while her Barre membership runs')

    def test_an_any_discipline_membership_still_holds_it_back(self):
        p = self._student()
        self._membership(p, 'any')
        pack = self._pack(p, 1, 'barre')
        self._book(p, pack, 'barre')
        self.assertFalse(self._bells(p, 'credit_zero'),
                         '"No credits" while an any-discipline membership runs')

    def test_a_group_membership_does_not_hide_her_last_private_credit(self):
        p = self._student()
        self._membership(p, 'reformer', 'group')
        pack = self._pack(p, 1, 'reformer', 'private')
        self._book(p, pack, 'reformer', 'private')
        self.assertEqual(
            len(self._bells(p, 'credit_zero')), 1,
            'a group membership cannot pay for a private class')

    def test_running_low_still_rings_beside_another_discipline(self):
        p = self._student()
        self._membership(p, 'reformer')
        pack = self._pack(p, 2, 'barre')
        self._book(p, pack, 'barre')               # Barre 2 -> 1
        lows = self._bells(p, 'credit_low')
        self.assertEqual(len(lows), 1)
        self.assertEqual(lows.title, 'Only 1 credit(s) left')
