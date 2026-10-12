# -*- coding: utf-8 -*-
""""Running low" counts only what could pay for the class she booked.

It took limit=1 on any line with one credit left - expired, on a
cancelled order, another discipline - and reported that line's count as
her balance. Carlota was told "Solo quedan 1 crédito(s)" holding five.

Now: the spendable lines (live order, not expired) that cover the class
just booked, summed. Threshold unchanged at 1.

Clock pinned, language explicit.
"""
from datetime import date, datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)


@tagged('post_install', '-at_install')
class TestRunningLowIsTrue(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.types = {
            room: self.env['fitness.class.type'].create({
                'name': 'RL %s' % room, 'classroom_type': room,
                'duration': 50, 'level': 'all', 'session_type': 'group'})
            for room in ('reformer', 'barre')}
        self._seq = 0

    def _student(self):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'RL Student %d' % self._seq,
                'login': 'rl.%d@example.invalid' % self._seq,
                'email': 'rl.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            }).partner_id

    def _line(self, partner, count, room='reformer', remaining=None):
        self._seq += 1
        tmpl = self.env['product.template'].create({
            'name': 'RL %s %d (%d)' % (room, count, self._seq),
            'list_price': 10.0 * count, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': count,
            'fitness_validity_days': 60, 'fitness_class_type': room,
            'fitness_session_type': 'group',
        })
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': room,
        })
        order.action_confirm()
        line = order.order_line[:1]
        if remaining is not None:
            line.fitness_remaining_classes = remaining
        return line

    def _book(self, partner, line, room='reformer'):
        start = PINNED + timedelta(days=1, hours=2)
        event = self.env['calendar.event'].sudo().create({
            'name': 'RL class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[room].id,
            'is_fitness_class': True, 'capacity': 6,
        })
        return self.env['fitness.booking'].sudo().create({
            'student_id': partner.id, 'calendar_event_id': event.id,
            'package_order_line_id': line.id,
        })

    def _lows(self, partner):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', 'in', partner.user_ids.ids),
            ('notification_type', '=', 'credit_low')])

    def test_carlotas_case_a_pack_beside_a_single_is_not_low(self):
        p = self._student()
        pack = self._line(p, 5)
        self._line(p, 1)                      # the old single, one left
        self._book(p, pack)                   # pack 5 -> 4; she holds 5
        self.assertFalse(self._lows(p), 'told she was low holding five')

    def test_her_genuine_last_credit_is_low(self):
        p = self._student()
        pack = self._line(p, 2)
        self._book(p, pack)                   # 2 -> 1, nothing else
        lows = self._lows(p)
        self.assertEqual(len(lows), 1)
        self.assertEqual(lows.title, 'Only 1 credit(s) left')

    def test_an_expired_line_is_not_counted(self):
        p = self._student()
        old = self._line(p, 1)
        old.fitness_validity_end_date = date(2026, 11, 3)
        pack = self._line(p, 4)
        self._book(p, pack)                   # 4 -> 3 live; expired 1
        self.assertFalse(self._lows(p))

    def test_an_expired_line_does_not_hide_the_real_last_credit(self):
        p = self._student()
        old = self._line(p, 5)
        old.fitness_validity_end_date = date(2026, 11, 3)
        pack = self._line(p, 2)
        self._book(p, pack)                   # live 1, expired 5
        self.assertEqual(len(self._lows(p)), 1)

    def test_a_cancelled_order_is_not_counted(self):
        p = self._student()
        gone = self._line(p, 1)
        gone.order_id._action_cancel()
        pack = self._line(p, 4)
        self._book(p, pack)
        self.assertFalse(self._lows(p))

    def test_another_discipline_is_not_counted(self):
        p = self._student()
        self._line(p, 1, room='barre')        # Barre, one left
        pack = self._line(p, 4)
        self._book(p, pack)                   # Reformer 4 -> 3
        self.assertFalse(self._lows(p))

    def test_another_discipline_does_not_hide_the_real_last_credit(self):
        p = self._student()
        self._line(p, 5, room='barre')
        pack = self._line(p, 2)
        self._book(p, pack)                   # Reformer 1, Barre 5
        self.assertEqual(len(self._lows(p)), 1)

    def test_the_total_across_covering_lines_is_what_counts(self):
        p = self._student()
        a = self._line(p, 2)
        self._line(p, 3, remaining=1)         # another Reformer line, one
        self._book(p, a)                      # 1 + 1 = 2 covering
        self.assertFalse(self._lows(p), 'reported one line, not the total')
