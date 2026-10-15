# -*- coding: utf-8 -*-
"""Paying the next month through Odoo's own payment opens that month and places her classes.

Eva Cuartero (14 Oct) paid her second month on her subscription page. The
invoice was posted, next_invoice_date moved one month - and nothing else:
the studio's side of a new period (its start, the weekly counter, her
weekly classes) only ran when the desk called _update_next_invoice_date.
Her period still began on 17 Sep, the monthly limit counted her September
classes against October, and her fourth October class was never placed.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOnlinePaymentOpensThePeriod(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        G = env.ref
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.student = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OP Student', 'login': 'op.student@example.invalid', 'email': 'op.student@example.invalid',
            'group_ids': [(6, 0, [G('base.group_portal').id, G('fitness_core.group_fitness_student').id])]})
        teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'OP Teacher', 'login': 'op.teacher@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G('fitness_core.group_fitness_teacher').id])]})
        room = env['fitness.classroom'].create({'name': 'OP Room', 'classroom_type': 'reformer', 'capacity': 8})
        ctype = env['fitness.class.type'].create({
            'name': 'OP Reformer', 'classroom_type': 'reformer', 'session_type': 'group',
            'level': 'all', 'classroom_id': room.id})
        cls.today = fields.Date.today()
        # Her month one ended yesterday-ish: paid to today+2, as Eva paid on
        # 14 Oct for a month starting 17 Oct.
        cls.next = cls.today + timedelta(days=2)
        cls.start = cls.next - relativedelta(months=1)
        wd = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][cls.today.weekday()]
        sched = env['fitness.class.schedule'].create({
            'name': 'OP weekly', 'class_type_id': ctype.id, 'classroom_id': room.id,
            'weekday': wd, 'start_time': 21.0, 'duration': 1.0,
            'date_start': cls.start - timedelta(days=7), 'horizon_weeks': 12,
            'teacher_user_id': teacher.id})
        sched.action_generate()
        cls.events = env['calendar.event'].search(
            [('recurrence_id', '=', sched.recurrence_id.id)], order='start')
        cls.month = env.ref('sale_subscription.subscription_plan_month')
        cls.product = env.ref('fitness_subscriptions.product_barre_clase_fija_1')
        cls.product.fitness_class_type = 'reformer'

    def test_paying_the_next_month_online_opens_it_and_places_her_classes(self):
        so = self.env['sale.order'].create({
            'partner_id': self.student.partner_id.id, 'plan_id': self.month.id,
            'start_date': self.start})
        self.env['sale.order.line'].create({
            'order_id': so.id, 'product_uom_qty': 1,
            'product_id': self.product.product_variant_ids[:1].id})
        so.with_context(skip_fitness_notification=True).action_confirm()
        self.env['fitness.clase.fija'].create(
            {'subscription_id': so.id, 'calendar_event_id': self.events[0].id})
        first = so._create_invoices()
        first.action_post()
        self.assertEqual(so.next_invoice_date, self.next, 'fixture: month one paid')
        # Month one's classes, all had: four of them, as Eva's were.
        Booking = self.env['fitness.booking'].with_context(_fitness_clase_fija_placement=True)
        had = self.events.filtered(lambda e: self.start <= e.start.date() < self.next)[:4]
        for e in had:
            Booking.create({'student_id': self.student.partner_id.id, 'calendar_event_id': e.id,
                            'subscription_id': so.id}).state = 'attended'
        self.assertEqual(len(had), 4, 'fixture: four classes in month one')

        # Month two paid the way Eva paid it: Odoo raises and posts the
        # invoice for the next period - no desk, no Renew (cash).
        second = so._create_invoices()
        second.action_post()

        so.invalidate_recordset()
        self.assertEqual(so.fitness_period_start_date, self.next,
                         'the month just paid was not opened (period still starts %s)'
                         % so.fitness_period_start_date)
        paid_to = self.next + relativedelta(months=1) - timedelta(days=1)
        held = self.env['fitness.booking'].search([
            ('subscription_id', '=', so.id), ('state', '!=', 'cancelled')]).mapped('class_start')
        in_month_two = [d for d in held if self.next <= d.date() <= paid_to]
        self.assertTrue(in_month_two, 'month two got no classes: %s' % sorted(d.date() for d in held))
        self.assertLessEqual(len(in_month_two), 4)
