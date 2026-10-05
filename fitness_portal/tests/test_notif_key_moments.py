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
