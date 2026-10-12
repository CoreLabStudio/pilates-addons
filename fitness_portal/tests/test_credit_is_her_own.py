# -*- coding: utf-8 -*-
"""A booking is paid with the booked student's own credit, on every path.

Independent QA booked one student by hand while naming another
student's pack line. The booking went through and the other student's
pack fell from 5 to 4; nobody told her, and the plain manager who did
it cannot even read order lines to see whose credit she spent. The
booking form's dropdown offered every student's packs and memberships.

The studio does not share packs, so the rule has no exception: the
constraint refuses another contact's line or membership on create and
on write, whoever calls it and however. The form now offers only her
own spendable lines and live memberships. Existing bookings are not
rewritten, and the duplicate-merge flow still leaves every booking on
its own student's credit.

The clock is pinned (the fixture), and each language is installed
explicitly before a refusal is read in it.
"""
import json

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_subscriptions.tests.test_makeup_credit_returned \
    import MakeUpCreditFixture

PASSWORD = 'own-credit-Pw-2026'
REFUSED = {
    'en_US': 'can only be paid with the student\'s own credit',
    'es_ES': 'solo se puede pagar con el crédito propio de la alumna',
    'ca_ES': 'només es pot pagar amb el crèdit propi de l\'alumna',
}


def _manager(env, login, lang='en_US', sales=False):
    """A fitness manager; with no Sales rights unless asked, as on
    production, where only the owner has them. The owner is the one whose
    form offered every student's packs."""
    groups = ['base.group_user', 'fitness_core.group_fitness_manager']
    if sales:
        groups.append('sales_team.group_sale_manager')
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': 'OC Manager %s' % lang, 'login': login, 'password': PASSWORD,
        'lang': lang, 'tz': 'Europe/Madrid',
        'group_ids': [(6, 0, [env.ref(g).id for g in groups])],
    })


class OwnCreditFixture(MakeUpCreditFixture):

    def setUp(self):
        super().setUp()
        self.mine = self._student('ocmine').partner_id
        self.hers = self._student('ochers').partner_id
        self.her_line = self._packline(self.hers)
        self.her_sub = self._membership(self.hers)
        self.event = self._class(30)

    def _left(self, line):
        line.invalidate_recordset()
        return line.fitness_remaining_classes


@tagged('post_install', '-at_install')
class TestNobodyElsesCredit(OwnCreditFixture):

    def test_another_students_pack_is_refused_and_untouched(self):
        self.assertEqual(self._left(self.her_line), 5)
        with self.assertRaises(ValidationError) as caught:
            self._book(self.mine, self.event,
                       package_order_line_id=self.her_line.id)
        self.assertIn(REFUSED['en_US'], str(caught.exception))
        self.assertIn(self.hers.name, str(caught.exception))
        self.assertEqual(self._left(self.her_line), 5,
                         'her pack must keep all five classes')
        self.assertFalse(self.env['fitness.booking'].search(
            [('student_id', '=', self.mine.id)]))

    def test_another_students_membership_is_refused(self):
        with self.assertRaises(ValidationError) as caught:
            self._book(self.mine, self.event, subscription_id=self.her_sub.id)
        self.assertIn(REFUSED['en_US'], str(caught.exception))
        self.assertFalse(self.env['fitness.booking'].search(
            [('student_id', '=', self.mine.id)]))

    def test_her_own_pack_still_pays(self):
        my_line = self._packline(self.mine)
        booking = self._book(self.mine, self.event,
                             package_order_line_id=my_line.id)
        self.assertEqual(booking.package_order_line_id, my_line)
        self.assertEqual(self._left(my_line), 4)
        self.assertEqual(self._left(self.her_line), 5)

    def test_moving_a_booking_onto_her_credit_is_refused(self):
        my_line = self._packline(self.mine)
        booking = self._book(self.mine, self.event)
        self.assertEqual(booking.package_order_line_id, my_line)
        with self.assertRaises(ValidationError):
            booking.write({'package_order_line_id': self.her_line.id})
        with self.assertRaises(ValidationError):
            booking.write({'subscription_id': self.her_sub.id})

    def test_changing_the_student_keeps_the_credit_with_its_owner(self):
        my_line = self._packline(self.mine)
        booking = self._book(self.mine, self.event)
        self.assertEqual(booking.package_order_line_id, my_line)
        with self.assertRaises(ValidationError):
            booking.write({'student_id': self.hers.id})

    def test_existing_bookings_are_left_alone(self):
        """A row already on someone else's line is not rewritten, and the
        studio can still work with it: only a change of who or what pays
        is checked."""
        my_line = self._packline(self.mine)
        booking = self._book(self.mine, self.event)
        self.env.cr.execute(
            "UPDATE fitness_booking SET package_order_line_id = %s "
            "WHERE id = %s", (self.her_line.id, booking.id))
        booking.invalidate_recordset()
        booking.write({'cancellation_reason': 'touched'})
        self.assertEqual(booking.package_order_line_id, self.her_line)
        self.assertEqual(self._left(my_line), 4)

    def test_the_refusal_is_in_the_managers_language(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for lang in ('en_US', 'es_ES', 'ca_ES'):
            with self.subTest(lang=lang):
                mgr = _manager(self.env, 'oc.lang.%s@example.invalid' % lang,
                               lang, sales=True)
                # The web client sends her language in the context, as here.
                with self.assertRaises(ValidationError) as caught:
                    self.env['fitness.booking'].with_user(mgr).with_context(
                        lang=mgr.lang).create({
                        'student_id': self.mine.id,
                        'calendar_event_id': self.event.id,
                        'package_order_line_id': self.her_line.id,
                        'manager_override_timewindow': True})
                self.assertIn(REFUSED[lang], str(caught.exception))
        self.assertEqual(self._left(self.her_line), 5)


@tagged('post_install', '-at_install')
class TestTheFormOffersOnlyHerOwn(OwnCreditFixture):

    def test_only_her_spendable_packs_are_offered(self):
        mine_live = self._packline(self.mine)
        mine_spent = self._packline(self.mine)
        mine_spent.fitness_remaining_classes = 0
        mine_cancelled = self._packline(self.mine)
        mine_cancelled.order_id._action_cancel()
        draft = self.env['fitness.booking'].new({'student_id': self.mine.id})
        self.assertEqual(draft.fitness_choosable_line_ids._origin, mine_live)

    def test_only_her_live_memberships_are_offered(self):
        mine_sub = self._membership(self.mine)
        draft = self.env['fitness.booking'].new({'student_id': self.mine.id})
        self.assertEqual(
            draft.fitness_choosable_subscription_ids._origin, mine_sub)

    def test_nothing_is_offered_before_a_student_is_chosen(self):
        draft = self.env['fitness.booking'].new({})
        self.assertFalse(draft.fitness_choosable_line_ids)
        self.assertFalse(draft.fitness_choosable_subscription_ids)

    def test_the_form_uses_those_lists(self):
        arch = self.env['fitness.booking'].get_views(
            [(False, 'form')])['views']['form']['arch']
        self.assertIn("('id', 'in', fitness_choosable_line_ids)", arch)
        self.assertIn("('id', 'in', fitness_choosable_subscription_ids)", arch)


@tagged('post_install', '-at_install')
class TestMergeKeepsCreditWithItsOwner(OwnCreditFixture):

    def test_a_merged_duplicate_brings_its_pack_and_bookings_along(self):
        """The studio's own join: the duplicate's pack and the booking it
        paid for both move to the survivor, so ownership still matches and
        she can go on spending it."""
        email = 'oc.mine@example.invalid'
        self.mine.email = email
        dup = self.env['res.partner'].create({'name': 'OC Mine', 'email': email})
        dup_line = self._packline(dup)
        booking = self._book(dup, self.event)
        self.assertEqual(booking.package_order_line_id, dup_line)

        dup._fitness_join_into(self.mine)

        booking.invalidate_recordset()
        dup_line.invalidate_recordset()
        self.assertEqual(booking.student_id, self.mine)
        self.assertEqual(dup_line.order_id.partner_id, self.mine)
        self.assertEqual(dup_line.order_partner_id, self.mine)
        # Re-checked through the constraint, not just read.
        booking._check_credit_is_her_own()
        second = self._book(self.mine, self._class(32, 'OC second'),
                            package_order_line_id=dup_line.id)
        self.assertEqual(second.package_order_line_id, dup_line)
        self.assertEqual(self._left(dup_line), 3)


class RpcMixin:

    def _rpc(self, model, method, args, kwargs=None):
        res = self.url_open(
            '/web/dataset/call_kw/%s/%s' % (model, method),
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'model': model, 'method': method,
                                        'args': args,
                                        'kwargs': kwargs or {}}}),
            headers={'Content-Type': 'application/json'})
        return res.json()


@tagged('post_install', '-at_install')
class TestTheFormOverRpc(RpcMixin, OwnCreditFixture, HttpCase):
    """The owner's case on production: a manager WITH Sales rights saving
    the booking form, over the endpoint the browser uses."""

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'oc.owner@example.invalid',
                                sales=True)
        self.authenticate(self.manager.login, PASSWORD)

    def test_saving_the_form_with_another_students_pack_is_refused(self):
        out = self._rpc('fitness.booking', 'web_save', [[], {
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'package_order_line_id': self.her_line.id,
            'manager_override_timewindow': True}], {'specification': {}})
        self.assertIn('error', out)
        self.assertIn(REFUSED['en_US'], out['error']['data']['message'])
        self.assertEqual(self._left(self.her_line), 5)

    def test_saving_the_form_with_her_membership_is_refused(self):
        out = self._rpc('fitness.booking', 'web_save', [[], {
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'subscription_id': self.her_sub.id,
            'manager_override_timewindow': True}], {'specification': {}})
        self.assertIn('error', out)
        self.assertIn(REFUSED['en_US'], out['error']['data']['message'])

    def test_her_own_pack_books_through_the_form(self):
        my_line = self._packline(self.mine)
        out = self._rpc('fitness.booking', 'web_save', [[], {
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'package_order_line_id': my_line.id,
            'manager_override_timewindow': True}], {'specification': {}})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(self._left(my_line), 4)
        self.assertEqual(self._left(self.her_line), 5)


@tagged('post_install', '-at_install')
class TestPlainManagerIsNotWidened(RpcMixin, OwnCreditFixture, HttpCase):
    """A fitness manager with no Sales rights, over RPC. On this code she
    cannot name a line at all (reading it is refused before any rule runs);
    what matters here is that nothing in this fix opens anything to her:
    another student's credit stays untouched and orders stay closed."""

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'oc.rpc@example.invalid')
        self.assertFalse(
            self.env['sale.order.line'].with_user(self.manager)
            .has_access('read'), 'fixture: she must have no Sales rights')
        self.authenticate(self.manager.login, PASSWORD)

    def test_naming_another_students_line_is_refused(self):
        out = self._rpc('fitness.booking', 'create', [{
            'student_id': self.mine.id, 'calendar_event_id': self.event.id,
            'package_order_line_id': self.her_line.id,
            'manager_override_timewindow': True}])
        self.assertIn('error', out)
        self.assertEqual(self._left(self.her_line), 5)
        self.assertFalse(self.env['fitness.booking'].search(
            [('student_id', '=', self.mine.id)]))

    def test_the_choosable_lists_give_her_no_order_data(self):
        """The new fields are computed as superuser; reading them must
        not hand her what reading order lines would refuse."""
        my_line = self._packline(self.mine)
        out = self._rpc('fitness.booking', 'onchange', [[], {
            'student_id': self.mine.id}, ['student_id'], {
            'student_id': {}, 'fitness_choosable_line_ids': {
                'fields': {'display_name': {}}}}])
        self.assertIn('error', out, 'line names reached a manager '
                      'without Sales rights: %s' % out.get('result'))
        out = self._rpc('sale.order.line', 'read',
                        [[my_line.id], ['name']])
        self.assertIn('error', out)

    def test_orders_stay_closed_to_her(self):
        for model, rec in (('sale.order', self.her_line.order_id),
                           ('sale.order.line', self.her_line)):
            with self.subTest(model=model):
                out = self._rpc(model, 'search_read',
                                [[('id', '=', rec.id)], ['name']])
                self.assertIn('error', out, '%s readable over RPC' % model)
                with self.assertRaises(AccessError):
                    rec.with_user(self.manager).read(['name'])
