# -*- coding: utf-8 -*-
"""Paying for a subscription has to save the card.

A membership is charged again next period, so the card must be tokenised.
Odoo works that out in sale_subscription._is_tokenization_required(), which
keys entirely off the sale_order_id handed to _get_compatible_providers().

Our pay page did not pass it. Odoo therefore treated a quarterly membership
as an ordinary one-off: the transaction was built with tokenize=False, the
Stripe intent carried no setup_future_usage, and the card element - which
does know a recurring plan needs saving - confirmed with off_session. Stripe
rejected the mismatch and the member simply could not pay:

    The provided setup_future_usage (off_session) does not match the
    expected setup_future_usage (null).

She tried three times on a Mastercard before anyone knew. Packs were never
affected, because a one-off has nothing to save - which is exactly why this
survived every earlier checkout test.

These assert the requirement rather than the plumbing: tokenization is
required for a subscription order and not for a pack. That holds whichever
way Odoo decides to pass the flag around internally.
"""
import re

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSubscriptionPaymentTokenization(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Tokenize Test Member"})
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")

        cls.membership = cls.env["product.template"].create({
            "name": "Membership (tokenize test)",
            "type": "service", "list_price": 95.0, "sale_ok": True,
            "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_class_type": "reformer",
            "weekly_class_allowance": 2,
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Pack (tokenize test)",
            "type": "service", "list_price": 120.0, "sale_ok": True,
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
            "fitness_class_count": 5,
        })

    def _order(self, product, subscription):
        vals = {
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1})],
        }
        if subscription:
            vals["plan_id"] = self.plan.id
        return self.env["sale.order"].create(vals)

    def test_a_subscription_requires_the_card_to_be_saved(self):
        """Without this the member cannot pay at all - Stripe refuses."""
        order = self._order(self.membership, subscription=True)
        self.assertTrue(order.is_subscription,
                        "the fixture is not a subscription, so this proves nothing")
        self.assertTrue(
            self.env["payment.provider"]._is_tokenization_required(
                sale_order_id=order.id),
            "a subscription did not require tokenisation - the Stripe intent "
            "would be built without setup_future_usage and the payment refused")

    def test_a_pack_does_not_require_it(self):
        """The other half: a one-off must not be forced to store a card."""
        order = self._order(self.pack, subscription=False)
        self.assertFalse(order.is_subscription)
        self.assertFalse(
            self.env["payment.provider"]._is_tokenization_required(
                sale_order_id=order.id),
            "a one-off pack was forced to tokenise")

    def test_the_pay_page_tells_odoo_which_order_it_is_paying(self):
        """The regression itself: the page must pass sale_order_id through.

        This reads the controller's source, which is a blunt way to test and
        worth being honest about. The two tests above pin Odoo's rule, but
        they would both still pass with the bug present - they ask Odoo
        directly, while the bug was that our page never asked. Short of
        standing up a real Stripe provider and a card, the argument actually
        reaching Odoo is the thing to pin, because its absence was invisible:
        the page rendered perfectly and the refusal only arrived from Stripe
        after the member had typed her card in, three times.
        """
        import inspect
        from odoo.addons.fitness_portal.controllers import portal

        source = inspect.getsource(portal.FitnessPackagePayment.packages_stripe_pay)
        self.assertIn("sale_order_id=order_sudo.id", source,
                      "the pay page no longer tells Odoo which order it is "
                      "paying for; subscriptions will be refused by Stripe")
        self.assertGreaterEqual(
            source.count("sale_order_id=order_sudo.id"), 2,
            "sale_order_id must reach both the provider and the payment-method "
            "lookup, or the form and the transaction disagree")


@tagged("post_install", "-at_install")
class TestQuarterlyDoubleSubmit(HttpCase):
    """Tapping Next twice must not turn three months into one.

    The checkout reuses an abandoned draft rather than leaving a new one
    behind on every attempt, which is the ordinary path - "Next, back, Next"
    is what people do. On that path the order was written with its plan and
    its lines in a single call, and plan_id is a dependency of the line's
    price_unit compute: changing it re-triggered the compute after our own
    figure had landed and restored the product's one-month price. The order
    kept the three-month plan and a third of the money.

    A real member's order sat on production in exactly that state - the
    quarterly plan at one month's price, which would have billed her every
    three months for one month's worth, indefinitely.

    Nothing caught it because every earlier test submitted once. A new order
    writes plan and lines together at create, where an explicit price_unit is
    honoured, so the first submit was always right. This drives the real URL
    twice, because the second submit is the whole bug.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.quarter = cls.env.ref(
            "fitness_subscriptions.subscription_plan_quarter",
            raise_if_not_found=False)
        cls.monthly = cls.env.ref("sale_subscription.subscription_plan_month")

        cls.student = cls.env["res.users"].create({
            "name": "Double Submit Member",
            "login": "double.submit@example.invalid",
            "password": "double-submit-pw-1",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        # 195.00 a month, so three months is 585.00 - the numbers the live
        # order collapsed between.
        cls.membership = cls.env["product.template"].create({
            "name": "Reformer membership (double-submit test)",
            "type": "service", "list_price": 195.0, "sale_ok": True,
            "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.monthly.id,
            "fitness_class_type": "reformer",
            "weekly_class_allowance": 2,
            # No tax, so the assertion is about the multiplier and not about
            # whichever default tax the database happens to carry.
            "taxes_id": [(5, 0, 0)],
        })

    def _submit_quarterly(self):
        """One trip through the checkout, exactly as the browser makes it."""
        url = "/my/packages/%d/checkout" % self.membership.id
        page = self.url_open("%s?plan_id=%d" % (url, self.quarter.id))
        self.assertEqual(page.status_code, 200, "the checkout did not render")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertTrue(token, "no csrf token on the checkout page")
        # payment_method is sent alongside terms so this holds whether or not
        # the database has an online provider enabled - both branches end in
        # _create_order, which is what is under test.
        return self.url_open(url, data={
            "csrf_token": token.group(1),
            "plan_id": self.quarter.id,
            "terms_accepted": "1",
            "payment_method": "transfer",
        })

    def _draft(self):
        order = self.env["sale.order"].sudo().search([
            ("partner_id", "=", self.student.partner_id.id),
            ("state", "=", "draft")], order="id desc", limit=1)
        self.assertTrue(order, "the checkout created no order at all")
        return order

    def test_the_second_submit_keeps_all_three_months(self):
        if not self.quarter:
            self.skipTest("no quarterly plan in this database")
        self.authenticate("double.submit@example.invalid", "double-submit-pw-1")

        self._submit_quarterly()
        first = self._draft()
        self.assertEqual(
            first.plan_id, self.quarter,
            "the first submit did not put the order on the quarterly plan")
        self.assertAlmostEqual(
            first.order_line[0].price_unit, 585.0, 2,
            "the first submit already mispriced three months at 195.00/month")

        self._submit_quarterly()
        second = self._draft()
        self.assertEqual(second, first,
                         "the second submit made a new order instead of "
                         "reusing the draft; this no longer tests the bug")
        self.assertEqual(
            second.plan_id, self.quarter,
            "the reused draft lost the quarterly plan")
        self.assertAlmostEqual(
            second.order_line[0].price_unit, 585.0, 2,
            "tapping Next twice threw away the months multiplier: the order "
            "still bills every three months but charges for one, which is "
            "what happened to a real member's order on production")

    def test_a_third_submit_is_still_right(self):
        """Not redundant: the collapse compounded, so prove it settles."""
        if not self.quarter:
            self.skipTest("no quarterly plan in this database")
        self.authenticate("double.submit@example.invalid", "double-submit-pw-1")
        for attempt in range(3):
            self._submit_quarterly()
            order = self._draft()
            self.assertAlmostEqual(
                order.order_line[0].price_unit, 585.0, 2,
                "submit %d priced three months at %.2f"
                % (attempt + 1, order.order_line[0].price_unit))

    def test_switching_back_to_monthly_reprices_down(self):
        """The guard must not freeze the price - a real plan change still moves.

        Writing the plan before the lines is the fix; pinning the price would
        have been the wrong one, and this is what tells the two apart.
        """
        if not self.quarter:
            self.skipTest("no quarterly plan in this database")
        self.authenticate("double.submit@example.invalid", "double-submit-pw-1")
        self._submit_quarterly()
        self.assertAlmostEqual(self._draft().order_line[0].price_unit, 585.0, 2)

        url = "/my/packages/%d/checkout" % self.membership.id
        page = self.url_open("%s?plan_id=%d" % (url, self.monthly.id))
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.url_open(url, data={
            "csrf_token": token.group(1),
            "plan_id": self.monthly.id,
            "terms_accepted": "1",
            "payment_method": "transfer",
        })
        order = self._draft()
        self.assertEqual(order.plan_id, self.monthly,
                         "switching back to monthly did not take")
        self.assertAlmostEqual(
            order.order_line[0].price_unit, 195.0, 2,
            "a genuine switch to monthly kept the quarterly price - the fix "
            "has frozen the price instead of ordering the writes")
