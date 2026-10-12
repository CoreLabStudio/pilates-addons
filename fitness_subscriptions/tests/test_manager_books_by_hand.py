# -*- coding: utf-8 -*-
"""A fitness manager can book a student by hand, and still reads no orders.

A fitness manager has no Sales rights, on purpose. Creating a booking by
hand with the source left to the engine died with "You are not allowed
to access 'Sales Order'" before any booking rule ran:
_select_payment_source searched the student's orders as the caller.
Naming the line herself already worked, and the form already showed her
the credit's name.

The engine now reads the student's orders as superuser, uses them only
to choose which one pays, and returns an id. These tests prove both
halves: the manager books packs and memberships by hand, a rule still
refuses her with the rule's own message - and she still cannot read
sale.order or sale.order.line, directly or over RPC.
"""
import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged

from .test_makeup_credit_returned import MakeUpCreditFixture

PASSWORD = 'mgr-by-hand-Pw-26'


def _manager(env, login):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': 'MB Manager', 'login': login, 'password': PASSWORD,
        'lang': 'en_US', 'tz': 'Europe/Madrid',
        'group_ids': [(6, 0, [
            env.ref('base.group_user').id,
            env.ref('fitness_core.group_fitness_manager').id])],
    })


@tagged('post_install', '-at_install')
class TestManagerBooksByHand(MakeUpCreditFixture):

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'mb.manager@example.invalid')
        self.assertFalse(
            self.env['sale.order'].with_user(self.manager).has_access('read'),
            'fixture: this manager must have no Sales rights')

    def _book_as_manager(self, partner, hours):
        return self.env['fitness.booking'].with_user(self.manager).create({
            'student_id': partner.id,
            'calendar_event_id': self._class(hours).id,
            'manager_override_timewindow': True,
        })

    def test_a_pack_holder_is_booked_on_her_pack(self):
        partner = self._student('mbpack').partner_id
        line = self._packline(partner)
        booking = self._book_as_manager(partner, 30)
        self.assertEqual(booking.package_order_line_id, line)
        self.assertEqual(line.fitness_remaining_classes, 4)

    def test_a_member_is_booked_on_her_membership(self):
        partner = self._student('mbsub').partner_id
        order = self._membership(partner)
        booking = self._book_as_manager(partner, 30)
        self.assertEqual(booking.subscription_id, order)

    def test_a_rule_still_refuses_with_its_own_sentence(self):
        partner = self._student('mbcap').partner_id
        self._membership(partner)
        self._spend_her_week(partner)
        with self.assertRaises(UserError) as caught:
            self._book_as_manager(partner, 32)
        self.assertNotIsInstance(caught.exception, AccessError)
        self.assertIn('weekly limit', str(caught.exception))

    def test_nobody_can_pay_refusal_is_the_rule_too(self):
        partner = self._student('mbnone').partner_id
        with self.assertRaises(UserError) as caught:
            self._book_as_manager(partner, 30)
        self.assertNotIsInstance(caught.exception, AccessError)
        self.assertIn('covers this class', str(caught.exception))

    def test_she_still_reads_no_orders(self):
        partner = self._student('mbread').partner_id
        line = self._packline(partner)
        self._book_as_manager(partner, 30)
        for model, rec in (('sale.order', line.order_id),
                           ('sale.order.line', line)):
            with self.subTest(model=model):
                with self.assertRaises(AccessError):
                    self.env[model].with_user(self.manager).search(
                        [('id', '=', rec.id)])
                with self.assertRaises(AccessError):
                    rec.with_user(self.manager).read(['name'])

    def test_a_plain_internal_user_still_cannot_book(self):
        plain = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'MB Plain', 'login': 'mb.plain@example.invalid',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        partner = self._student('mbplain').partner_id
        self._packline(partner)
        with self.assertRaises(AccessError):
            self.env['fitness.booking'].with_user(plain).create({
                'student_id': partner.id,
                'calendar_event_id': self._class(30).id,
            })


@tagged('post_install', '-at_install')
class TestManagerBooksByHandOverRpc(MakeUpCreditFixture, HttpCase):

    def _rpc(self, model, method, args):
        res = self.url_open(
            '/web/dataset/call_kw/%s/%s' % (model, method),
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'model': model, 'method': method,
                                        'args': args, 'kwargs': {}}}),
            headers={'Content-Type': 'application/json'})
        return res.json()

    def test_booking_by_hand_works_and_orders_stay_closed(self):
        manager = _manager(self.env, 'mb.rpc@example.invalid')
        partner = self._student('mbrpc').partner_id
        line = self._packline(partner)
        event = self._class(30)
        self.authenticate(manager.login, PASSWORD)
        out = self._rpc('fitness.booking', 'create', [{
            'student_id': partner.id, 'calendar_event_id': event.id,
            'manager_override_timewindow': True}])
        self.assertNotIn('error', out, out.get('error'))
        for model in ('sale.order', 'sale.order.line'):
            out = self._rpc(model, 'search_read',
                            [[('id', '=', line.order_id.id
                               if model == 'sale.order' else line.id)],
                             ['name']])
            self.assertIn('error', out, '%s readable over RPC' % model)
