# -*- coding: utf-8 -*-
"""A wrong mark has a way back, and the way back cannot mint a credit.

Before this, a marked booking offered nothing: both marks refuse what is
not Booked, action_cancel refuses what IS marked, every header button
hid itself. Laia was marked a no-show and her pack credit was gone with
no route to return it.

Now a no-show offers "Mark as Attended" and "Cancel with reason"; an
attended booking offers "Mark as No-show" and "Cancel with reason". Each
asks why and writes who, when, what and why to the chatter. A mark never
changes a credit (owner decision Q4 a); only Cancel with reason, ticked,
returns one - once.

Carried across from the review of f829cd7 / 3fdf0ff, not cherry-picked:
five full cycles leave the balance where it started, a repeat is
refused, manager-only including over /web/dataset/call_button, and a
cancelled booking cannot be marked or corrected.

Clock pinned; every class is booked before it starts and marked after.
"""
import json
from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, common, tagged

PINNED = datetime(2026, 11, 2, 8, 0, 0)      # a Monday, 09:00 Madrid
PASSWORD = 'mark-fix-Pw-2026'
AFTER = timedelta(minutes=70)                # once the class has run


class CorrectionFixture:

    def _setup_fixture(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'MC Barre', 'classroom_type': 'barre',
            'session_type': 'group', 'level': 'all', 'duration': 55,
        })
        self.pack = self.env['product.template'].create({
            'name': 'MC Pack', 'type': 'service', 'list_price': 100.0,
            'fitness_is_package': True, 'fitness_class_count': 10,
            'fitness_validity_days': 90, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group',
        })
        Users = self.env['res.users'].with_context(no_reset_password=True)

        def user(login, groups):
            return Users.create({
                'name': login, 'login': login, 'password': PASSWORD,
                'email': login, 'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])],
            })
        self.manager = user('mc.manager@example.invalid', [
            'base.group_user', 'fitness_core.group_fitness_manager'])
        self.teacher = user('mc.teacher@example.invalid', [
            'base.group_portal', 'fitness_core.group_fitness_teacher'])
        self.student = user('mc.student@example.invalid', [
            'base.group_portal', 'fitness_core.group_fitness_student'])
        order = self.env['sale.order'].sudo().create(
            {'partner_id': self.student.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'barre',
        })
        order.action_confirm()
        self.line = order.order_line[:1]
        self._day = 0

    def _left(self):
        self.line.invalidate_recordset(['fitness_remaining_classes'])
        return self.line.fitness_remaining_classes

    def _booking(self):
        """A class tomorrow-or-later, booked now. Returns (booking, start)."""
        self._day += 1
        start = PINNED + timedelta(days=self._day, hours=2)
        event = self.env['calendar.event'].sudo().create({
            'name': 'MC class %d' % self._day, 'start': start,
            'stop': start + timedelta(minutes=55),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
            'capacity': 10, 'user_id': self.teacher.id,
        })
        with common.freeze_time(start - timedelta(hours=1)):
            booking = self.env['fitness.booking'].sudo().create({
                'student_id': self.student.partner_id.id,
                'calendar_event_id': event.id,
                'package_order_line_id': self.line.id,
            })
        return booking, start

    def _marked(self, state):
        booking, start = self._booking()
        with common.freeze_time(start + AFTER):
            getattr(booking.with_user(self.teacher),
                    'action_mark_' + state)()
        self.assertEqual(booking.state, state)
        return booking, start


@tagged('post_install', '-at_install')
class TestMarkCorrections(CorrectionFixture, TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self._setup_fixture()

    def _as_manager(self, booking):
        return booking.with_user(self.manager)

    def _chatter(self, booking):
        return ' '.join(booking.sudo().message_ids.mapped('body'))

    # -- flipping a mark ---------------------------------------------------
    def test_a_no_show_becomes_attended_and_no_credit_moves(self):
        booking, start = self._marked('no_show')
        before = self._left()
        with common.freeze_time(start + AFTER + timedelta(hours=1)):
            self._as_manager(booking)._correct_mark(
                'attended', 'She was in the room')
        self.assertEqual(booking.state, 'attended')
        self.assertEqual(self._left(), before, 'a mark changed a credit')
        self.assertEqual(booking.marked_by_id, self.manager)
        log = self._chatter(booking)
        self.assertIn('She was in the room', log)
        self.assertIn(self.manager.name, log)
        self.assertIn('No-show', log)
        self.assertIn('Attended', log)

    def test_attended_becomes_a_no_show_and_no_credit_moves(self):
        booking, start = self._marked('attended')
        before = self._left()
        with common.freeze_time(start + AFTER):
            self._as_manager(booking)._correct_mark(
                'no_show', 'Wrong student ticked')
        self.assertEqual(booking.state, 'no_show')
        self.assertEqual(self._left(), before)

    def test_a_reason_is_required_everywhere(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            for blank in ('', '   ', False):
                with self.assertRaises(UserError):
                    self._as_manager(booking)._correct_mark('attended', blank)
                with self.assertRaises(UserError):
                    self._as_manager(booking)._cancel_marked_with_reason(
                        blank, True)
        self.assertEqual(booking.state, 'no_show')

    def test_a_correction_to_the_same_mark_is_refused(self):
        booking, start = self._marked('attended')
        with common.freeze_time(start + AFTER):
            with self.assertRaises(UserError):
                self._as_manager(booking)._correct_mark('attended', 'again')

    # -- who may -----------------------------------------------------------
    def test_only_a_manager_corrects(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            for user in (self.teacher, self.student):
                with self.assertRaises(AccessError):
                    booking.with_user(user)._correct_mark('attended', 'x')
                with self.assertRaises(AccessError):
                    booking.with_user(user)._cancel_marked_with_reason(
                        'x', True)
                with self.assertRaises(AccessError):
                    booking.with_user(user).action_open_cancel_with_reason()
        self.assertEqual(booking.state, 'no_show')

    # -- cancel with reason ------------------------------------------------
    def test_ticked_cancel_returns_the_pack_credit_once(self):
        """Laia's case, end to end."""
        start_balance = self._left()
        booking, start = self._marked('no_show')
        self.assertEqual(self._left(), start_balance - 1)
        with common.freeze_time(start + AFTER):
            self._as_manager(booking)._cancel_marked_with_reason(
                'Rang in ill before the class', True)
        self.assertEqual(booking.state, 'cancelled')
        self.assertTrue(booking.credit_returned)
        self.assertEqual(self._left(), start_balance)
        # never twice: not again by this route, nor by Give the Credit Back
        with self.assertRaises(UserError):
            self._as_manager(booking)._cancel_marked_with_reason('again', True)
        with self.assertRaises(UserError):
            self._as_manager(booking)._give_credit_back('again')
        self.assertEqual(self._left(), start_balance)
        self.assertIn('Rang in ill before the class', self._chatter(booking))

    def test_unticked_cancel_returns_nothing(self):
        start_balance = self._left()
        booking, start = self._marked('attended')
        with common.freeze_time(start + AFTER):
            self._as_manager(booking)._cancel_marked_with_reason(
                'Booked onto the wrong class', False)
        self.assertEqual(booking.state, 'cancelled')
        self.assertFalse(booking.credit_returned)
        self.assertEqual(self._left(), start_balance - 1)

    def test_the_tick_is_on_by_default(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            action = self._as_manager(booking).action_open_cancel_with_reason()
        wizard = self.env['fitness.booking.mark.wizard'].browse(
            action['res_id'])
        self.assertTrue(wizard.return_credit)
        self.assertEqual(wizard.kind, 'cancel')

    def test_the_wizard_returns_an_action_a_button_accepts(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            action = self._as_manager(booking).action_open_mark_as_attended()
            self.assertEqual(action['type'], 'ir.actions.act_window')
            wizard = self.env['fitness.booking.mark.wizard'].with_user(
                self.manager).browse(action['res_id'])
            wizard.reason = 'Arrived late, did the class'
            result = wizard.action_confirm()
        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})
        self.assertEqual(booking.state, 'attended')

    # -- the loop cannot be run round --------------------------------------
    def test_five_cycles_leave_the_balance_unchanged(self):
        start_balance = self._left()
        for cycle in range(5):
            booking, start = self._booking()
            self.assertEqual(self._left(), start_balance - 1,
                             'cycle %d: booking did not cost one' % cycle)
            with common.freeze_time(start + AFTER):
                booking.with_user(self.teacher).action_mark_no_show()
                self.assertEqual(self._left(), start_balance - 1,
                                 'cycle %d: the mark moved a credit' % cycle)
                self._as_manager(booking)._correct_mark('attended', 'came')
                self._as_manager(booking)._correct_mark('no_show', 'did not')
                self.assertEqual(self._left(), start_balance - 1,
                                 'cycle %d: a correction moved one' % cycle)
                self._as_manager(booking)._cancel_marked_with_reason(
                    'cycle %d' % cycle, True)
            self.assertEqual(self._left(), start_balance,
                             'cycle %d: ended off balance' % cycle)

    def test_a_cancelled_booking_cannot_be_marked_or_corrected(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            self._as_manager(booking)._cancel_marked_with_reason('x', False)
            for call in (
                    lambda: self._as_manager(booking).action_mark_attended(),
                    lambda: self._as_manager(booking).action_mark_no_show(),
                    lambda: self._as_manager(booking)._correct_mark(
                        'attended', 'y'),
                    lambda: self._as_manager(booking)
                    .action_open_cancel_with_reason()):
                with self.assertRaises(UserError):
                    call()
        self.assertEqual(booking.state, 'cancelled')

    def test_a_booked_booking_is_not_cancelled_by_this_route(self):
        booking, start = self._booking()
        with common.freeze_time(start + AFTER):
            with self.assertRaises(UserError):
                self._as_manager(booking)._cancel_marked_with_reason('x', True)
        self.assertEqual(booking.state, 'booked')

    # -- what the screens offer --------------------------------------------
    def test_the_form_and_roster_offer_the_corrections(self):
        for model in ('fitness.booking', 'calendar.event'):
            arch = self.env[model].with_user(self.manager).get_view(
                view_type='form')['arch']
            for name in ('action_open_mark_as_attended',
                         'action_open_mark_as_no_show',
                         'action_open_cancel_with_reason',
                         'fitness_class_started'):
                self.assertIn(name, arch, '%s lacks %s' % (model, name))

    def test_class_started_flips_at_the_start(self):
        booking, start = self._booking()
        with common.freeze_time(start - timedelta(seconds=1)):
            booking.invalidate_recordset(['fitness_class_started'])
            self.assertFalse(booking.fitness_class_started)
        with common.freeze_time(start):
            booking.invalidate_recordset(['fitness_class_started'])
            self.assertTrue(booking.fitness_class_started)


@tagged('post_install', '-at_install')
class TestMarkCorrectionsOverHttp(CorrectionFixture, HttpCase):

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self._setup_fixture()

    def _call(self, login, booking, method):
        self.authenticate(login, PASSWORD)
        res = self.url_open(
            '/web/dataset/call_button/fitness.booking/%s' % method,
            data=json.dumps({
                'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                'params': {'model': 'fitness.booking', 'method': method,
                           'args': [[booking.id]], 'kwargs': {}},
            }),
            headers={'Content-Type': 'application/json'})
        return res.json()

    def test_only_the_manager_opens_a_correction(self):
        booking, start = self._marked('no_show')
        with common.freeze_time(start + AFTER):
            for login in (self.teacher.login, self.student.login):
                out = self._call(login, booking,
                                 'action_open_cancel_with_reason')
                self.assertIn('error', out, '%s opened it' % login)
            out = self._call(self.manager.login, booking,
                             'action_open_cancel_with_reason')
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['result']['res_model'],
                         'fitness.booking.mark.wizard')
