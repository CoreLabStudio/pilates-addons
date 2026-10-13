# -*- coding: utf-8 -*-
"""Recording a walk-in: what pays, what is refused, and what is written.

The wizard (Record a walk-in, on the class and on the student) books a
student onto a class that has already started, already attended, marked
by the manager and dated to the class, flagged as recorded after the
fact. It is paid by:

  existing  what the engine would choose - pack, allowance or make-up
  trial     her unused free trial, only if the offer was open on the
            class's date in Madrid
  free      a free class given and used in the same step, recorded as a
            Free desk sale with its reason, so it is in Free classes given

Refused, each with its reason: a cancelled class, one not yet started,
one older than fitness.record_attendance_days (14 when absent), a full
class, no reason, no manager, nothing that can pay. That it counts as
attendance and never as a seat booked in advance is tested in
fitness_reports, which owns the class report.

Silence on every channel is tested in test_record_attendance_is_silent.
Clock pinned, language explicit.
"""
from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 18, 0, 0)       # Wednesday, 19:00 Madrid


@tagged('post_install', '-at_install')
class TestRecordAttendance(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.search([('key', '=', 'fitness.record_attendance_days')]).unlink()
        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.manager = Users.create({
            'name': 'WI Manager', 'login': 'wi.manager@example.invalid',
            'lang': 'en_US', 'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('fitness_core.group_fitness_manager').id])]})
        self.types = {}
        for room in ('reformer', 'barre'):
            self.types[room] = self.env['fitness.class.type'].create({
                'name': 'WI %s' % room, 'classroom_type': room,
                'duration': 50, 'level': 'all', 'session_type': 'group'})
        self._seq = 0

    # -- fixtures ----------------------------------------------------
    def _student(self, email=True):
        self._seq += 1
        vals = {'name': 'WI Student %d' % self._seq, 'lang': 'en_US'}
        if email:
            vals['email'] = 'wi.%d@example.invalid' % self._seq
        return self.env['res.partner'].create(vals)

    def _class(self, hours_ago=20, room='reformer', capacity=6, cancelled=False):
        start = PINNED - timedelta(hours=hours_ago)
        event = self.env['calendar.event'].sudo().create({
            'name': 'WI %s class %d' % (room, self._seq), 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[room].id, 'is_fitness_class': True,
            'capacity': capacity, 'session_type': 'group'})
        if cancelled:
            event.class_state = 'cancelled'
        return event

    def _pack(self, partner, room='reformer', classes=5):
        tmpl = self.env['product.template'].create({
            'name': 'WI %s pack' % room, 'list_price': 50.0,
            'type': 'service', 'fitness_is_package': True,
            'fitness_class_count': classes, 'fitness_validity_days': 60,
            'fitness_class_type': room, 'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': room})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order.order_line[:1]

    def _membership(self, partner, weekly=2, floating=0):
        plan = self.env['product.template'].create({
            'name': 'WI Reformer %d a week' % weekly, 'list_price': 90.0,
            'type': 'service', 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'reformer', 'fitness_session_type': 'group',
            'weekly_class_allowance': weekly})
        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'plan_id': self.env.ref(
                'sale_subscription.subscription_plan_month').id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': plan.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': plan.list_price})
        order.with_context(skip_fitness_notification=True).action_confirm()
        today = PINNED.date()
        order.write({'start_date': today - timedelta(days=10),
                     'next_invoice_date': today + timedelta(weeks=8),
                     'fitness_floating_credits': floating})
        return order

    def _wizard(self, event, partner, pay_with='existing', reason='Walked in',
                user=None):
        return self.env['fitness.record.attendance.wizard'].with_user(
            user or self.manager).create({
                'calendar_event_id': event.id, 'student_id': partner.id,
                'pay_with': pay_with, 'reason': reason})

    def _booking(self, event, partner):
        return self.env['fitness.booking'].sudo().search([
            ('calendar_event_id', '=', event.id),
            ('student_id', '=', partner.id)])

    def _assert_recorded(self, event, partner):
        b = self._booking(event, partner)
        self.assertEqual(len(b), 1)
        self.assertEqual(b.state, 'attended')
        self.assertEqual(b.marked_by_id, self.manager)
        self.assertEqual(b.marked_date, event.start, 'dated to the class')
        self.assertTrue(b.fitness_recorded_after_the_fact)
        return b

    # == what pays ===================================================
    def test_her_pack_pays_and_the_dialog_names_it(self):
        p = self._student()
        line = self._pack(p)
        event = self._class()
        wiz = self._wizard(event, p)
        self.assertIn(line.order_id.name, wiz.source_label)
        wiz.action_record()
        b = self._assert_recorded(event, p)
        self.assertEqual(b.package_order_line_id, line)
        self.assertEqual(line.fitness_remaining_classes, 4)

    def test_her_weekly_allowance_pays(self):
        p = self._student()
        order = self._membership(p)
        event = self._class()
        self._wizard(event, p).action_record()
        b = self._assert_recorded(event, p)
        self.assertEqual(b.subscription_id, order)
        self.assertFalse(b.fitness_used_floating_credit)

    def test_her_make_up_credit_pays_when_her_week_is_spent(self):
        p = self._student()
        order = self._membership(p, weekly=1, floating=1)
        self._wizard(self._class(hours_ago=30), p).action_record()
        event = self._class(hours_ago=20)
        self._wizard(event, p).action_record()
        b = self._assert_recorded(event, p)
        self.assertTrue(b.fitness_used_floating_credit)
        self.assertEqual(order.fitness_floating_credits, 0)

    def test_her_free_trial_pays_if_the_offer_was_open_that_day(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2026-11-30')
        p = self._student()
        event = self._class()
        wiz = self._wizard(event, p, pay_with='trial')
        self.assertIn('can be used', wiz.source_label)
        wiz.action_record()
        b = self._assert_recorded(event, p)
        trial = self.env.ref('fitness_packages.product_reformer_trial')
        self.assertEqual(b.package_order_line_id.product_id.product_tmpl_id,
                         trial)
        self.assertTrue(self.env['fitness.trial.request']._trial_taken(
            p, trial))

    def test_the_trial_is_refused_when_the_offer_had_closed(self):
        # Class at 23:00 Madrid on 3 Nov; the offer closed at the end of 2
        # Nov - in Madrid. A UTC reading would say the same here, so the
        # boundary is the day itself.
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2026-11-02')
        p = self._student()
        event = self._class(hours_ago=20)
        with self.assertRaises(UserError) as caught:
            self._wizard(event, p, pay_with='trial').action_record()
        self.assertIn('had closed', str(caught.exception))
        self.assertFalse(self._booking(event, p))

    def test_the_trial_day_is_madrids(self):
        """00:30 on 4 Nov in Madrid is 23:30 on 3 Nov in UTC."""
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2026-11-03')
        p = self._student()
        start = datetime(2026, 11, 3, 23, 30)         # 00:30 Madrid, 4 Nov
        event = self.env['calendar.event'].sudo().create({
            'name': 'WI late class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types['reformer'].id,
            'is_fitness_class': True, 'capacity': 6,
            'session_type': 'group'})
        with self.assertRaises(UserError):
            self._wizard(event, p, pay_with='trial').action_record()

    def test_a_free_class_is_given_used_and_in_the_history(self):
        p = self._student()
        event = self._class()
        self._wizard(event, p, pay_with='free',
                     reason='Came with a friend').action_record()
        b = self._assert_recorded(event, p)
        order = b.package_order_line_id.order_id
        self.assertEqual(order.fitness_payment_method, 'free')
        self.assertEqual(order.fitness_free_reason, 'Came with a friend')
        self.assertEqual(order.amount_total, 0.0)
        self.env.flush_all()
        row = self.env['fitness.free.credit.report'].with_user(
            self.manager).search([('order_id', '=', order.id)])
        self.assertEqual((row.status, row.used_event_id, row.given_by),
                         ('used', event, self.manager))

    # == what is refused ============================================
    def _refused(self, event, partner, needle, **kw):
        with self.assertRaises(UserError) as caught:
            self._wizard(event, partner, **kw).action_record()
        self.assertIn(needle, str(caught.exception))
        self.assertFalse(self._booking(event, partner))

    def test_refusals_each_say_why(self):
        p = self._student()
        self._pack(p, classes=10)
        self._refused(self._class(cancelled=True), p, 'cancelled')
        self._refused(self._class(hours_ago=-5), p, 'has not happened yet')
        self._refused(self._class(hours_ago=24 * 15), p, '14 days')
        self._refused(self._class(), p, 'Say why', reason='  ')

    def test_the_window_comes_from_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.record_attendance_days', '3')
        p = self._student()
        self._pack(p)
        self._refused(self._class(hours_ago=24 * 4), p, '3 days')

    def test_a_full_class_is_refused(self):
        p, other = self._student(), self._student()
        self._pack(p)
        self._pack(other)
        event = self._class(capacity=1)
        self._wizard(event, other).action_record()
        self._refused(event, p, 'is full')

    def test_with_nothing_to_pay_it_says_so(self):
        p = self._student()
        event = self._class()
        wiz = self._wizard(event, p)
        self.assertIn('covers this class', wiz.source_label)
        self._refused(event, p, 'covers this class')

    def test_only_a_manager(self):
        p = self._student()
        self._pack(p)
        plain = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'WI Plain', 'login': 'wi.plain@example.invalid',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(AccessError):
            self._wizard(self._class(), p, user=plain).action_record()

    # == a student with no email and no phone, end to end ===========
    def test_no_email_no_phone_end_to_end(self):
        contact = self.env['res.partner'].create({'name': 'Núria Sense Correu'})
        self.assertFalse(contact.email or contact.phone)
        mk = self.env['fitness.make.student.wizard'].with_user(
            self.manager).with_context(default_partner_id=contact.id,
                                       active_id=contact.id,
                                       active_model='res.partner').create({
                'partner_id': contact.id, 'password': 'walkin-Pw-2026'})
        mk.action_make_student()
        self.assertTrue(contact.fitness_is_student)
        self.env['fitness.desk.sale.wizard'].with_user(self.manager).create({
            'partner_id': contact.id, 'payment_method': 'free',
            'product_id': self.env.ref(
                'fitness_packages.product_courtesy_reformer').id,
            'reason': 'Walk-in, no app'}).action_create_sale()
        event = self._class()
        self._wizard(event, contact).action_record()
        b = self._assert_recorded(event, contact)
        self.assertTrue(b.package_order_line_id.product_id.fitness_is_courtesy)
        self.env.flush_all()
        row = self.env['fitness.free.credit.report'].with_user(
            self.manager).search([('student_id', '=', contact.id)])
        self.assertEqual((row.status, row.used_event_id, row.reason),
                         ('used', event, 'Walk-in, no app'))
