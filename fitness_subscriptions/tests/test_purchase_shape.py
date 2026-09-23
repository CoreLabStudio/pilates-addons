# -*- coding: utf-8 -*-
"""What a membership purchase is made of: months, and the matrícula.

These rules decide what a student is charged, and they had no tests at all -
grep the suite for "matricula" and nothing comes back. They were controller
methods reachable only from a web request, so the desk wizard could not call
them and sold a pack without them; harmless while it sold only packs, wrong
the moment it sells a membership, because a Trimestral would be charged one
month of a three-month commitment.

Pinned here on the model they now live on, before anything is built on top.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseShape(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.P = cls.env["product.template"]
        cls.month = cls.env.ref("sale_subscription.subscription_plan_month",
                                raise_if_not_found=False)
        cls.quarter = cls.env.ref("fitness_subscriptions.subscription_plan_quarter",
                                  raise_if_not_found=False)
        cls.matricula = cls.env.ref("fitness_subscriptions.product_matricula",
                                    raise_if_not_found=False)
        cls.student = cls.env["res.users"].create({
            "name": "Shape Student",
            "login": "shape.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        cls.partner = cls.student.partner_id
        cls.membership = cls.env["product.template"].create({
            "name": "Shape membership",
            "list_price": 95.0,
            "type": "service",
            "fitness_is_subscription_plan": True,
            "recurring_invoice": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })

    # -- the fixtures these rules need, asserted rather than assumed --------

    def test_the_plans_and_the_fee_exist(self):
        """Every assertion below is meaningless without these."""
        self.assertTrue(self.month, "no monthly plan")
        self.assertTrue(self.quarter, "no quarterly plan")
        self.assertTrue(self.matricula, "no matricula product")

    # -- months ------------------------------------------------------------

    def test_a_month_is_one_month_and_a_quarter_is_three(self):
        self.assertEqual(self.P.fitness_plan_months(self.month), 1)
        self.assertEqual(self.P.fitness_plan_months(self.quarter), 3)

    def test_no_plan_is_one_month(self):
        """A pack has no plan and must not be multiplied by nothing."""
        self.assertEqual(self.P.fitness_plan_months(None), 1)

    # -- the matricula -----------------------------------------------------

    def test_a_first_monthly_membership_is_charged_the_fee(self):
        due = self.membership.fitness_matricula_due(self.partner, self.month)
        self.assertEqual(due, self.matricula,
                         "a new member on a monthly plan should owe the fee")

    def test_committing_to_three_months_waives_it(self):
        due = self.membership.fitness_matricula_due(self.partner, self.quarter)
        self.assertFalse(due, "a quarterly commitment waives the fee")

    def test_a_second_membership_is_not_charged_it_again(self):
        self._give_a_past_membership()
        due = self.membership.fitness_matricula_due(self.partner, self.month)
        self.assertFalse(due, "the fee is charged once, on the first membership")

    def test_a_pack_never_owes_it(self):
        pack = self.env["product.template"].create({
            "name": "Shape pack", "list_price": 75.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 5,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        self.assertFalse(pack.fitness_matricula_due(self.partner, self.month))

    # -- the lines that follow ---------------------------------------------

    def test_a_quarter_is_charged_for_three_months(self):
        """The fault this guards is on record: a quarterly membership at
        585.00 billed as 195.00, every three months, for as long as it ran."""
        lines = self.membership.fitness_order_line_vals(
            self.partner, plan=self.quarter, period_price=95.0)
        pack_lines = [l for l in lines
                      if l["product_id"] in self.membership.product_variant_ids.ids]
        self.assertTrue(pack_lines, "no line for the membership itself")
        self.assertAlmostEqual(
            pack_lines[0]["price_unit"], 285.0, places=2,
            msg="a quarterly membership is three months charged at once")

    def test_a_monthly_purchase_carries_the_fee_as_its_own_line(self):
        lines = self.membership.fitness_order_line_vals(
            self.partner, plan=self.month, period_price=95.0)
        mat_ids = self.matricula.product_variant_ids.ids
        self.assertTrue(
            any(l["product_id"] in mat_ids for l in lines),
            "the registration fee is not on the order")

    def test_a_quarterly_purchase_does_not(self):
        lines = self.membership.fitness_order_line_vals(
            self.partner, plan=self.quarter, period_price=95.0)
        mat_ids = self.matricula.product_variant_ids.ids
        self.assertFalse(
            any(l["product_id"] in mat_ids for l in lines),
            "the fee was charged on a commitment that waives it")

    def test_a_total_price_is_taken_as_given(self):
        """What the desk passes: the cash taken for the whole sale, which must
        not then be multiplied by the months again."""
        lines = self.membership.fitness_order_line_vals(
            self.partner, plan=self.quarter, total_price=250.0)
        pack_lines = [l for l in lines
                      if l["product_id"] in self.membership.product_variant_ids.ids]
        self.assertAlmostEqual(pack_lines[0]["price_unit"], 250.0, places=2)

    # -- helpers -----------------------------------------------------------

    def _give_a_past_membership(self):
        """A membership she already holds, shaped like a real one.

        With a plan: Odoo's constraint runs both ways - a recurring product
        without a plan is refused exactly as a plan without a recurring
        product is. An order carrying one and not the other is not a
        membership anybody could have bought.
        """
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "plan_id": self.month.id,
            "order_line": [(0, 0, {
                "product_id": self.membership.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 95.0,
            })],
        })
        order.action_confirm()
        return order
