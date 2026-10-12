# -*- coding: utf-8 -*-
"""A cancellation message says what happened to the credit, and only that.

Every booking_cancelled bell ended "Check your credit balance for any
refunds", including inside the cancellation window, where the credit is
kept on purpose. The email added "(cancelled more than 6 hours before the
class)" to a returned credit even when it was the studio that cancelled.

Now: kept, nothing about credit at all; returned, one short sentence; the
studio giving a late credit back tells her so. Every branch in es, ca and
en, bell and email.

Clock pinned, window read from the setting, language explicit.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
LANGS = ('en_US', 'es_ES', 'ca_ES')

CANCELLED = {
    'en_US': 'has been cancelled.',
    'es_ES': 'ha sido cancelada.',
    'ca_ES': "s'ha cancel·lat.",
}
RETURNED = {
    'en_US': 'Your credit has been returned.',
    'es_ES': 'Tu crédito ha sido devuelto.',
    'ca_ES': "El teu crèdit s'ha retornat.",
}
GIVEN_BACK = {
    'en_US': 'The studio has returned your credit for',
    'es_ES': 'El estudio te ha devuelto el crédito de',
    'ca_ES': "L'estudi t'ha retornat el crèdit de",
}
# Nothing about money may survive a late cancellation, in any language.
CREDIT_WORDS = ('credit', 'crédit', 'crèdit', 'refund', 'reembols',
                'saldo', 'devuelto', 'retornat', 'returned')


@tagged('post_install', '-at_install')
class TestCancelSaysWhatHappened(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.cancellation_window_hours', '6')
        ICP.set_param('fitness_notifications.send_cancellation', 'True')
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'CW Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group',
        })
        self.pack = self.env['product.template'].create({
            'name': 'CW pack 5', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
        })
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CW Manager', 'login': 'cw.manager@example.invalid',
                'lang': 'es_ES',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id,
                ])],
            })
        self._seq = 0

    def _student(self, lang):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CW Student %d' % self._seq,
                'login': 'cw.%d@example.invalid' % self._seq,
                'email': 'cw.%d@example.invalid' % self._seq,
                'lang': lang, 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            })

    def _booking(self, user, hours_ahead):
        order = self.env['sale.order'].sudo().create({
            'partner_id': user.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            'fitness_class_type': 'reformer',
        })
        order.action_confirm()
        start = PINNED + timedelta(hours=hours_ahead)
        event = self.env['calendar.event'].create({
            'name': 'CW Class %d' % self._seq, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
            'capacity': 6,
        })
        return self.env['fitness.booking'].sudo().create({
            'student_id': user.partner_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': order.order_line[:1].id,
        })

    def _bells(self, user):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'booking_cancelled'),
        ], order='id')

    def _email_text(self, booking):
        mail = self.env['mail.mail'].sudo().search([
            ('model', '=', 'fitness.booking'), ('res_id', '=', booking.id),
        ], order='id desc', limit=1)
        self.assertTrue(mail, 'a cancellation email must be queued')
        return mail.body_html or ''

    def _assert_says_nothing_about_credit(self, text, label):
        low = text.lower()
        for word in CREDIT_WORDS:
            self.assertNotIn(word, low,
                             '%s mentions %r: %s' % (label, word, text))

    # -- late cancel: nothing about credit --------------------------------
    def test_late_cancel_says_only_that_it_was_cancelled(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang)
                booking = self._booking(user, hours_ahead=3)
                booking.with_user(user).action_cancel()
                self.assertFalse(booking.credit_returned)
                bell = self._bells(user)
                self.assertEqual(len(bell), 1)
                self.assertIn(CANCELLED[lang], bell.body)
                self._assert_says_nothing_about_credit(
                    bell.body, 'late bell %s' % lang)
                self._assert_says_nothing_about_credit(
                    self._email_text(booking), 'late email %s' % lang)

    # -- cancel in good time: one sentence that it came back ---------------
    def test_early_cancel_says_the_credit_came_back(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang)
                booking = self._booking(user, hours_ahead=30)
                booking.with_user(user).action_cancel()
                self.assertTrue(booking.credit_returned)
                bell = self._bells(user)
                self.assertIn(CANCELLED[lang], bell.body)
                self.assertTrue(bell.body.endswith(RETURNED[lang]),
                                'early bell %s: %s' % (lang, bell.body))
                email = self._email_text(booking)
                self.assertIn(RETURNED[lang], email)
                self.assertNotIn('6 ', email.split(RETURNED[lang])[1][:40])

    # -- the studio cancels the class --------------------------------------
    def test_studio_cancellation_email_is_true(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang)
                # Inside the window: "more than 6 hours before" would be
                # false, and was what the email used to say.
                booking = self._booking(user, hours_ahead=2)
                booking.calendar_event_id.with_user(
                    self.manager).action_cancel_class()
                self.assertTrue(booking.credit_returned)
                email = self._email_text(booking)
                self.assertIn(RETURNED[lang], email)
                for wrong in ('6 hours', '6 horas', '6 hores'):
                    self.assertNotIn(wrong, email)

    # -- the studio returns it inside the window ---------------------------
    def test_forced_refund_inside_the_window_says_it_came_back(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang)
                booking = self._booking(user, hours_ahead=3)
                wiz = self.env['fitness.booking.cancel.wizard'].with_user(
                    self.manager).create({'booking_id': booking.id,
                                          'restore_credit': True})
                wiz.action_confirm()
                self.assertTrue(booking.credit_returned)
                self.assertTrue(self._bells(user).body.endswith(
                    RETURNED[lang]))
                self.assertIn(RETURNED[lang], self._email_text(booking))

    # -- Give the Credit Back after a late cancel --------------------------
    def test_give_back_tells_her(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang)
                booking = self._booking(user, hours_ahead=3)
                booking.with_user(user).action_cancel()
                booking.with_user(self.manager)._give_credit_back(
                    'Ill, rang in the morning')
                bells = self._bells(user)
                self.assertEqual(len(bells), 2)
                self.assertIn(GIVEN_BACK[lang], bells[-1].body)

    def test_give_back_is_silent_when_asked(self):
        user = self._student('es_ES')
        booking = self._booking(user, hours_ahead=3)
        booking.with_user(user).action_cancel()
        booking.with_user(self.manager).with_context(
            skip_fitness_notification=True)._give_credit_back('Silent')
        self.assertEqual(len(self._bells(user)), 1)
