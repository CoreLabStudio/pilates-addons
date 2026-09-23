# -*- coding: utf-8 -*-
"""Renewing a membership at the desk, in cash.

Renewal did not exist in any form before this: the portal displayed the next
billing date and rolled it forward when it had passed, and nothing anywhere
renewed anything. Odoo's own recurring invoicing is switched off on this
studio's database and three of its four members hold no saved card, so
nothing was going to bill them either.

This is the desk half - the studio takes the money in person and the
membership continues on the plan she is already on.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMembershipCashRenewal(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Renew Manager",
            "login": "renew.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.student = cls.env["res.users"].create({
            "name": "Renew Student",
            "login": "renew.student@example.invalid",
            "email": "renew.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        cls.partner = cls.student.partner_id
        cls.month = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.membership = cls.env["product.template"].create({
            "name": "Renew membership",
            "list_price": 95.0,
            "type": "service",
            "fitness_is_subscription_plan": True,
            "recurring_invoice": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })

    def _running_membership(self):
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

    # -- the fixture is a real subscription, or nothing below means anything

    def test_the_fixture_is_a_running_subscription(self):
        sub = self._running_membership()
        self.assertTrue(sub.is_subscription, "not a subscription")
        self.assertEqual(sub.subscription_state, "3_progress")
        self.assertTrue(sub.next_invoice_date, "no billing date to move")

    # -- renewing ----------------------------------------------------------

    def test_renewing_moves_the_billing_date_forward(self):
        sub = self._running_membership()
        before = sub.next_invoice_date

        sub.with_user(self.manager).action_fitness_renew_cash()

        sub.invalidate_recordset()
        self.assertGreater(
            sub.next_invoice_date, before,
            "the membership was not carried into its next period")

    def test_renewing_raises_and_sends_an_invoice(self):
        sub = self._running_membership()
        before_moves = self.env["account.move"].search([]).ids

        sub.with_user(self.manager).action_fitness_renew_cash()

        new = self.env["account.move"].search([("id", "not in", before_moves)])
        theirs = new.filtered(lambda m: m.partner_id == self.partner
                              and m.move_type == "out_invoice")
        self.assertTrue(theirs, "no invoice was raised for the renewal")
        self.assertEqual(theirs[:1].state, "posted", "the invoice is a draft")
        self.assertTrue(
            theirs[:1].is_move_sent,
            "the renewal invoice was never sent - the cash payer gets a "
            "document she is not shown, where an online payer is emailed it")

    def test_it_stays_one_membership_not_two(self):
        """A renewal is the same plan continuing, not a second subscription."""
        sub = self._running_membership()
        before = self.env["sale.order"].search_count([
            ("partner_id", "=", self.partner.id), ("is_subscription", "=", True)])

        sub.with_user(self.manager).action_fitness_renew_cash()

        after = self.env["sale.order"].search_count([
            ("partner_id", "=", self.partner.id), ("is_subscription", "=", True)])
        self.assertEqual(
            after, before,
            "renewing created a second subscription; her membership history "
            "becomes a pile of orders instead of one plan")

    # -- who may, and what may be renewed ----------------------------------

    def test_only_a_manager_may_renew(self):
        sub = self._running_membership()
        with self.assertRaises(UserError):
            sub.with_user(self.student).action_fitness_renew_cash()

    def test_a_plain_order_is_not_renewable(self):
        pack = self.env["product.template"].create({
            "name": "Renew pack", "list_price": 75.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 5,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 75.0})]})
        order.action_confirm()

        with self.assertRaises(UserError):
            order.with_user(self.manager).action_fitness_renew_cash()


    # -- changing the commitment at renewal --------------------------------

    def _invoiced_membership(self):
        """A membership that has been through one period.

        Odoo refuses to raise a renewal quotation from a subscription that has
        never been invoiced - there is nothing to renew from - so the plan
        change cannot be tested on a fresh one.
        """
        sub = self._running_membership()
        sub.with_user(self.manager).action_fitness_renew_cash()
        sub.invalidate_recordset()
        return sub

    def test_a_fresh_membership_cannot_change_plan_yet(self):
        """Said as a sentence about her membership, not a raw ValidationError."""
        quarter = self.env.ref("fitness_subscriptions.subscription_plan_quarter")
        sub = self._running_membership()
        with self.assertRaises(UserError):
            sub.with_user(self.manager).action_fitness_renew_cash(
                new_plan=quarter)

    def test_moving_to_a_quarter_starts_a_new_commitment(self):
        quarter = self.env.ref("fitness_subscriptions.subscription_plan_quarter")
        sub = self._invoiced_membership()

        sub.with_user(self.manager).action_fitness_renew_cash(new_plan=quarter)

        renewed = self.env["sale.order"].search([
            ("partner_id", "=", self.partner.id),
            ("plan_id", "=", quarter.id),
            ("state", "=", "sale"),
        ], limit=1)
        self.assertTrue(renewed, "no confirmed order on the new plan")
        self.assertNotEqual(
            renewed, sub, "the plan was changed in place instead of renewed")

    def test_the_new_commitment_is_priced_for_three_months(self):
        """A Trimestral is three months charged at once - the 585-as-195
        fault, on the renewal path this time."""
        quarter = self.env.ref("fitness_subscriptions.subscription_plan_quarter")
        sub = self._invoiced_membership()

        sub.with_user(self.manager).action_fitness_renew_cash(new_plan=quarter)

        renewed = self.env["sale.order"].search([
            ("partner_id", "=", self.partner.id),
            ("plan_id", "=", quarter.id), ("state", "=", "sale")], limit=1)
        membership_lines = renewed.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == self.membership)
        self.assertTrue(membership_lines, "no membership line on the renewal")
        self.assertAlmostEqual(
            membership_lines[0].price_unit, 285.0, places=2,
            msg="the new commitment was priced at one month, not three")

    def test_renewing_on_the_same_plan_is_not_a_plan_change(self):
        """Passing the plan she is already on must renew in place."""
        sub = self._invoiced_membership()
        before = self.env["sale.order"].search_count([
            ("partner_id", "=", self.partner.id), ("is_subscription", "=", True)])

        sub.with_user(self.manager).action_fitness_renew_cash(
            new_plan=self.month)

        after = self.env["sale.order"].search_count([
            ("partner_id", "=", self.partner.id), ("is_subscription", "=", True)])
        self.assertEqual(
            after, before,
            "renewing on the same plan raised a second contract")


    def test_a_manager_can_renew_without_sales_rights(self):
        """The reads behind a renewal must not need Sales access.

        This is the trap the other tests could not see: they created the
        subscription as admin, so its fields sat in ORM cache and the manager
        never actually read sale.order. Invalidating first forces the read a
        real manager's click would make - and a fitness manager cannot read
        sale.order at all, so every field access raised AccessError.
        """
        sub = self._running_membership()
        sub.invalidate_recordset()

        # No assertRaises: the point is that this simply works.
        sub.with_user(self.manager).action_fitness_renew_cash()

        sub.invalidate_recordset()
        self.assertTrue(
            sub.next_invoice_date,
            "the renewal did not complete for a manager without Sales rights")
