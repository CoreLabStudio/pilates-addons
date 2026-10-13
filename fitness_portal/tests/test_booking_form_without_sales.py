# -*- coding: utf-8 -*-
"""A fitness manager without Sales rights can open a booking whose student holds credit.

The pack dropdown on the booking form is limited to the student's own
spendable lines through fitness_choosable_line_ids (Hotfix 2). That field
was computed as the reader, and a manager without Sales rights may not
read order lines, so the whole form failed for her - "Failed to write
field fitness.booking.fitness_choosable_line_ids" - on any booking whose
student held credit. Found in the merge-1 five-minute look, step 3.

Computed as superuser it gives her the ids the dropdown filters on and
nothing more: reading the lines' names is still refused.
"""
from lxml import etree

from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_portal.tests.test_credit_is_her_own import (
    PASSWORD, OwnCreditFixture, RpcMixin, _manager)


@tagged('post_install', '-at_install')
class TestBookingFormWithoutSales(RpcMixin, OwnCreditFixture, HttpCase):

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'oc.nosales@example.invalid')
        self.assertFalse(
            self.env['sale.order.line'].with_user(self.manager).has_access('read'),
            'fixture: she must have no Sales rights')
        self.my_line = self._packline(self.mine)
        self.booking = self._book(self.mine, self.event,
                                  package_order_line_id=self.my_line.id)
        self.authenticate(self.manager.login, PASSWORD)

    def test_she_opens_the_booking(self):
        out = self._rpc('fitness.booking', 'web_read', [self.booking.ids], {
            'specification': {
                'student_id': {'fields': {'display_name': {}}},
                'fitness_choosable_line_ids': {},
                'package_order_line_id': {'fields': {'display_name': {}}},
            }})
        self.assertNotIn('error', out, out.get('error', {}).get('data', {}).get('message'))
        rec = out['result'][0]
        self.assertEqual(rec['fitness_choosable_line_ids'], self.my_line.ids,
                         'the dropdown must still offer her own pack, and only it')

    def test_a_new_booking_form_fills_in_for_a_student_with_credit(self):
        out = self._rpc('fitness.booking', 'onchange', [[], {
            'student_id': self.mine.id}, ['student_id'], {
            'student_id': {}, 'fitness_choosable_line_ids': {}}])
        self.assertNotIn('error', out, out.get('error', {}).get('data', {}).get('message'))

    def test_the_lines_themselves_stay_closed_to_her(self):
        out = self._rpc('fitness.booking', 'web_read', [self.booking.ids], {
            'specification': {'fitness_choosable_line_ids': {
                'fields': {'display_name': {}}}}})
        self.assertIn('error', out, 'order line names reached a manager without '
                      'Sales rights: %s' % out.get('result'))

    def _form_specification(self):
        """What the browser asks for when it opens the booking form: every
        field of the form view she is served, not a hand-picked few. Three
        named fields once hid a fourth that failed the form."""
        views = self._rpc('fitness.booking', 'get_views', [], {
            'views': [[False, 'form']]})
        self.assertNotIn('error', views)
        form = views['result']['views']['form']
        fields = views['result']['models']['fitness.booking']['fields']
        arch = etree.fromstring(form['arch'])
        spec = {}
        for node in arch.iter('field'):
            if any(p.tag == 'field' for p in node.iterancestors()):
                continue  # a sub-view's column, read by its own model
            name = node.get('name')
            if fields.get(name, {}).get('type') == 'many2one':
                spec[name] = {'fields': {'display_name': {}}}
            else:
                spec[name] = {}
        self.assertIn('fitness_choosable_subscription_ids', spec)
        self.assertIn('fitness_choosable_line_ids', spec)
        return spec

    def test_she_opens_every_field_of_the_real_form(self):
        spec = self._form_specification()
        for booking in (self.booking, self._book(self.hers, self.event,
                                                   subscription_id=self.her_sub.id)):
            out = self._rpc('fitness.booking', 'web_read', [booking.ids],
                            {'specification': spec})
            self.assertNotIn('error', out, '%s: %s' % (
                booking.student_id.name,
                out.get('error', {}).get('data', {}).get('message')))

    def test_a_new_booking_form_fills_in_every_field(self):
        spec = self._form_specification()
        out = self._rpc('fitness.booking', 'onchange', [[], {
            'student_id': self.mine.id}, ['student_id'], spec])
        self.assertNotIn('error', out, out.get('error', {}).get('data', {}).get('message'))
