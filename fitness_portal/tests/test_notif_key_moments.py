# -*- coding: utf-8 -*-
"""The opt-in ask appears at the key moments, and nowhere else.

Driven over HTTP as a real non-admin student, because the ask is placed by
the template inside a success branch and read by the browser afterwards.
A model-level call would prove neither which pages carry it nor which
do not - and "nowhere else" is the half that actually constrains anything.

The ask ships hidden. These assert that the MARKUP is present, which is
what the server controls; whether it becomes visible is the browser's
decision and is covered by the headless harness.
"""
import re

from odoo.tests import HttpCase, tagged

ASK = 'id="mv-notif-booked"'
LANG_PREFIX = re.compile(r'^/(?:es|ca|en)(?:_[A-Z]{2})?(?=/)')


@tagged("post_install", "-at_install")
class TestKeyMomentAsk(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Moment Student', 'login': 'moment.student',
                'email': 'moment.student@example.invalid',
                'password': 'moment-pass-9134',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        self.env.registry.clear_cache()

    def _as_student(self, path):
        self.authenticate('moment.student', 'moment-pass-9134')
        return self.url_open(path).text

    def _logged_out(self, path):
        self.authenticate(None, None)
        return self.url_open(path).text

    # ── the moments that SHOULD carry it ─────────────────────────────────
    def test_the_booking_confirmation_carries_the_ask(self):
        body = self._as_student('/my/studio?booked=1')
        self.assertIn(ASK, body,
                      "the studio confirmation does not carry the ask")

    def test_the_free_trial_confirmation_carries_the_ask(self):
        body = self._as_student('/my/packages?booked=1')
        self.assertIn(ASK, body,
                      "the free-trial confirmation does not carry the ask")

    def test_the_cash_reservation_carries_the_ask(self):
        """'Reserved for you' - the cash landing, and the one a card payment
        returns to through the provider's landing_route."""
        for qs in ('cash_requested=1', 'cash_pending=1'):
            body = self._as_student('/my/packages?%s' % qs)
            self.assertIn(ASK, body,
                          "the %s landing does not carry the ask" % qs)

    # ── and the pages that SHOULD NOT ────────────────────────────────────
    def test_an_ordinary_visit_does_not_carry_it(self):
        """It is an addition to a confirmation, not a banner on every page."""
        for path in ('/my/studio', '/my/packages', '/my/notifications'):
            body = self._as_student(path)
            self.assertNotIn(ASK, body,
                             "%s carries the ask with nothing to confirm"
                             % path)

    def test_an_error_flash_never_carries_it(self):
        """A failure is not a moment to ask her for anything."""
        body = self._as_student('/my/studio?error=Something+went+wrong')
        self.assertNotIn(ASK, body,
                         "the ask appeared beside an error")

    def test_a_cancellation_is_not_a_key_moment(self):
        body = self._as_student('/my/studio?cancelled=1&credit_returned=1')
        self.assertNotIn(ASK, body,
                         "the ask appeared after a cancellation")

    def test_the_checkout_page_never_carries_it(self):
        prod = self.env['product.template'].sudo().search(
            [('fitness_is_package', '=', True)], limit=1)
        if not prod:
            self.skipTest("no package product on this database")
        body = self._as_student('/my/packages/%d/checkout' % prod.id)
        self.assertNotIn(ASK, body,
                         "the ask appeared mid-payment")

    # ── the public trial page ────────────────────────────────────────────
    def test_a_logged_out_visitor_never_sees_it_on_the_trial_page(self):
        """/trial is auth='public'. Asking somebody with no account to turn
        on notifications for it is meaningless, and the browser cannot tell
        a public session from a student's - so it is gated on the server."""
        body = self._logged_out('/trial')
        self.assertNotIn(ASK, body,
                         "a logged-out visitor is being shown the ask")

    # ── back from a card or Bizum payment ────────────────────────────────
    def _a_transaction(self, state):
        """One recent transaction for this student, in the given state."""
        provider = self.env['payment.provider'].sudo().search([], limit=1)
        method = (provider.payment_method_ids[:1]
                  or self.env['payment.method'].sudo().search([], limit=1))
        if not provider or not method:
            self.skipTest("no payment provider on this database")
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id,
            'payment_method_id': method.id,
            'reference': 'MOMENT-%s' % state,
            'amount': 12.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.student.partner_id.id,
        })
        tx.sudo().write({'state': state})
        return tx

    def test_a_confirmed_payment_carries_the_ask(self):
        self._a_transaction('done')
        body = self._as_student('/my/packages?from_payment=1')
        self.assertIn(ASK, body, "a paid return does not carry the ask")
        self.assertIn('Payment received', body,
                      "she is not told the payment landed")

    def test_a_pending_payment_carries_the_ask(self):
        """Bizum confirms out of band, so she is back in the shop before her
        bank has answered. This is the state where being told she will be
        notified is worth most, and it had no message at all."""
        self._a_transaction('pending')
        body = self._as_student('/my/packages?from_payment=1')
        self.assertIn(ASK, body, "a pending return does not carry the ask")
        self.assertIn('not confirmed it yet', body,
                      "she is not told the payment is still in progress")

    def test_a_failed_payment_carries_no_ask(self):
        """Not a moment to ask her for anything."""
        self._a_transaction('error')
        body = self._as_student('/my/packages?from_payment=1')
        self.assertNotIn(ASK, body, "the ask appeared after a failed payment")
        self.assertIn('did not go through', body,
                      "she is not told the payment failed")

    def test_without_the_marker_an_old_payment_changes_nothing(self):
        """An ordinary visit to the shop is not a confirmation, however
        recently she paid."""
        self._a_transaction('done')
        body = self._as_student('/my/packages')
        self.assertNotIn(ASK, body,
                         "an ordinary shop visit is showing the ask")

    # ── the fixed-slot picker, the last step of buying a fixed class ─────
    def test_choosing_a_weekly_slot_carries_the_ask(self):
        body = self._as_student('/my/subscription?slot_set=1')
        self.assertIn(ASK, body,
                      "the fixed-slot confirmation does not carry the ask")

    def test_the_subscription_page_alone_does_not(self):
        body = self._as_student('/my/subscription')
        self.assertNotIn(ASK, body,
                         "the subscription page carries the ask with nothing "
                         "to confirm")
