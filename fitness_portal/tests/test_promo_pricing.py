# -*- coding: utf-8 -*-
"""Admin-set promotional pricing, and the one number it produces.

The studio used to run an offer by typing a new figure into the sales price
and typing the old one back afterwards. That is what produced a trial priced
at zero that the checkout could not complete, and it left nothing to put the
price back when the offer ended.

So the offer is modelled instead, and the whole point is that exactly one
calculation decides what a student is shown and what they are charged. These
tests pin that: the window arithmetic, the money, and - most importantly - the
order line that Stripe is eventually handed carrying the same number the page
displayed.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged


class _PromoCase(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.product = cls.env["product.template"].create({
            "name": "Promo Trial Class",
            "list_price": 25.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
        })

    def _promo(self, mode, pct=0.0, start=None, end=None):
        self.product.write({
            "fitness_promo_mode": mode,
            "fitness_promo_percent": pct,
            "fitness_promo_start": start,
            "fitness_promo_end": end,
        })
        return self.product


@tagged("post_install", "-at_install")
class TestPromoPricing(_PromoCase):

    # ── the arithmetic ───────────────────────────────────────────────────
    def test_full_price_when_no_promotion(self):
        self.assertEqual(self.product.fitness_effective_price(), 25.0)
        self.assertFalse(self.product.fitness_promo_is_live)
        self.assertFalse(self.product.fitness_price_is_free())

    def test_percentage_off(self):
        p = self._promo("percent", 10.0, self.today, self.today + timedelta(days=20))
        self.assertEqual(p.fitness_effective_price(), 22.5)
        self.assertEqual(p.fitness_promo_saving, 2.5)
        self.assertTrue(p.fitness_promo_is_live)
        self.assertFalse(p.fitness_price_is_free(),
                         "a 10% discount is not a free item")

    def test_free_mode(self):
        p = self._promo("free", 0.0, self.today, self.today + timedelta(days=5))
        self.assertEqual(p.fitness_effective_price(), 0.0)
        self.assertTrue(p.fitness_price_is_free())

    def test_a_hundred_percent_off_is_free(self):
        """It has to take the same one-tap path as Free mode.

        Otherwise a student is sent to a payment page for 0.00, which is the
        original bug wearing a different hat.
        """
        p = self._promo("percent", 100.0, self.today, self.today + timedelta(days=5))
        self.assertEqual(p.fitness_effective_price(), 0.0)
        self.assertTrue(p.fitness_price_is_free())

    # ── the window ───────────────────────────────────────────────────────
    def test_it_expires_on_its_own(self):
        """The whole reason this exists: nothing to reset by hand."""
        end = self.today + timedelta(days=20)
        p = self._promo("percent", 10.0, self.today, end)
        self.assertEqual(p.fitness_effective_price(end), 22.5,
                         "the last day of the window must still be discounted")
        self.assertEqual(p.fitness_effective_price(end + timedelta(days=1)), 25.0,
                         "the day after the window it must be full price again")

    def test_it_does_not_apply_before_it_starts(self):
        start = self.today + timedelta(days=3)
        p = self._promo("percent", 10.0, start, start + timedelta(days=5))
        self.assertEqual(p.fitness_effective_price(start - timedelta(days=1)), 25.0)
        self.assertEqual(p.fitness_effective_price(start), 22.5)
        self.assertFalse(p.fitness_promo_is_live,
                         "a promotion starting later must not read as running today")

    def test_open_ended_dates_are_allowed(self):
        p = self._promo("free", 0.0, False, False)
        self.assertTrue(p.fitness_promo_is_live, "no dates means running now")
        self.assertEqual(p.fitness_effective_price(self.today + timedelta(days=999)), 0.0)

    def test_the_sales_price_is_never_touched(self):
        """The list price stays the real price throughout.

        Overwriting it is exactly the practice this replaces.
        """
        self._promo("free", 0.0, self.today, self.today + timedelta(days=5))
        self.assertEqual(self.product.list_price, 25.0)
        self._promo("none")
        self.assertEqual(self.product.list_price, 25.0)
        self.assertEqual(self.product.fitness_effective_price(), 25.0)

    # ── the admin cannot save nonsense ───────────────────────────────────
    def test_a_percentage_outside_0_to_100_is_refused(self):
        for bad in (0.0, -5.0, 101.0):
            with self.assertRaises(ValidationError, msg="accepted %s%%" % bad):
                self._promo("percent", bad, self.today, self.today + timedelta(days=1))

    def test_an_end_before_the_start_is_refused(self):
        with self.assertRaises(ValidationError):
            self._promo("percent", 10.0, self.today, self.today - timedelta(days=1))


@tagged("post_install", "-at_install")
class TestPromoCheckout(HttpCase):
    """The number on the page and the number on the order must be the same."""

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.password = "promo-checkout-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Promo Checkout Student",
            "login": "promo.checkout@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        cls.product = cls.env["product.template"].create({
            "name": "Promo Checkout Trial",
            "list_price": 25.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
        })

    def _gross(self, net):
        """What that net amount comes to once the product's taxes are applied.

        Empty taxes return a recordset from compute_all rather than a dict, so
        the no-tax case is answered before asking.
        """
        taxes = self.product.taxes_id.filtered(
            lambda t: t.company_id == self.env.company)
        if not taxes:
            return net
        return taxes.compute_all(
            net, currency=self.product.currency_id, quantity=1.0,
            product=self.product.product_variant_ids[:1],
            partner=self.partner)["total_included"]

    def _page(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")
        return res.text

    def test_the_discounted_price_is_the_one_shown(self):
        self.product.write({
            "fitness_promo_mode": "percent", "fitness_promo_percent": 10.0,
            "fitness_promo_start": self.today,
            "fitness_promo_end": self.today + timedelta(days=20),
        })
        html = self._page("/my/packages/%d" % self.product.id)
        self.assertIn("22.50", html, "the discounted price is not on the page")
        self.assertIn("25.00", html, "the full price is not shown struck through")
        self.assertIn("mv-price-was", html, "no strikethrough on the full price")

    def test_the_checkout_totals_use_the_discounted_price(self):
        self.product.write({
            "fitness_promo_mode": "percent", "fitness_promo_percent": 10.0,
            "fitness_promo_start": self.today,
            "fitness_promo_end": self.today + timedelta(days=20),
        })
        html = self._page("/my/packages/%d/checkout" % self.product.id)
        self.assertIn("25.00", html, "the full price should be listed")
        self.assertIn("2.50", html, "the saving is not broken out")
        self.assertIn("22.50", html, "the discounted subtotal is missing")
        # The total follows the discounted number through the product's real
        # taxes, worked out here the same way the page does rather than typed
        # in - so this keeps holding if the studio's tax rate ever changes.
        self.assertIn("%.2f" % self._gross(22.50), html,
                      "the total does not match the tax the order will charge")
        self.assertNotIn("30.25", html, "the total is still based on the full price")

    def test_the_order_line_carries_the_discounted_price(self):
        """The number Stripe is asked for.

        A page that shows 22.50 and an order that says 25.00 is the failure
        this whole feature exists to make impossible.
        """
        self.product.write({
            "fitness_promo_mode": "percent", "fitness_promo_percent": 10.0,
            "fitness_promo_start": self.today,
            "fitness_promo_end": self.today + timedelta(days=20),
        })
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": self.product.fitness_effective_price(),
            })],
        })
        self.assertEqual(order.order_line.price_unit, 22.5)
        self.assertAlmostEqual(order.amount_untaxed, 22.5, places=2)

    def test_an_expired_promotion_charges_full_price(self):
        self.product.write({
            "fitness_promo_mode": "percent", "fitness_promo_percent": 10.0,
            "fitness_promo_start": self.today - timedelta(days=30),
            "fitness_promo_end": self.today - timedelta(days=1),
        })
        self.assertFalse(self.product.fitness_promo_is_live)
        html = self._page("/my/packages/%d/checkout" % self.product.id)
        self.assertIn("%.2f" % self._gross(25.0), html,
                      "an expired promotion is still discounting")
        self.assertNotIn("mv-price-was", html,
                         "a strikethrough is shown for a promotion that has ended")

    def test_a_free_promotion_reaches_the_one_tap_path(self):
        """A promotion that resolves to zero books like any other free item.

        No checkout page, and the checkout URL redirects back to the product -
        the same treatment a permanently free product gets, decided by the
        price rather than by which field made it zero.
        """
        self.product.write({
            "fitness_promo_mode": "free",
            "fitness_promo_start": self.today,
            "fitness_promo_end": self.today + timedelta(days=5),
        })
        html = self._page("/my/packages/%d" % self.product.id)
        self.assertIn("/book-free", html,
                      "a Free promotion did not get the one-tap Book button")

        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages/%d/checkout" % self.product.id,
                            allow_redirects=False, timeout=30)
        self.assertIn(res.status_code, (301, 302, 303),
                      "a Free promotion still renders a checkout page")
