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
from odoo import fields
from odoo.tests import TransactionCase, tagged


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
