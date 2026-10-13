# -*- coding: utf-8 -*-
"""A booking made under skip_fitness_notification rings nothing.

booking_confirmed honoured the flag; credit_used, credit_low and
credit_zero, fired from the same create(), did not. So a booking the
caller wanted silent - a walk-in recorded at the desk - still told the
student a credit was used and how many she had left.

Counted on every channel: bells, mails, and pushes through a recorder in
place of the real sender (web_push.send), with a VAPID keypair and a
registered device, so a push that would have left is counted rather than
skipped for an unrelated reason. The negatives are the same bookings
without the flag, which must ring exactly as before.

Clock pinned, language explicit.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)

PINNED = datetime(2026, 11, 4, 8, 0, 0)
CREDIT_TYPES = ('booking_confirmed', 'credit_used', 'credit_low',
                'credit_zero')


@tagged('post_install', '-at_install')
class TestSilentBookingBells(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_PUBLIC, 'pub-for-test')
        Param.set_param(PARAM_PRIVATE, 'priv-for-test')
        Param.set_param('database.is_neutralized', 'False')
        Param.set_param('fitness.opening_date', '')
        Param.set_param('fitness_notifications.send_confirmation', 'True')
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
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'SB Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        self._seq = 0

    def _student_with_pack(self, classes):
        self._seq += 1
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'SB Student %d' % self._seq,
                'login': 'sb.%d@example.invalid' % self._seq,
                'email': 'sb.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])],
            })
        self.env['fitness.push.subscription']._register_device(
            user.id, 'https://push.example.invalid/sb%d' % self._seq,
            'pub', 'auth')
        tmpl = self.env['product.template'].create({
            'name': 'SB pack %d' % classes, 'list_price': 10.0 * classes,
            'type': 'service', 'fitness_is_package': True,
            'fitness_class_count': classes, 'fitness_validity_days': 60,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create(
            {'partner_id': user.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return user, order.order_line[:1]

    def _channels(self, user):
        bells = self.env['fitness.notification'].sudo().search(
            [('user_id', '=', user.id)])
        mails = self.env['mail.mail'].sudo().search_count(
            [('recipient_ids', 'in', user.partner_id.ids)])
        return bells, mails, len(self.pushed)

    def _book(self, user, line, silent):
        self.pushed.clear()
        start = PINNED + timedelta(days=1, hours=2 + self._seq)
        event = self.env['calendar.event'].sudo().create({
            'name': 'SB class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id,
            'is_fitness_class': True, 'capacity': 6})
        before = self._channels(user)
        ctx = {'skip_fitness_notification': True} if silent else {}
        self.env['fitness.booking'].sudo().with_context(**ctx).create({
            'student_id': user.partner_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': line.id})
        bells, mails, pushes = self._channels(user)
        new = bells - before[0]
        return sorted(new.mapped('notification_type')), \
            mails - before[1], pushes

    def test_silent_booking_rings_nothing_on_any_channel(self):
        for classes in (2, 1):          # leaves 1 (low) and 0 (zero)
            with self.subTest(classes=classes):
                user, line = self._student_with_pack(classes)
                types, mails, pushes = self._book(user, line, silent=True)
                self.assertEqual((types, mails, pushes), ([], 0, 0))
                self.assertEqual(line.fitness_remaining_classes,
                                 classes - 1, 'the credit was still spent')

    def test_without_the_flag_she_is_told_as_before(self):
        cases = {2: ['booking_confirmed', 'credit_low', 'credit_used'],
                 1: ['booking_confirmed', 'credit_used', 'credit_zero']}
        for classes, expected in cases.items():
            with self.subTest(classes=classes):
                user, line = self._student_with_pack(classes)
                types, mails, pushes = self._book(user, line, silent=False)
                self.assertEqual(types, expected)
                self.assertEqual(pushes, len(expected))
                self.assertEqual(mails, 1, 'the confirmation email')
