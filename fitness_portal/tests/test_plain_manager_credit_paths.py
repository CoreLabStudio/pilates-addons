# -*- coding: utf-8 -*-
"""A manager without Sales rights books on the student's own credit, and
nobody else's - on every path.

Batch 2 commit 3 let a fitness manager with no Sales rights book a student
by hand: the payment engine now reads the student's orders as superuser to
choose which one pays. Hotfix 2 made a booking refuse any line or
membership that is not the booked student's own. This proves the two
together, over the endpoints the browser uses, as that manager: the form
(web_save), direct RPC (create and write), the Roster's Add a student, the
walk-in dialog and the desk. Another student's pack and membership are
refused and left untouched on each; her student's own credit works; and
she still reads no orders.

How each path refuses is part of what is proven. Naming a line at all -
another student's or her own - is refused to this manager by Odoo itself
(she has no read on sale.order.line) before any booking rule runs; a
manager WITH Sales rights reaches the ownership rule instead, which Hotfix
2's tests cover. Her own credit is spent by leaving the source to the
payment engine, which is how the form, the Roster and the walk-in all do
it. Either way: refused, and the other student's credit untouched.

The clock is pinned (the fixture).
"""
import json

from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_subscriptions.tests.test_makeup_credit_returned \
    import MakeUpCreditFixture

PASSWORD = 'plain-paths-Pw-26'
REFUSED = "can only be paid with the student's own credit"
NO_READ = "not allowed to access 'Sales Order"


def refusal(out):
    """The message an RPC call was refused with, or '' if it was not."""
    return out.get('error', {}).get('data', {}).get('message', '')


@tagged('post_install', '-at_install')
class TestPlainManagerCreditPaths(MakeUpCreditFixture, HttpCase):

    def setUp(self):
        super().setUp()
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'PP Manager', 'login': 'pp.manager@example.invalid',
                'password': PASSWORD, 'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id])]})
        self.assertFalse(
            self.env['sale.order.line'].with_user(self.manager)
            .has_access('read'), 'fixture: she must have no Sales rights')
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.mine = self._student('ppmine').partner_id
        self.my_line = self._packline(self.mine)
        self.hers = self._student('pphers').partner_id
        self.her_line = self._packline(self.hers)
        self.her_sub = self._membership(self.hers)
        self.event = self._class(30)
        self.authenticate(self.manager.login, PASSWORD)

    # -- plumbing ------------------------------------------------------
    def _call(self, model, method, args, kwargs=None, button=False):
        route = 'call_button' if button else 'call_kw'
        res = self.url_open(
            '/web/dataset/%s/%s/%s' % (route, model, method),
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'model': model, 'method': method,
                                        'args': args,
                                        'kwargs': kwargs or {}}}),
            headers={'Content-Type': 'application/json'})
        return res.json()

    def _left(self, line):
        line.invalidate_recordset()
        return line.fitness_remaining_classes

    def _hers_untouched(self):
        self.assertEqual(self._left(self.her_line), 5,
                         "the other student's pack was spent")

    def _bookings(self, partner):
        return self.env['fitness.booking'].sudo().search_count(
            [('student_id', '=', partner.id)])

    # -- another student's credit, every path ----------------------------
    def test_the_form_refuses_her_pack_and_her_membership(self):
        for field, value in (('package_order_line_id', self.her_line.id),
                             ('subscription_id', self.her_sub.id)):
            with self.subTest(field=field):
                out = self._call('fitness.booking', 'web_save', [[], {
                    'student_id': self.mine.id,
                    'calendar_event_id': self.event.id, field: value,
                    'manager_override_timewindow': True}],
                    {'specification': {}})
                why = refusal(out)
                self.assertTrue(REFUSED in why or NO_READ in why, out)
        self._hers_untouched()
        self.assertEqual(self._bookings(self.mine), 0)

    def test_direct_rpc_create_and_write_are_refused(self):
        out = self._call('fitness.booking', 'create', [{
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'package_order_line_id': self.her_line.id,
            'manager_override_timewindow': True}])
        why = refusal(out)
        self.assertTrue(REFUSED in why or NO_READ in why, out)
        own = self._call('fitness.booking', 'create', [{
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'manager_override_timewindow': True}])
        self.assertNotIn('error', own, own.get('error'))
        booking_id = own['result'][0] if isinstance(own['result'], list) \
            else own['result']
        for field, value in (('package_order_line_id', self.her_line.id),
                             ('subscription_id', self.her_sub.id)):
            with self.subTest(write=field):
                out = self._call('fitness.booking', 'write',
                                 [[booking_id], {field: value}])
                why = refusal(out)
                self.assertTrue(REFUSED in why or NO_READ in why, out)
        self._hers_untouched()

    def test_the_roster_books_her_own_credit_only(self):
        wid = self._call('fitness.add.student.wizard', 'create', [{
            'event_id': self.event.id, 'student_id': self.mine.id}])['result']
        out = self._call('fitness.add.student.wizard', 'action_add',
                         [[wid]], button=True)
        self.assertNotIn('error', out, out.get('error'))
        booking = self.env['fitness.booking'].sudo().search(
            [('student_id', '=', self.mine.id)])
        self.assertEqual(booking.package_order_line_id, self.my_line)
        self._hers_untouched()
        # A student with nothing of her own is refused, not paid for by
        # somebody else.
        nobody = self._student('ppnone').partner_id
        wid = self._call('fitness.add.student.wizard', 'create', [{
            'event_id': self.event.id, 'student_id': nobody.id}])['result']
        out = self._call('fitness.add.student.wizard', 'action_add',
                         [[wid]], button=True)
        self.assertIn('error', out)
        self.assertEqual(self._bookings(nobody), 0)
        self._hers_untouched()

    def test_the_walkin_records_on_her_own_credit_only(self):
        past = self._class(-3, 'PP walk-in')
        wid = self._call('fitness.record.attendance.wizard', 'create', [{
            'calendar_event_id': past.id, 'student_id': self.mine.id,
            'pay_with': 'existing', 'reason': 'Walked in'}])['result']
        out = self._call('fitness.record.attendance.wizard', 'action_record',
                         [[wid]], button=True)
        self.assertNotIn('error', out, out.get('error'))
        booking = self.env['fitness.booking'].sudo().search(
            [('student_id', '=', self.mine.id)])
        self.assertEqual(booking.package_order_line_id, self.my_line)
        self._hers_untouched()
        # The dialog has no credit field to smuggle another one through.
        # Asserted on the model, not tried over RPC: an unknown field is a
        # ValueError, which odoo.http logs at ERROR, and odoo.sh fails a
        # build on any ERROR line.
        fields = self.env['fitness.record.attendance.wizard']._fields
        self.assertFalse({'package_order_line_id', 'subscription_id'}
                         & set(fields))

    def test_the_desk_gives_to_the_named_student_only(self):
        before = self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.hers.id)])
        wid = self._call('fitness.desk.sale.wizard', 'create', [{
            'partner_id': self.mine.id, 'product_id': self.pack.id,
            'payment_method': 'free', 'reason': 'Her cousin'}])['result']
        out = self._call('fitness.desk.sale.wizard', 'action_create_sale',
                         [[wid]], button=True)
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.hers.id)]), before)
        fields = self.env['fitness.desk.sale.wizard']._fields
        self.assertFalse({'package_order_line_id', 'subscription_id'}
                         & set(fields))
        self._hers_untouched()

    # -- her own credit, and nothing else opened -----------------------
    def test_her_own_credit_works(self):
        """Left to the engine, by the form and over RPC: her pack pays."""
        out = self._call('fitness.booking', 'create', [{
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'manager_override_timewindow': True}])
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(self._left(self.my_line), 4)
        out = self._call('fitness.booking', 'web_save', [[], {
            'student_id': self.mine.id,
            'calendar_event_id': self._class(32, 'PP second').id,
            'manager_override_timewindow': True}], {'specification': {}})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(self._left(self.my_line), 3)
        self._hers_untouched()

    def test_naming_even_her_own_line_needs_sales_rights(self):
        """Unchanged by Batch 2: she gains no read on order lines."""
        out = self._call('fitness.booking', 'create', [{
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'package_order_line_id': self.my_line.id,
            'manager_override_timewindow': True}])
        self.assertIn(NO_READ, refusal(out), out)
        self.assertEqual(self._left(self.my_line), 5)

    def test_she_still_reads_no_orders(self):
        for model, rid in (('sale.order', self.her_line.order_id.id),
                           ('sale.order.line', self.her_line.id)):
            with self.subTest(model=model):
                out = self._call(model, 'search_read',
                                 [[('id', '=', rid)], ['name']])
                self.assertIn('error', out, '%s readable' % model)
