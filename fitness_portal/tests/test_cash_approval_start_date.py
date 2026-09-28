# -*- coding: utf-8 -*-
"""A cash request that sat for a few days must not start in the past.

start_date is a stored compute, filled when the quotation is created and
never revisited. _confirm_subscription copies it straight into
fitness_period_start_date. So a request made on the 25th and approved on
the 28th began its quarter three days before anybody was paid: she loses
those days, and placement - which bypasses the "already started" rule -
then books classes that have already run.

S00410 had to be corrected by hand for exactly this, in the minutes before
approval, by somebody who happened to know.

What these pin:

  * approving a stale request starts the period on the day the money
    arrived, and the next invoice follows from there;
  * a start date of today is left alone, and so is one somebody has
    deliberately set in the future - moving that would be the same bug
    pointing the other way;
  * packs and single classes are untouched. They have no period at all,
    and writing start_date on them would be meaningless.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCashApprovalStartDate(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Start Date Manager",
                "login": "startdate.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.partner = cls.env["res.partner"].create(
            {"name": "Start Date Student"})
        cls.membership = cls.env["product.template"].create({
            "name": "Start Date Membership", "type": "service",
            "list_price": 90.0, "sale_ok": True, "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_class_type": "barre", "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Start Date Pack", "type": "service",
            "list_price": 60.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })

    def _request(self, product, is_sub, requested_days_ago=0,
                 start_date=None):
        vals = {
            "partner_id": self.partner.id,
            "fitness_payment_method": "cash",
            "fitness_cash_requested_on": (
                fields.Datetime.now() - timedelta(days=requested_days_ago)),
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        }
        if is_sub:
            vals["plan_id"] = self.plan.id
        order = self.env["sale.order"].sudo().create(vals)
        if start_date is not None:
            order.write({"start_date": start_date})
        self.env.invalidate_all()
        return order

    def _approve(self, order):
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()

    # ── the case it exists for ──────────────────────────────────────────────

    def test_a_request_made_days_ago_starts_on_the_day_it_is_paid(self):
        """Laura's case: asked on the 25th, paid on the 28th."""
        today = fields.Date.context_today(self.env.user)
        three_days_ago = today - timedelta(days=3)
        order = self._request(self.membership, True, requested_days_ago=3,
                              start_date=three_days_ago)
        self.assertEqual(order.start_date, three_days_ago, "fixture wrong")

        self._approve(order)

        self.assertEqual(
            order.start_date, today,
            "the period still begins before she paid, so she loses the days "
            "in between and placement can book classes that already ran")
        self.assertEqual(
            order.fitness_period_start_date, today,
            "the billing period start did not follow the start date")
        self.assertTrue(
            order.next_invoice_date and order.next_invoice_date > today,
            "the next invoice date does not follow the corrected start")

    def test_nothing_from_the_period_can_predate_the_approval(self):
        """The point of the fix, stated as the thing that must be true."""
        today = fields.Date.context_today(self.env.user)
        order = self._request(self.membership, True, requested_days_ago=6,
                              start_date=today - timedelta(days=6))
        self._approve(order)
        self.assertGreaterEqual(
            order.fitness_period_start_date, today,
            "part of the paid period lies before the payment")

    # ── and the cases it must leave alone ───────────────────────────────────

    def test_a_request_approved_the_same_day_is_untouched(self):
        today = fields.Date.context_today(self.env.user)
        order = self._request(self.membership, True, start_date=today)
        self._approve(order)
        self.assertEqual(
            order.start_date, today,
            "today's date was rewritten, which can only introduce drift")

    def test_a_start_date_set_in_the_future_is_left_alone(self):
        """Somebody chose that on purpose - she starts next month."""
        today = fields.Date.context_today(self.env.user)
        next_week = today + timedelta(days=7)
        order = self._request(self.membership, True, start_date=next_week)
        self._approve(order)
        self.assertEqual(
            order.start_date, next_week,
            "a deliberate future start was dragged back to today - the same "
            "bug pointing the other way")
        self.assertEqual(
            order.fitness_period_start_date, next_week,
            "the billing period no longer matches the chosen start")

    def test_a_pack_is_unaffected(self):
        order = self._request(self.pack, False, requested_days_ago=3)
        self._approve(order)
        self.assertEqual(
            order.state, "sale", "the pack did not sell")
        self.assertEqual(
            self.partner._fitness_credit_total(), 5,
            "the pack granted the wrong credits")
        self.assertFalse(
            order.is_subscription,
            "fixture wrong: a pack is not a subscription")

    def test_a_single_class_is_unaffected(self):
        single = self.env["product.template"].create({
            "name": "Start Date Single", "type": "service",
            "list_price": 15.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 1, "fitness_validity_days": 30,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        partner = self.env["res.partner"].create({"name": "Single Student"})
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "fitness_payment_method": "cash",
            "fitness_cash_requested_on": (
                fields.Datetime.now() - timedelta(days=4)),
            "order_line": [(0, 0, {
                "product_id": single.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 15.0,
            })],
        })
        self.env.invalidate_all()
        self._approve(order)
        self.assertEqual(order.state, "sale")
        self.assertEqual(
            partner._fitness_credit_total(), 1,
            "the single class granted the wrong credits")

    # ── the sale itself is untouched ────────────────────────────────────────

    def test_the_money_and_the_invoice_are_unchanged(self):
        """Moving a date must not move anything else."""
        today = fields.Date.context_today(self.env.user)
        order = self._request(self.membership, True, requested_days_ago=3,
                              start_date=today - timedelta(days=3))
        total_before = order.amount_total
        self._approve(order)
        self.assertEqual(
            order.amount_total, total_before,
            "correcting the start date changed what she pays")
        self.assertEqual(
            len(order.invoice_ids), 1,
            "invoiced %d times" % len(order.invoice_ids))
        self.assertTrue(
            order.fitness_cash_approved_on,
            "the approval itself did not record")
