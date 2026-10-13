# -*- coding: utf-8 -*-
"""Record a walk-in does its work once per dialog.

Hotfix 2 gave every dialog that creates an order, a credit or a booking
one confirmation per dialog. The walk-in dialog, added in Batch 2, creates
all three - a booking, and with "a free class, given now" an order and its
credit - and did not have the rule: a double click, a second tab or a
retry over RPC recorded her twice, spent a second credit or gave a second
free class.

Sequential presses through the real action; concurrent presses as two
real database connections racing for one committed dialog row, the loser
retried as Odoo retries a serialization failure. The clock is pinned.
"""
import threading
import time
from datetime import datetime, timedelta

import psycopg2.errors

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged
from odoo.tools import mute_logger

PINNED = datetime(2026, 11, 4, 18, 0, 0)       # Wednesday, 19:00 Madrid
ALREADY = 'already been confirmed'
MODEL = 'fitness.record.attendance.wizard'


@tagged('post_install', '-at_install')
class TestWalkinOnce(TransactionCase):

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'WO Manager', 'login': 'wo.manager@example.invalid',
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id])]})
        ctype = self.env['fitness.class.type'].create({
            'name': 'WO Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        start = PINNED - timedelta(hours=20)
        self.event = self.env['calendar.event'].sudo().create({
            'name': 'WO class', 'start': start,
            'stop': start + timedelta(minutes=50), 'class_type_id': ctype.id,
            'is_fitness_class': True, 'capacity': 6, 'session_type': 'group'})
        self.student = self.env['res.partner'].create({'name': 'WO Student'})
        pack = self.env['product.template'].create({
            'name': 'WO pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student.id,
            'order_line': [(0, 0, {
                'product_id': pack.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'fitness_class_type': 'reformer'})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        self.line = order.order_line[:1]

    def _wizard(self, pay_with):
        return self.env[MODEL].with_user(self.manager).create({
            'calendar_event_id': self.event.id,
            'student_id': self.student.id, 'pay_with': pay_with,
            'reason': 'Walked in'})

    def _bookings(self):
        return self.env['fitness.booking'].sudo().search_count([
            ('student_id', '=', self.student.id)])

    def _orders(self):
        return self.env['sale.order'].sudo().search_count([
            ('partner_id', '=', self.student.id)])

    def test_her_credit_is_spent_once(self):
        wiz = self._wizard('existing')
        wiz.action_record()
        with self.assertRaises(UserError) as caught:
            wiz.action_record()
        self.assertIn(ALREADY, str(caught.exception))
        self.line.invalidate_recordset()
        self.assertEqual(self._bookings(), 1)
        self.assertEqual(self.line.fitness_remaining_classes, 4,
                         'a second credit was spent')

    def test_the_free_class_is_given_once(self):
        orders = self._orders()
        wiz = self._wizard('free')
        wiz.action_record()
        with self.assertRaises(UserError) as caught:
            wiz.action_record()
        self.assertIn(ALREADY, str(caught.exception))
        self.assertEqual(self._bookings(), 1)
        self.assertEqual(self._orders(), orders + 1,
                         'a second free class was given')

    def test_two_walkins_are_two(self):
        """No cap: a second dialog for another class records again."""
        self._wizard('existing').action_record()
        start = PINNED - timedelta(hours=44)
        self.event = self.event.copy({'start': start,
                                      'stop': start + timedelta(minutes=50)})
        self._wizard('existing').action_record()
        self.assertEqual(self._bookings(), 2)


@tagged('post_install', '-at_install')
class TestWalkinConcurrent(TransactionCase):
    """Two connections, one committed walk-in dialog, pressing at once.

    Raw connections, not registry.cursor(): inside a test that hands out
    test cursors sharing one connection behind a Python lock. The losing
    press is refused by Postgres on purpose and odoo.sql_db logs that at
    ERROR; odoo.sh fails a build on any ERROR line, so it is muted here.
    """

    def _raw(self):
        return sql_db.db_connect(self.env.cr.dbname).cursor()

    def _commit_dialog(self, pay_with):
        with self._raw() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            partner = env['res.partner'].create({'name': 'WO Race'})
            event = env['calendar.event'].create({
                'name': 'WO race class', 'start': '2026-11-04 08:00:00',
                'stop': '2026-11-04 08:50:00'})
            wiz = env[MODEL].create({
                'calendar_event_id': event.id, 'student_id': partner.id,
                'pay_with': pay_with, 'reason': 'race'})
            ids = (wiz.id, event.id, partner.id)
        self.addCleanup(self._drop, *ids)
        return ids[0]

    def _drop(self, wiz_id, event_id, partner_id):
        with self._raw() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env[MODEL].browse(wiz_id).unlink()
            env['calendar.event'].browse(event_id).unlink()
            env['res.partner'].browse(partner_id).unlink()

    def _race(self, pay_with):
        with mute_logger('odoo.sql_db'):
            wiz_id = self._commit_dialog(pay_with)
            first, second = self._raw(), self._raw()
            outcome = {}
            try:
                api.Environment(first, SUPERUSER_ID, {})[MODEL].browse(
                    wiz_id)._fitness_confirm_once()
                # Built here, not in the thread: an Environment looks up
                # the registry under a lock the test runner is holding.
                again = api.Environment(second, SUPERUSER_ID, {})[
                    MODEL].browse(wiz_id)

                def press_again():
                    try:
                        again._fitness_confirm_once()
                        outcome['first try'] = 'claimed'
                    except psycopg2.errors.SerializationFailure:
                        outcome['first try'] = 'retry'
                    except UserError:
                        outcome['first try'] = 'refused'

                racer = threading.Thread(target=press_again)
                racer.start()
                time.sleep(1.0)
                outcome['waited'] = racer.is_alive()
                first.commit()
                racer.join(30)
                if outcome.get('first try') == 'retry':
                    second.rollback()
                    try:
                        api.Environment(second, SUPERUSER_ID, {})[
                            MODEL].browse(wiz_id)._fitness_confirm_once()
                        outcome['retry'] = 'claimed'
                    except UserError:
                        outcome['retry'] = 'refused'
                    second.rollback()
            finally:
                first.close()
                second.close()
        return outcome

    def test_two_presses_of_one_walkin_with_her_credit(self):
        outcome = self._race('existing')
        self.assertTrue(outcome['waited'], outcome)
        self.assertNotIn('claimed', outcome.values(), outcome)
        self.assertIn('refused', outcome.values(), outcome)

    def test_two_presses_of_one_walkin_giving_a_free_class(self):
        outcome = self._race('free')
        self.assertTrue(outcome['waited'], outcome)
        self.assertNotIn('claimed', outcome.values(), outcome)
        self.assertIn('refused', outcome.values(), outcome)
