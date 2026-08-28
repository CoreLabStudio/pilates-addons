# -*- coding: utf-8 -*-
"""The duplicate-payment guard, exercised through its real HTTP route.

Order S00177 was charged twice, two minutes apart, because Odoo's
/my/orders/<id>/transaction route checks only the access token. The guard added
in fitness_portal/controllers/payment_guard.py refuses a second payment.

The block on a 'pending' transaction is time-boxed. Bizum sits pending while the
customer authorises on their banking app, and an abandoned authorisation never
resolves, so an unbounded block would lock the order permanently. These tests
pin both halves of that behaviour: recent pending blocks, stale pending does not.

The guard raises before delegating to super(), so the response distinguishes
which path ran. That also means the request body does not need to be a valid
payment payload, which keeps the test independent of provider configuration.

Every assertion checks the HTTP status first. An earlier version of this file
did not, and reported four passes while every request was in fact 404ing on the
database filter: an absent guard message reads as "allowed" whether the guard
let the request through or the request never arrived. Assert arrival, then
assert behaviour.
"""
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

GUARD_IN_FLIGHT = "already being processed"
GUARD_ALREADY_PAID = "already been paid"


@tagged("post_install", "-at_install")
class TestDuplicatePaymentGuard(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "guard-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Guard Test Student",
            "login": "guard.student@example.invalid",
            "password": cls.password,
            # Odoo 19 renamed res.users.groups_id to group_ids.
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        cls.partner = cls.user.partner_id
        cls.product = cls.env["product.product"].create({
            "name": "Guard Test Class Pack",
            "list_price": 10.0,
            "sale_ok": True,
            "type": "service",
        })
        providers = cls.env["payment.provider"].search([])
        cls.provider = providers[:1]
        cls.method = cls.env["payment.method"].with_context(active_test=False).search([], limit=1)
        # payment.transaction refuses the 'authorized' state unless the provider
        # declares manual capture. support_manual_capture is computed and not
        # stored, so it can be neither written nor searched: pick a provider that
        # already has it, and let the one test that needs it skip if the database
        # has none. The guard treats 'authorized' and 'done' identically, and
        # 'done' is covered unconditionally, so nothing goes unverified silently.
        cls.capture_provider = next(
            (p for p in providers if p.support_manual_capture), cls.env["payment.provider"]
        )

    # ── helpers ───────────────────────────────────────────────────────────
    def _new_order(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "price_unit": 10.0,
            })],
        })

    def _add_transaction(self, order, state, minutes_old, provider=None):
        """Attach a transaction in `state`, aged `minutes_old` minutes."""
        provider = provider if provider is not None else self.provider
        if not provider or not self.method:
            self.skipTest("no payment provider or method available in this database")
        tx = self.env["payment.transaction"].create({
            "reference": "GUARD-TEST-%s-%s" % (order.id, state),
            "provider_id": provider.id,
            "payment_method_id": self.method.id,
            "partner_id": self.partner.id,
            "amount": 10.0,
            "currency_id": order.currency_id.id,
            "sale_order_ids": [(6, 0, [order.id])],
        })
        # state and timestamp are set after create so no state machine runs
        tx.write({
            "state": state,
            "last_state_change": fields.Datetime.now() - timedelta(minutes=minutes_old),
        })
        return tx

    def _attempt_payment(self, order):
        """POST the transaction route as the student.

        Returns the lowered body. Fails outright if the request did not reach
        the controller, so no test can pass because of a routing problem.
        """
        self.authenticate(self.user.login, self.password)
        response = self.url_open(
            "/my/orders/%s/transaction" % order.id,
            data=json.dumps({
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "order_id": order.id,
                    "access_token": order._portal_ensure_token(),
                },
            }),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        body = (response.text or "").lower()
        self.assertEqual(
            response.status_code, 200,
            "the request never reached the payment route (HTTP %s), so this test "
            "would prove nothing about the guard. Response:\n%s"
            % (response.status_code, body[:400]),
        )
        return body

    def _assert_blocked(self, order, msg):
        body = self._attempt_payment(order)
        self.assertTrue(
            GUARD_IN_FLIGHT in body or GUARD_ALREADY_PAID in body,
            "%s\nguard should have refused this payment. response was:\n%s" % (msg, body[:400]),
        )

    def _assert_allowed(self, order, msg):
        body = self._attempt_payment(order)
        self.assertNotIn(GUARD_IN_FLIGHT, body, msg)
        self.assertNotIn(GUARD_ALREADY_PAID, body, msg)

    # ── the payment must go through ───────────────────────────────────────
    def test_first_payment_is_allowed(self):
        """An order with no transaction is a genuine first payment."""
        self._assert_allowed(self._new_order(), "a first payment must never be blocked")

    def test_abandoned_draft_attempt_is_allowed(self):
        """A draft transaction is an abandoned attempt, not money in flight."""
        order = self._new_order()
        self._add_transaction(order, "draft", 5)
        self._assert_allowed(order, "a draft transaction must not block a retry")

    def test_stale_pending_is_allowed(self):
        """The fix: an abandoned Bizum authorisation must not lock the order.

        Without the time box this order could never be paid again.
        """
        order = self._new_order()
        self._add_transaction(order, "pending", 90)
        self._assert_allowed(order, "a pending transaction older than the grace period must not block")

    def test_cancelled_transaction_is_allowed(self):
        order = self._new_order()
        self._add_transaction(order, "cancel", 90)
        self._assert_allowed(order, "a cancelled transaction must not block a retry")

    # ── the payment must be refused ───────────────────────────────────────
    def test_recent_pending_blocks(self):
        """A payment really in flight still blocks, which is the original bug."""
        order = self._new_order()
        self._add_transaction(order, "pending", 5)
        self._assert_blocked(order, "a recent pending transaction must block")

    def test_authorized_blocks_regardless_of_age(self):
        """Authorized means money is committed; age is irrelevant."""
        if not self.capture_provider:
            self.skipTest(
                "no installed payment provider supports manual capture, so no "
                "transaction can legally hold the 'authorized' state here"
            )
        order = self._new_order()
        self._add_transaction(order, "authorized", 90, provider=self.capture_provider)
        self._assert_blocked(order, "an authorized transaction must always block")

    def test_done_blocks_regardless_of_age(self):
        order = self._new_order()
        self._add_transaction(order, "done", 90)
        self._assert_blocked(order, "a completed transaction must always block")
