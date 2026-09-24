# -*- coding: utf-8 -*-
"""Both ways of taking cash, for all three things a student can buy.

Path A is the desk: the student has no app, so a manager does the whole
thing. Path B is self-service: she chooses Cash in her own checkout, and the
desk approves it when she turns up with the money.

The two must leave her in the same place. A student who paid cash at the
desk and one who paid cash after asking in the app should be
indistinguishable afterwards - same credits, same membership state, same
notification. Every cell below asserts the outcome rather than that a method
returned, because "it did not raise" is not the same as "she got her pack".
"""

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBothCashPathsForEveryProduct(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Matrix Manager",
                "login": "matrix.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.plan_month = cls.env.ref("sale_subscription.subscription_plan_month")

        # one of each thing she can buy
        cls.single = cls.env["product.template"].create({
            "name": "Matrix Single Class", "list_price": 18.0,
            "type": "service", "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 1,
            "fitness_validity_days": 30, "fitness_class_type": "reformer",
            "fitness_session_type": "group",
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Matrix Pack 10", "list_price": 120.0,
            "type": "service", "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })
        cls.membership = cls.env["product.template"].create({
            "name": "Matrix Membership", "list_price": 95.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "barre", "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })

    # ── helpers ─────────────────────────────────────────────────────────────

    def _student(self, suffix):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Matrix %s" % suffix,
                "login": "matrix.%s@example.invalid" % suffix,
                "email": "matrix.%s@example.invalid" % suffix,
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        user.partner_id.write({"email": user.login})
        return user

    def _notifications(self, user):
        return self.env["fitness.notification"].sudo().search(
            [("user_id", "=", user.id)])

    # ── Path A: the desk sells it ───────────────────────────────────────────

    def _desk_sale(self, user, template, price, plan=None):
        vals = {
            "partner_id": user.partner_id.id,
            "product_id": template.id,
            "payment_method": "cash",
            "amount_paid": price,
        }
        if plan:
            vals["plan_id"] = plan.id
        wiz = self.env["fitness.desk.sale.wizard"].with_user(
            self.manager).create(vals)
        wiz.action_create_sale()
        return self.env["sale.order"].sudo().search(
            [("partner_id", "=", user.partner_id.id)], order="id desc", limit=1)

    def test_A1_desk_sells_a_single_class(self):
        user = self._student("a1")
        before = user.partner_id._fitness_credit_total()
        order = self._desk_sale(user, self.single, 18.0)
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale", "order not confirmed")
        self.assertEqual(user.partner_id._fitness_credit_total(), before + 1,
                         "the single class granted no credit")
        self.assertEqual(order.fitness_payment_method, "cash")

    def test_A2_desk_sells_a_pack(self):
        user = self._student("a2")
        before = user.partner_id._fitness_credit_total()
        order = self._desk_sale(user, self.pack, 120.0)
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale")
        self.assertEqual(user.partner_id._fitness_credit_total(), before + 10,
                         "the pack's ten credits did not arrive")

    def test_A3_desk_sells_a_membership(self):
        user = self._student("a3")
        order = self._desk_sale(user, self.membership, 95.0,
                                plan=self.plan_month)
        self.env.invalidate_all()
        self.assertTrue(order.is_subscription, "not a subscription")
        self.assertEqual(order.subscription_state, "3_progress",
                         "the membership is not running")

    def test_A4_a_desk_cash_sale_is_invoiced(self):
        """Cash has no payment transaction, so nothing invoices it by
        itself. The desk does it explicitly, or the only paying customer who
        never gets an invoice is the one who paid in person."""
        user = self._student("a4")
        order = self._desk_sale(user, self.pack, 120.0)
        self.env.invalidate_all()
        self.assertTrue(order.invoice_ids, "no invoice for a cash sale")
        self.assertEqual(order.invoice_ids[:1].state, "posted",
                         "the invoice was left in draft")

    # ── Path B: she asks, the desk approves ─────────────────────────────────

    def _cash_request(self, user, template, price, plan=None):
        vals = {"partner_id": user.partner_id.id,
                "fitness_payment_method": "cash"}
        if plan:
            vals["plan_id"] = plan.id
        order = self.env["sale.order"].create(vals)
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": template.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": price,
        })
        order.write({"fitness_cash_requested_on": fields.Datetime.now()})
        return order

    def test_B0_a_request_gives_her_nothing_until_approved(self):
        user = self._student("b0")
        before = user.partner_id._fitness_credit_total()
        order = self._cash_request(user, self.pack, 120.0)
        self.env.invalidate_all()
        self.assertEqual(order.state, "draft")
        self.assertTrue(order.fitness_cash_pending)
        self.assertEqual(user.partner_id._fitness_credit_total(), before,
                         "credits appeared before the money did")

    def test_B1_approved_single_class(self):
        user = self._student("b1")
        before = user.partner_id._fitness_credit_total()
        order = self._cash_request(user, self.single, 18.0)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale")
        self.assertEqual(user.partner_id._fitness_credit_total(), before + 1)

    def test_B2_approved_pack(self):
        user = self._student("b2")
        before = user.partner_id._fitness_credit_total()
        order = self._cash_request(user, self.pack, 120.0)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale")
        self.assertEqual(user.partner_id._fitness_credit_total(), before + 10)

    def test_B3_approved_membership(self):
        user = self._student("b3")
        order = self._cash_request(user, self.membership, 95.0,
                                   plan=self.plan_month)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertTrue(order.is_subscription)
        self.assertEqual(order.subscription_state, "3_progress")

    def test_B4_an_approved_request_is_invoiced(self):
        user = self._student("b4")
        order = self._cash_request(user, self.pack, 120.0)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertTrue(order.invoice_ids, "no invoice after approval")

    # ── the two paths must agree ────────────────────────────────────────────

    def test_both_paths_leave_her_holding_the_same_thing(self):
        """The point of having two paths at all: which door she came through
        must not change what she ends up with."""
        desk_user = self._student("cmp_desk")
        self._desk_sale(desk_user, self.pack, 120.0)

        app_user = self._student("cmp_app")
        order = self._cash_request(app_user, self.pack, 120.0)
        order.with_user(self.manager).action_fitness_approve_cash()

        self.env.invalidate_all()
        self.assertEqual(
            desk_user.partner_id._fitness_credit_total(),
            app_user.partner_id._fitness_credit_total(),
            "the desk and the app grant different credits for one pack")

    def test_both_paths_tell_the_student(self):
        """She is told she bought something, whichever door she used."""
        desk_user = self._student("ntf_desk")
        self._desk_sale(desk_user, self.pack, 120.0)

        app_user = self._student("ntf_app")
        order = self._cash_request(app_user, self.pack, 120.0)
        order.with_user(self.manager).action_fitness_approve_cash()

        self.env.invalidate_all()
        self.assertTrue(self._notifications(desk_user),
                        "the desk buyer was told nothing")
        self.assertTrue(self._notifications(app_user),
                        "the app buyer was told nothing")
