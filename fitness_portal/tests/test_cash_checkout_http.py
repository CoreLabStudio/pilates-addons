# -*- coding: utf-8 -*-
"""Buying with cash, over HTTP, with a card provider switched on.

The cash flow had been exercised by calling methods. What a student
actually does is open a page, tick a box and press a button, and the
interesting part of this flow is precisely what the pages do: cash has to
stay on offer even when Stripe is live, and a second request for the same
thing has to be refused everywhere it could be started from.

Stripe is enabled here on purpose. The local restore ships it disabled,
which sends checkout down the manual branch and hides the branch real
students take. With it on, the page has to choose between the card and
the desk, and "pay at the studio" must survive that choice - a student
who has decided to pay cash must not be handed a card form because a
provider happens to be configured.

What these pin:

  * the checkout page offers cash while a card provider is enabled;
  * the POST creates a real pending order that mints nothing;
  * a second attempt is refused from the shop, the product page and the
    checkout URL alike - a kept link is not a way round it;
  * after approval the credits, their expiry, and the three pages a
    student reads all agree;
  * and a booking spends the pack she bought, not something else.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestCashCheckoutOverHttp(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")

        # Stripe on. Without this the page takes the manual branch and the
        # card-versus-cash decision - the thing worth testing - never happens.
        cls.stripe = cls.env.ref("payment.payment_provider_stripe",
                                 raise_if_not_found=False)
        if cls.stripe:
            cls.stripe.sudo().write({"state": "test"})

        cls.password = "cash-http-pw-1"
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Cash Http Student",
                "login": "cash.http@example.invalid",
                "password": cls.password,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.user.partner_id
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Cash Http Manager",
                "login": "cash.http.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Cash Http Room", "classroom_type": "barre",
            "capacity": 10,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Cash Http Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.validity_days = 90
        cls.pack = cls.env["product.template"].create({
            "name": "Cash Http Pack", "type": "service", "list_price": 80.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 5,
            "fitness_validity_days": cls.validity_days,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })

    def setUp(self):
        super().setUp()
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _get(self, url, expect=200):
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, expect, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session was lost")
        return res

    def _checkout_url(self):
        return "/my/packages/%d/checkout" % self.pack.id

    def _csrf_token(self):
        """A token from the checkout form, while the form is still served."""
        import re
        page = self._get(self._checkout_url())
        tok = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        self.assertTrue(tok, "no csrf token on the checkout page")
        return tok.group(1)

    def _post_cash(self, token=None):
        """Submit the checkout form.

        The token is taken separately and may be passed back in, because
        once a request is pending the GET no longer serves the form - it
        redirects. Replaying a token captured earlier is exactly what a
        kept tab or a back button does, and it is the case worth testing:
        a stale form must not create a second order.
        """
        token = token or self._csrf_token()
        return self.url_open(self._checkout_url(), data={
            "csrf_token": token,
            "payment_method": "cash",
            "terms_accepted": "1",
        }, timeout=30)

    def _her_orders(self):
        return self.env["sale.order"].sudo().search(
            [("partner_id", "=", self.partner.id)], order="id desc")

    # ── the page ────────────────────────────────────────────────────────────

    def test_the_checkout_page_offers_cash_while_stripe_is_on(self):
        if self.stripe:
            self.assertIn(
                self.stripe.state, ("test", "enabled"),
                "fixture wrong: Stripe is not on, so this proves nothing")
        page = self._get(self._checkout_url())
        self.assertIn(
            'value="cash"', page.text,
            "the desk option vanished once a card provider was enabled - a "
            "student who wants to pay cash is handed a card form")

    def test_the_product_page_and_checkout_are_reachable_before_buying(self):
        self._get("/my/packages/%d" % self.pack.id)
        self._get(self._checkout_url())
        self._get("/my/packages")

    # ── the POST ────────────────────────────────────────────────────────────

    def test_the_post_creates_a_pending_order_that_mints_nothing(self):
        before = len(self._her_orders())
        res = self._post_cash()
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertIn(
            "cash_requested=1", res.url,
            "the student was not told her request was taken (landed on %s)"
            % res.url)

        orders = self._her_orders()
        self.assertEqual(
            len(orders), before + 1, "no order was created")
        order = orders[0]
        self.assertEqual(order.state, "draft", "the order was confirmed")
        self.assertTrue(
            order.fitness_cash_requested_on, "not marked as a cash request")
        self.assertEqual(
            order.fitness_payment_method, "cash",
            "the order did not record that she is paying at the desk")
        self.assertEqual(
            self.partner._fitness_credit_total(), 0,
            "credits were granted before anybody took the money")

    # ── the duplicate, refused from all three places ────────────────────────

    def test_a_second_request_is_refused_everywhere_it_could_start(self):
        token = self._csrf_token()
        self._post_cash(token)
        self.env.invalidate_all()
        first = len(self._her_orders())

        # (a) the checkout page itself stops serving the form
        landed = self.url_open(self._checkout_url(), timeout=30)
        self.assertIn(
            "cash_pending=1", landed.url,
            "the checkout page still offers the form while a request is "
            "pending (landed on %s)" % landed.url)

        # (b) and a form kept from before - a back button, a stale tab -
        # cannot push a second order through with a token that is still
        # perfectly valid.
        again = self._post_cash(token)
        self.assertIn(
            "cash_pending=1", again.url,
            "a replayed checkout form created a second cash request - she "
            "would owe twice for one pack (landed on %s)" % again.url)
        self.env.invalidate_all()
        self.assertEqual(
            len(self._her_orders()), first,
            "a duplicate order was created")

        # and the shop and product pages still answer without offering it
        shop = self._get("/my/packages")
        self.assertNotIn(
            'href="/my/packages/%d/checkout"' % self.pack.id, shop.text,
            "the shop still links her to a checkout she cannot use")
        self._get("/my/packages/%d" % self.pack.id)

    def test_she_can_buy_a_different_product_while_one_is_pending(self):
        """The negative: the guard is per product, not a blanket lock."""
        other = self.env["product.template"].create({
            "name": "Cash Http Other Pack", "type": "service",
            "list_price": 40.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 2, "fitness_validity_days": 30,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        self._post_cash()
        self.env.invalidate_all()
        page = self._get("/my/packages/%d/checkout" % other.id)
        self.assertIn(
            'value="cash"', page.text,
            "one pending request locked her out of every other product")

    # ── after approval ──────────────────────────────────────────────────────

    def _approve_her_request(self):
        order = self._her_orders()[0]
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        return order

    def test_credits_expiry_and_the_three_pages_all_agree(self):
        self._post_cash()
        self.env.invalidate_all()
        order = self._approve_her_request()

        self.assertEqual(
            self.partner._fitness_credit_total(), 5,
            "approval did not grant the pack's credits")

        line = order.order_line.filtered("fitness_remaining_classes")[:1]
        self.assertTrue(line, "no credit line was created")
        self.assertEqual(
            line.fitness_remaining_classes, 5,
            "the credit line holds the wrong number")
        expected_end = fields.Date.today() + timedelta(
            days=self.validity_days)
        self.assertEqual(
            line.fitness_validity_end_date, expected_end,
            "credits expire on %s, expected %s"
            % (line.fitness_validity_end_date, expected_end))
        self.assertFalse(
            line.fitness_is_expired, "brand new credits are already expired")

        # The three pages she would look at. Each must render, and the
        # credits page must actually say the number.
        self._get("/my/home")
        self._get("/my/schedule")
        credits_page = self._get("/my/credits")
        self.assertIn(
            "Cash Http Pack", credits_page.text,
            "the pack she just paid for is not on her credits page")

    def test_a_booking_spends_the_pack_she_bought(self):
        self._post_cash()
        self.env.invalidate_all()
        order = self._approve_her_request()
        line = order.order_line.filtered("fitness_remaining_classes")[:1]
        self.assertEqual(line.fitness_remaining_classes, 5, "fixture wrong")

        start = (fields.Datetime.now() + timedelta(days=2)).replace(
            hour=18, minute=0, second=0, microsecond=0)
        event = self.env["calendar.event"].sudo().create({
            "name": "Cash Http class", "start": start,
            "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True, "capacity": 10,
        })
        self.env["fitness.booking"].sudo().create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": line.id,
        })
        self.env.invalidate_all()

        self.assertEqual(
            line.fitness_remaining_classes, 4,
            "the booking did not come out of the pack she paid for")
        self.assertEqual(
            self.partner._fitness_credit_total(), 4,
            "her credit total disagrees with the pack line")
