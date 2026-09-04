# -*- coding: utf-8 -*-
"""A trial that costs nothing, and the once-per-student rule on it.

Setting a trial to EUR 0 still routed the student to Stripe, which cannot
authorise a zero-amount charge: the payment page could not be completed, so the
booking could never be made. The fix takes the payment step out of the way when
the total really is zero and confirms the order there and then.

That opens an obvious hole - an order confirmed with no payment - so both
halves are tested here together:

  * the free path is chosen on the order's own server-side total, never on
    anything the student can send, and
  * the trial can be claimed once per student, re-checked at the signature
    route because a draft abandoned beforehand is still reachable there.

The paid path is asserted too. A change that makes free items work by making
everything free is the failure this file exists to catch.
"""
import re

from odoo.tests import HttpCase, tagged

ALREADY_USED = "already used this free trial"
CSRF = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')


@tagged("post_install", "-at_install")
class TestFreeCheckout(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "free-checkout-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Free Checkout Student",
            "login": "free.checkout@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id

        def package(name, price):
            return cls.env["product.template"].create({
                "name": name,
                "list_price": price,
                "sale_ok": True,
                "type": "service",
                "fitness_is_package": True,
                "fitness_class_type": "reformer",
            })

        cls.free_product = package("Free Trial Class", 0.0)
        cls.paid_product = package("Paid Class Pack", 45.0)

    # ── helpers ──────────────────────────────────────────────────────────
    def _token(self, page_url=None):
        """A CSRF token for the current session.

        Odoo 19 has no ir.http._get_csrf_token, so it is scraped from a page.
        The token belongs to the session rather than to one form, and the
        default page is the paid checkout precisely because it always renders a
        form: several of the tests below post to routes whose page correctly
        shows no form at all in the state being tested - a refused second free
        trial has nothing to submit - and taking the token from there would
        fail the test on the very behaviour it is asserting.
        """
        page_url = page_url or ("/my/packages/%d/checkout" % self.paid_product.id)
        res = self.url_open(page_url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        match = CSRF.search(res.text)
        self.assertTrue(match, "no csrf token on %s - is the form rendered?" % page_url)
        return match.group(1)

    def _post(self, url, **extra):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        data = {"csrf_token": self._token()}
        data.update(extra)
        return self.url_open(url, data=data, timeout=30)

    def _checkout(self, product, terms=True):
        """POST the checkout step exactly as the page's own form does."""
        extra = {"terms_accepted": "1"} if terms else {}
        return self._post("/my/packages/%d/checkout" % product.id, **extra)

    def _book_free(self, product, back="/my/packages"):
        """Tap Book. There is no page in between any more."""
        return self._post("/my/packages/%d/book-free" % product.id, back=back)

    def _page_text(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        return res.text

    def _orders(self, product, states=("sale", "done")):
        return self.env["sale.order"].search([
            ("partner_id", "=", self.partner.id),
            ("state", "in", list(states)),
            ("order_line.product_id", "in", product.product_variant_ids.ids),
        ])

    def _draft_for(self, product, method=None):
        vals = {
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": product.list_price,
            })],
        }
        if method:
            vals["fitness_payment_method"] = method
        return self.env["sale.order"].create(vals)

    # ── the fix ──────────────────────────────────────────────────────────
    def test_a_free_trial_completes_without_any_payment(self):
        res = self._book_free(self.free_product)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")

        order = self._orders(self.free_product)
        self.assertEqual(len(order), 1, "the free order was not confirmed")
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.fitness_payment_method, "free")
        self.assertFalse(order.transaction_ids,
                         "a payment transaction was created for a free order")
        self.assertEqual(order.amount_total, 0.0)
        self.assertTrue(order.fitness_terms_accepted_on,
                        "consent stopped being recorded when the page went away")

    def test_a_free_item_has_no_checkout_page_at_all(self):
        """Not merely unlinked. Reaching it by URL goes back to the product.

        Leaving the page renderable would have left two ways to book the same
        thing, one of them the screen this was meant to remove.
        """
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages/%d/checkout" % self.free_product.id,
                            allow_redirects=False, timeout=30)
        self.assertIn(res.status_code, (301, 302, 303),
                      "the free checkout page still renders")
        self.assertIn("/my/packages/%d" % self.free_product.id,
                      res.headers.get("Location", ""))

    def test_the_listing_offers_book_not_buy_for_a_free_item(self):
        html = self._page_text("/my/packages?tab=classes")
        self.assertIn("/book-free", html,
                      "the free item still points at a checkout page")

    def test_the_free_detail_page_books_directly(self):
        html = self._page_text("/my/packages/%d" % self.free_product.id)
        self.assertIn("/book-free", html)
        self.assertNotIn("/my/packages/%d/checkout" % self.free_product.id, html,
                         "the free item still offers the checkout page")
        self.assertIn("Terms", html,
                      "consent is no longer stated anywhere on a free booking")

    def test_a_paid_pack_still_goes_through_payment(self):
        """The free path must not swallow everything else."""
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages/%d/checkout" % self.paid_product.id)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("No payment is needed", res.text)
        self.assertFalse(self._orders(self.paid_product),
                         "a paid pack was confirmed without payment")

    def test_consent_is_recorded_even_without_a_tickbox(self):
        """The page that carried the checkbox is gone.

        Booking is the act of agreement now, and the page says so next to the
        button - but the order still has to carry the timestamp, or the studio
        has no record that terms were accepted at all.
        """
        self._book_free(self.free_product)
        order = self._orders(self.free_product)
        self.assertEqual(len(order), 1)
        self.assertTrue(order.fitness_terms_accepted_on)
        self.assertTrue(order.signed_on)

    def test_posting_book_free_at_a_paid_product_does_not_book_it(self):
        """The price is read from the product, never taken from the request."""
        res = self._book_free(self.paid_product)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self._orders(self.paid_product),
                         "a 45 EUR pack was booked through the free route")

    # ── once per student ─────────────────────────────────────────────────
    def test_the_second_attempt_is_refused(self):
        self._book_free(self.free_product)
        self.assertEqual(len(self._orders(self.free_product)), 1)

        res = self._book_free(self.free_product)
        self.assertEqual(res.status_code, 200)
        self.assertIn(ALREADY_USED, res.text, "the second attempt was not refused")
        self.assertEqual(len(self._orders(self.free_product)), 1,
                         "a second free order was confirmed")

    def test_another_student_is_unaffected(self):
        """The rule is per student, not per product."""
        self._book_free(self.free_product)
        other = self.env["res.users"].create({
            "name": "Second Free Student",
            "login": "free.checkout.2@example.invalid",
            "password": "free-checkout-pw-2",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        self.env.flush_all()
        self.authenticate(other.login, "free-checkout-pw-2")
        url = "/my/packages/%d/book-free" % self.free_product.id
        res = self.url_open(
            url, data={"csrf_token": self._token(), "back": "/my/packages"},
            timeout=30)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(ALREADY_USED, res.text)
        confirmed = self.env["sale.order"].search([
            ("partner_id", "=", other.partner_id.id), ("state", "=", "sale")])
        self.assertTrue(confirmed, "a different student was refused the free trial")

    def test_an_abandoned_draft_does_not_burn_the_trial(self):
        """A draft is an attempt, not a claim.

        The checkout reuses drafts, so counting one as proof the trial had been
        taken would let a single abandoned checkout block that student's first
        free trial for ever.
        """
        self._draft_for(self.free_product)
        res = self._book_free(self.free_product)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(ALREADY_USED, res.text,
                         "an abandoned draft blocked the first free trial")
        self.assertEqual(len(self._orders(self.free_product)), 1)

    def test_a_cancelled_free_order_does_not_count(self):
        self._book_free(self.free_product)
        self._orders(self.free_product).with_context(
            disable_cancel_warning=True)._action_cancel()
        self.env.flush_all()
        res = self._book_free(self.free_product)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(ALREADY_USED, res.text,
                         "a cancelled free order still counted as claimed")

    def test_the_signature_route_also_enforces_the_rule(self):
        """The hole the checkout guard alone would leave.

        A draft abandoned before the trial was claimed stays reachable at the
        signature step afterwards, and confirming it there would hand out a
        second free trial.
        """
        # Two, not one. The checkout reuses a matching draft, so with a single
        # abandoned order there is nothing left over afterwards - it becomes
        # the claim. It takes a second draft for one to survive the claim and
        # still be reachable at the signature step, which is the real hole.
        stale = self._draft_for(self.free_product, method="free")
        self._draft_for(self.free_product, method="free")
        self._book_free(self.free_product)             # claims it properly
        self.assertEqual(len(self._orders(self.free_product)), 1)
        stale.invalidate_recordset()
        self.assertEqual(stale.state, "draft",
                         "fixture wrong: the draft under test was the one claimed")

        res = self._post("/my/checkout/%d/complete" % stale.id,
                         signature="aGVsbG8=", signed_by="Free Checkout Student")
        self.assertEqual(res.status_code, 200)
        stale.invalidate_recordset()
        self.assertEqual(stale.state, "draft",
                         "a second free trial was confirmed through the signature route")
        self.assertEqual(len(self._orders(self.free_product)), 1)

    def test_a_paid_order_cannot_ride_the_free_path(self):
        """The branch is chosen on the order's own total, not on its method."""
        order = self._draft_for(self.paid_product, method="free")
        res = self._post("/my/checkout/%d/complete" % order.id,
                         signature="aGVsbG8=", signed_by="Free Checkout Student")
        self.assertEqual(res.status_code, 200)
        order.invalidate_recordset()
        self.assertEqual(order.state, "draft",
                         "a 45 EUR order was confirmed with no payment")
