# -*- coding: utf-8 -*-
"""Renew (cash) moves the billing date one period, and the paid period gets its classes.

Posting the renewal invoice already moves next_invoice_date to the day after
the paid period; the desk then called _update_next_invoice_date() as well,
which moved it a second period. The studio's override opened the period
after the one just paid, so that month got no fixed-class placement. Found
reading the code (14 Oct), confirmed by a local run: invoice 16 Oct - 15 Nov,
next billing 16 Dec, nothing booked in the paid month.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRenewCashMovesOnce(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        G = env.ref
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RC Manager', 'login': 'rc.manager@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G('fitness_core.group_fitness_manager').id])]})
        cls.student = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RC Student', 'login': 'rc.student@example.invalid', 'email': 'rc.student@example.invalid',
            'group_ids': [(6, 0, [G('base.group_portal').id, G('fitness_core.group_fitness_student').id])]})
        teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RC Teacher', 'login': 'rc.teacher@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G('fitness_core.group_fitness_teacher').id])]})
        room = env['fitness.classroom'].create({'name': 'RC Room', 'classroom_type': 'barre', 'capacity': 8})
        ctype = env['fitness.class.type'].create({
            'name': 'RC Barre', 'classroom_type': 'barre', 'session_type': 'group',
            'level': 'all', 'classroom_id': room.id})
        cls.today = fields.Date.today()
        cls.start = cls.today - timedelta(days=28)
        wd = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][cls.today.weekday()]
        sched = env['fitness.class.schedule'].create({
            'name': 'RC weekly', 'class_type_id': ctype.id, 'classroom_id': room.id,
            'weekday': wd, 'start_time': 21.0, 'duration': 1.0,
            'date_start': cls.start, 'horizon_weeks': 14, 'teacher_user_id': teacher.id})
        sched.action_generate()
        cls.events = env['calendar.event'].search(
            [('recurrence_id', '=', sched.recurrence_id.id)], order='start')
        cls.month = env.ref('sale_subscription.subscription_plan_month')
        cls.product = env.ref('fitness_subscriptions.product_barre_clase_fija_1')

    def _paid_month_one(self):
        so = self.env['sale.order'].create({
            'partner_id': self.student.partner_id.id, 'plan_id': self.month.id,
            'start_date': self.start})
        self.env['sale.order.line'].create({
            'order_id': so.id, 'product_uom_qty': 1,
            'product_id': self.product.product_variant_ids[:1].id})
        so.with_context(skip_fitness_notification=True).action_confirm()
        self.env['fitness.clase.fija'].create(
            {'subscription_id': so.id, 'calendar_event_id': self.events[0].id})
        inv = so._create_invoices()
        inv.action_post()
        self.assertEqual(so.next_invoice_date, self.start + relativedelta(months=1),
                         'fixture: month one paid must leave the date one month on')
        return so

    def test_one_renewal_moves_the_date_exactly_one_period(self):
        so = self._paid_month_one()
        before = so.next_invoice_date
        so.with_user(self.manager).action_fitness_renew_cash()
        so.invalidate_recordset()
        self.assertEqual(so.next_invoice_date, before + relativedelta(months=1),
                         'one cash payment moved the billing date more than one period')
        self.assertEqual(so.fitness_period_start_date, before,
                         'the period opened is not the one just paid')

    def test_the_paid_period_gets_its_classes(self):
        so = self._paid_month_one()
        paid_from = so.next_invoice_date
        so.with_user(self.manager).action_fitness_renew_cash()
        so.invalidate_recordset()
        # The month the renewal invoice covers - fixed, not read back from
        # the billing date, which is what the fault moved.
        paid_to = paid_from + relativedelta(months=1) - timedelta(days=1)
        held = self.env['fitness.booking'].search([
            ('subscription_id', '=', so.id), ('state', '!=', 'cancelled')]).mapped('class_start')
        in_paid = [d for d in held if paid_from <= d.date() <= paid_to]
        self.assertTrue(in_paid, 'the period just paid (%s..%s) got no classes: %s'
                        % (paid_from, paid_to, sorted(d.date() for d in held)))

    def test_a_plan_change_moves_the_new_plan_once(self):
        """Renew (cash) onto a quarter: one quarter paid, one quarter credited."""
        so = self._paid_month_one()
        so.next_invoice_date = self.today + timedelta(days=2)   # inside any renewal window
        quarter = self.env.ref('fitness_subscriptions.subscription_plan_quarter')
        so.with_user(self.manager).action_fitness_renew_cash(new_plan=quarter)
        new = self.env['sale.order'].search([
            ('partner_id', '=', self.student.partner_id.id), ('plan_id', '=', quarter.id),
            ('state', '=', 'sale')], limit=1)
        self.assertTrue(new, 'no order on the new plan')
        self.assertEqual(new.next_invoice_date, new.start_date + relativedelta(months=3),
                         'one quarter paid moved the date %s -> %s'
                         % (new.start_date, new.next_invoice_date))
        self.assertEqual(new.fitness_period_start_date, new.start_date,
                         'the period opened is not the one just paid')
