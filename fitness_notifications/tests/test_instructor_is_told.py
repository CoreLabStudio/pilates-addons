# -*- coding: utf-8 -*-
"""The instructor is told when a student is booked into her class.

Nobody was: every recipient on the booking path was the student.
Maridelvis had nothing for a 1-on-1 with Carlota on 16 October.

Bell and push to the instructor, once per booking, in her language. Not
for a class that has already started (a recording after the fact), not
for the Clase Fija bulk placement, and not under the silence flag. The
student is not sent the instructor's notice.

Push counted with the real sender replaced by a recorder. Clock pinned.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)

PINNED = datetime(2026, 11, 4, 8, 0, 0)
NEUTRALIZED = 'database.is_neutralized'


@tagged('post_install', '-at_install')
class TestInstructorIsTold(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_and_install_lang('es_ES')

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_PUBLIC, 'pub-for-test')
        Param.set_param(PARAM_PRIVATE, 'priv-for-test')
        Param.set_param(NEUTRALIZED, 'False')
        Param.set_param('fitness.opening_date', '')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        self.pushed = []
        real_send = web_push.send

        def recorder(endpoint, *args, **kwargs):
            self.pushed.append(endpoint)
            return 201, ''
        web_push.send = recorder

        def restore():
            web_push.send = real_send
        self.addCleanup(restore)

        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.teacher = Users.create({
            'name': 'IT Maridelvis', 'login': 'it.teacher@example.invalid',
            'email': 'it.teacher@example.invalid', 'lang': 'en_US',
            'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('fitness_core.group_fitness_teacher').id])],
        })
        self.env['fitness.push.subscription']._register_device(
            self.teacher.id, 'https://push.example.invalid/teacher',
            'pub', 'auth')
        self.private_type = self.env['fitness.class.type'].create({
            'name': 'IT Private', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'private'})
        self.group_type = self.env['fitness.class.type'].create({
            'name': 'IT Group', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        self._seq = 0

    def _student(self):
        self._seq += 1
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'IT Student %d' % self._seq,
                'login': 'it.%d@example.invalid' % self._seq,
                'email': 'it.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])],
            })
        return user.partner_id

    def _line(self, partner, session):
        tmpl = self.env['product.template'].create({
            'name': 'IT %s pack' % session, 'list_price': 50.0,
            'type': 'service', 'fitness_is_package': True,
            'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'reformer', 'fitness_session_type': session})
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.action_confirm()
        return order.order_line[:1]

    def _event(self, ctype, start=None):
        start = start or PINNED + timedelta(days=2, hours=2)
        return self.env['calendar.event'].sudo().create({
            'name': 'IT %s class' % ctype.session_type, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True,
            'session_type': ctype.session_type, 'user_id': self.teacher.id,
        })

    def _book(self, event, ctx=None, partner=None):
        partner = partner or self._student()
        line = self._line(partner, event.session_type)
        return self.env['fitness.booking'].sudo().with_context(
            **(ctx or {})).create({
                'student_id': partner.id,
                'calendar_event_id': event.id,
                'package_order_line_id': line.id,
                'manager_override_timewindow': True,
            })

    def _told(self, user=None):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', (user or self.teacher).id),
            ('notification_type', '=', 'student_booked')])

    def test_a_private_booking_tells_her_by_bell_and_push(self):
        booking = self._book(self._event(self.private_type))
        told = self._told()
        self.assertEqual(len(told), 1)
        self.assertEqual(self.pushed.count(
            'https://push.example.invalid/teacher'), 1)
        self.assertIn(booking.student_id.name, told.body)
        # 6 Nov 10:00 UTC is 11:00 in Madrid (CET).
        self.assertIn('6 Nov 11:00', told.body, 'not on studio time')
        self.assertEqual(told.action_url,
                         '/my/instructor/classes/%d'
                         % booking.calendar_event_id.id)

    def test_once_per_booking(self):
        event = self._event(self.group_type)
        first = self._book(event)
        self._book(event)
        self.assertEqual(len(self._told()), 2)
        first.with_user(first.student_id.user_ids[:1]).action_cancel()
        self.assertEqual(len(self._told()), 2,
                         'a cancellation told her of a new booking')

    def test_the_student_is_not_sent_it(self):
        booking = self._book(self._event(self.private_type))
        self.assertFalse(self._told(booking.student_id.user_ids[:1]))

    def test_in_her_language(self):
        self.teacher.lang = 'es_ES'
        self._book(self._event(self.private_type))
        told = self._told()
        self.assertTrue(told.title.startswith('Nueva reserva'), told.title)
        self.assertIn('nov', told.body)

    def test_not_for_the_bulk_placement(self):
        self._book(self._event(self.group_type),
                   ctx={'_fitness_clase_fija_placement': True})
        self.assertFalse(self._told())
        self.assertFalse(self.pushed)

    def test_not_under_the_silence_flag(self):
        self._book(self._event(self.private_type),
                   ctx={'skip_fitness_notification': True})
        self.assertFalse(self._told())
        self.assertFalse(self.pushed)

    def test_not_for_a_recording_after_the_fact(self):
        start = PINNED + timedelta(days=1)
        booking = self._book(self._event(self.private_type, start=start))
        self._told().unlink()
        # The same booking seen once the class has begun: what a walk-in
        # recorded at the desk looks like.
        with common.freeze_time(start + timedelta(minutes=5)):
            self.env['fitness.booking']._maybe_notify_instructor(booking)
        self.assertFalse(self._told())

    def test_a_class_with_no_instructor_tells_nobody(self):
        event = self._event(self.private_type)
        event.user_id = False
        self._book(event)
        self.assertFalse(self.env['fitness.notification'].sudo().search(
            [('notification_type', '=', 'student_booked')]))
