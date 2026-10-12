# -*- coding: utf-8 -*-
"""Attended and No-show only from the moment the class starts.

The start-time rule bound the instructor and was waived for the manager,
in the model and in the view. A manager marked Laia a no-show thirty
hours before her class, and the mark took her credit with no way back.

Now nobody marks before the start: not the manager, not the instructor,
and the student never. Held in the model, on the action methods AND on a
plain write of state, because a write is what an RPC call, an import or
a server action does. From the start itself it is allowed for the
manager and the instructor, which is when the register is taken.

The boundary is tested one second either side, on a pinned clock. One
test goes through /web/dataset/call_button as a real non-admin manager,
because that is the door the back-office buttons use.
"""
import json
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)          # 09:00 in Madrid
START = PINNED + timedelta(hours=2)              # class at 11:00 Madrid
ONE = timedelta(seconds=1)
PASSWORD = 'mark-start-Pw-2026'


class MarkFixture:

    def _setup_marks(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'MS Barre', 'classroom_type': 'barre',
            'session_type': 'group', 'level': 'all', 'duration': 55,
        })
        self.pack = self.env['product.template'].create({
            'name': 'MS Pack', 'type': 'service', 'list_price': 100.0,
            'fitness_is_package': True, 'fitness_class_count': 10,
            'fitness_validity_days': 90, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group',
        })
        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.manager = Users.create({
            'name': 'MS Manager', 'login': 'ms.manager@example.invalid',
            'password': PASSWORD, 'lang': 'en_US', 'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('fitness_core.group_fitness_manager').id,
            ])],
        })
        self.teacher = Users.create({
            'name': 'MS Teacher', 'login': 'ms.teacher@example.invalid',
            'password': PASSWORD, 'lang': 'en_US', 'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('fitness_core.group_fitness_teacher').id,
            ])],
        })
        self._seq = 0

    def _new_student(self):
        # One per booking: every booking here is at the same instant, and
        # one student cannot hold two overlapping classes.
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'MS Student %d' % self._seq,
                'login': 'ms.student%d@example.invalid' % self._seq,
                'password': PASSWORD, 'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            })

    def _booking(self):
        student = self._new_student()
        event = self.env['calendar.event'].sudo().create({
            'name': 'MS class', 'start': START,
            'stop': START + timedelta(minutes=55),
            'class_type_id': self.class_type.id,
            'is_fitness_class': True, 'capacity': 10,
            'user_id': self.teacher.id,
        })
        order = self.env['sale.order'].sudo().create(
            {'partner_id': student.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            'fitness_class_type': 'barre',
        })
        order.action_confirm()
        return self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': order.order_line[:1].id,
        })


@tagged('post_install', '-at_install')
class TestMarksWaitForTheStart(MarkFixture, TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self._setup_marks()

    def _at(self, moment):
        return common.freeze_time(moment)

    def _ways(self, booking, user, state):
        """Every route a mark can take, as that user."""
        method = ('action_mark_attended' if state == 'attended'
                  else 'action_mark_no_show')
        return (
            ('action', lambda: getattr(booking.with_user(user), method)()),
            ('write', lambda: booking.with_user(user).write({'state': state})),
        )

    def test_nobody_marks_one_second_before_the_start(self):
        for who in ('manager', 'teacher', 'student'):
            for state in ('attended', 'no_show'):
                booking = self._booking()
                user = (booking.student_id.user_ids[:1] if who == 'student'
                        else getattr(self, who))
                for how, call in self._ways(booking, user, state):
                    with self.subTest(user=user.login, state=state, how=how):
                        with self._at(START - ONE):
                            with self.assertRaises(UserError):
                                call()
                        self.assertEqual(booking.state, 'booked')

    def test_manager_and_instructor_mark_from_the_start(self):
        for user in (self.manager, self.teacher):
            for moment in (START, START + ONE):
                for state in ('attended', 'no_show'):
                    for how in ('action', 'write'):
                        booking = self._booking()
                        call = dict(self._ways(booking, user, state))[how]
                        with self.subTest(user=user.login, at=str(moment),
                                          state=state, how=how):
                            with self._at(moment):
                                call()
                            self.assertEqual(booking.state, state)

    def test_the_student_never_marks_even_after_the_start(self):
        for state in ('attended', 'no_show'):
            booking = self._booking()
            student = booking.student_id.user_ids[:1]
            for how, call in self._ways(booking, student, state):
                with self.subTest(state=state, how=how):
                    with self._at(START + timedelta(hours=1)):
                        with self.assertRaises(UserError):
                            call()
                    self.assertEqual(booking.state, 'booked')

    def test_the_student_cannot_take_a_mark_off(self):
        booking = self._booking()
        with self._at(START + ONE):
            booking.with_user(self.manager).action_mark_no_show()
            with self.assertRaises(UserError):
                booking.with_user(booking.student_id.user_ids[:1]).write(
                    {'state': 'booked'})
        self.assertEqual(booking.state, 'no_show')

    def test_a_cancelled_booking_cannot_be_marked(self):
        booking = self._booking()
        booking.sudo().with_context(
            _admin_cancel_direct=True).action_cancel()
        self.assertEqual(booking.state, 'cancelled')
        with self._at(START + ONE):
            with self.assertRaises(UserError):
                booking.with_user(self.manager).action_mark_attended()
            with self.assertRaises(UserError):
                booking.with_user(self.manager).action_mark_no_show()
        self.assertEqual(booking.state, 'cancelled')

    def test_the_refusal_is_a_sentence_in_her_language(self):
        self.env['res.lang']._activate_and_install_lang('es_ES')
        self.manager.lang = 'es_ES'
        booking = self._booking()
        with self._at(START - ONE):
            with self.assertRaises(UserError) as caught:
                booking.with_user(self.manager).with_context(
                    lang='es_ES').action_mark_no_show()
        self.assertIn('aún no ha empezado', str(caught.exception))


@tagged('post_install', '-at_install')
class TestMarksWaitForTheStartOverHttp(MarkFixture, HttpCase):
    """The back office's own door, as a non-admin manager."""

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self._setup_marks()

    def _call_button(self, booking, method):
        self.authenticate(self.manager.login, PASSWORD)
        res = self.url_open(
            '/web/dataset/call_button/fitness.booking/%s' % method,
            data=json.dumps({
                'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                'params': {'model': 'fitness.booking', 'method': method,
                           'args': [[booking.id]], 'kwargs': {}},
            }),
            headers={'Content-Type': 'application/json'})
        return res.json()

    def test_call_button_refuses_before_and_allows_after(self):
        booking = self._booking()
        with common.freeze_time(START - ONE):
            out = self._call_button(booking, 'action_mark_no_show')
        self.assertIn('error', out, 'a no-show before the start went through')
        self.assertIn("hasn't started yet",
                      out['error']['data']['message'])
        booking.invalidate_recordset()
        self.assertEqual(booking.state, 'booked')

        with common.freeze_time(START + ONE):
            out = self._call_button(booking, 'action_mark_no_show')
        self.assertNotIn('error', out, out.get('error'))
        booking.invalidate_recordset()
        self.assertEqual(booking.state, 'no_show')
