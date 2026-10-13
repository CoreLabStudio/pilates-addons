# -*- coding: utf-8 -*-
"""A walk-in recorded after the class is attendance, not a seat booked.

The class report's Booked Seats and fill rate are what the studio reads
as "booked in advance". A booking the studio recorded after the class
(fitness_recorded_after_the_fact, set by the walk-in wizard) is counted
as attended and left out of both. A booking she made herself still
counts in both.

Clock pinned. The report is a database view, so writes are flushed
before it is read.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 18, 0, 0)


@tagged('post_install', '-at_install')
class TestWalkinNotBookedInAdvance(TransactionCase):

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.ct = self.env['fitness.class.type'].create({
            'name': 'WN Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        self.pack = self.env['product.template'].create({
            'name': 'WN pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})

    def _line(self, name):
        partner = self.env['res.partner'].create({'name': name})
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return partner, order.order_line[:1]

    def test_booked_seats_and_fill_rate_leave_the_walk_in_out(self):
        start = PINNED - timedelta(hours=20)
        event = self.env['calendar.event'].sudo().create({
            'name': 'WN class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.ct.id, 'is_fitness_class': True,
            'capacity': 4, 'session_type': 'group'})
        booked, booked_line = self._line('WN Booked')
        walkin, walkin_line = self._line('WN Walk-in')
        Booking = self.env['fitness.booking'].sudo().with_context(
            skip_fitness_notification=True)
        with common.freeze_time(start - timedelta(days=1)):
            mine = Booking.create({
                'student_id': booked.id, 'calendar_event_id': event.id,
                'package_order_line_id': booked_line.id})
        recorded = Booking.with_context(
            fitness_record_past_attendance=True).create({
                'student_id': walkin.id, 'calendar_event_id': event.id,
                'package_order_line_id': walkin_line.id,
                'manager_override_timewindow': True})
        (mine | recorded).write({'state': 'attended'})
        recorded.write({'fitness_recorded_after_the_fact': True})
        self.env.flush_all()
        row = self.env['fitness.report.class'].search(
            [('event_id', '=', event.id)])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.attended_count, 2, 'both were there')
        self.assertEqual(row.booked_count, 1, 'only one booked in advance')
        self.assertEqual(row.occupancy_pct, 25.0)
