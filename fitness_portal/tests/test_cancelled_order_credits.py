# -*- coding: utf-8 -*-
"""A cancelled order stops paying for classes.

Cancelling an order does not zero the credits on its lines. Nothing did,
so a cancelled sale kept funding bookings: Nuria's duplicate 50 EUR private
was cancelled, the credit was handed back to the line on the way out, and
she was left holding one free Reformer Private that nobody had bought. It
showed in her balance, in the Credits list and at booking time.

Found on production, by the studio, looking at a student's credits screen.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCancelledOrderCredits(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.pack = cls.env["product.template"].create({
            "name": "Cancel Probe Pack", "list_price": 50.0,
            "type": "service", "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 1,
            "fitness_validity_days": 90, "fitness_class_type": "reformer",
            "fitness_session_type": "private",
        })

    def _sell(self, partner):
        order = self.env["sale.order"].sudo().create(
            {"partner_id": partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 50.0,
        })
        order.action_confirm()
        return order

    def test_a_confirmed_order_does_pay_for_classes(self):
        """The half that must keep working - without it, excluding
        cancelled orders would be satisfied by excluding everything."""
        partner = self.env["res.partner"].create({"name": "Cancel Probe A"})
        self._sell(partner)
        self.env.invalidate_all()
        self.assertEqual(
            partner._fitness_credit_total(), 1,
            "a confirmed order granted no credit")

    def test_a_cancelled_order_stops_paying(self):
        partner = self.env["res.partner"].create({"name": "Cancel Probe B"})
        order = self._sell(partner)
        self.env.invalidate_all()
        self.assertEqual(partner._fitness_credit_total(), 1)

        order._action_cancel()
        self.env.invalidate_all()

        self.assertEqual(
            partner._fitness_credit_total(), 0,
            "a cancelled order is still paying for classes - she can book "
            "something nobody bought")

    def test_the_credits_list_does_not_show_it_either(self):
        """The balance and the screen have to agree. The studio found this
        on the Credits list, not in the total."""
        partner = self.env["res.partner"].create({"name": "Cancel Probe C"})
        order = self._sell(partner)
        order._action_cancel()
        self.env.invalidate_all()

        lines = partner._fitness_active_package_lines()
        self.assertNotIn(
            order.order_line[:1], lines,
            "the cancelled order's line is still listed as a live credit")
