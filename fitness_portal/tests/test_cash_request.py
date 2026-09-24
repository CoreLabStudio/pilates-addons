# -*- coding: utf-8 -*-
"""A student asks to pay at the desk, and the desk says the money arrived.

The order she creates is deliberately inert: draft, no credits, nothing
bookable. Everything that makes a purchase real happens on approval, and it
has to happen exactly as it happens for a card payment - same credits, same
validity, same matricula rules, same invoice, same notification. A cash
buyer who ends up with something different from a card buyer is the failure
this whole flow exists to avoid, so every product type is checked, not one.
"""

import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, tagged


class CashRequestFixture:
    """Shared fixture: one student, and one of each thing she can buy."""

    @classmethod
    def _build(cls):
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.password = "cash-request-pw-1"
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Cash Request Student",
                "login": "cash.request@example.invalid",
                "email": "cash.request@example.invalid",
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
                "name": "Cash Desk Manager",
                "login": "cash.desk@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })

        # A pack, a single class and a membership - the three shapes the
        # approval has to get right.
        cls.pack = cls.env["product.template"].create({
            "name": "Cash Pack 10", "list_price": 120.0, "type": "service",
            "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })
        cls.single = cls.env["product.template"].create({
            "name": "Cash Single Class", "list_price": 18.0, "type": "service",
            "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 1,
            "fitness_validity_days": 30, "fitness_class_type": "reformer",
            "fitness_session_type": "group",
        })
        cls.membership = cls.env["product.template"].create({
            "name": "Cash Membership", "list_price": 95.0, "type": "service",
            "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "barre", "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")

    def _request(self, template, plan=None):
        """What the portal creates: a draft order marked as a cash request."""
        vals = {"partner_id": self.partner.id,
                "fitness_payment_method": "cash"}
        if plan:
            vals["plan_id"] = plan.id
        order = self.env["sale.order"].create(vals)
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": template.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": template.list_price,
        })
        order.write({
            "fitness_cash_requested_on": fields.Datetime.now(),
            "fitness_terms_accepted_on": fields.Datetime.now(),
        })
        return order


@tagged("post_install", "-at_install")
class TestCashRequestIsInertUntilApproved(TransactionCase, CashRequestFixture):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()

    # ── the request itself gives her nothing ────────────────────────────────

    def test_a_request_is_a_draft_order(self):
        order = self._request(self.pack)
        self.assertEqual(order.state, "draft",
                         "a cash request confirmed itself")

    def test_a_request_mints_no_credits(self):
        """The whole point: the studio is not extending credit to anybody."""
        before = self.partner._fitness_credit_total()
        self._request(self.pack)
        self.env.invalidate_all()
        self.assertEqual(self.partner._fitness_credit_total(), before,
                         "credits appeared before the money did")

    def test_a_request_shows_up_as_pending(self):
        order = self._request(self.pack)
        self.assertTrue(order.fitness_cash_pending,
                        "the desk will never see this request")

    def test_the_deadline_is_24_hours_after_asking(self):
        order = self._request(self.pack)
        expected = order.fitness_cash_requested_on + timedelta(hours=24)
        self.assertEqual(order.fitness_cash_deadline, expected)

    def test_nothing_expires_on_its_own(self):
        """An overdue request stays on the list. Deciding it is too late is
        the studio's call, not a cron's - she may simply be late."""
        order = self._request(self.pack)
        order.write({"fitness_cash_requested_on":
                     fields.Datetime.now() - timedelta(days=3)})
        self.env.invalidate_all()
        self.assertTrue(order.fitness_cash_pending,
                        "an overdue request vanished from the desk's list")

    # ── approval ────────────────────────────────────────────────────────────

    def test_approving_a_pack_grants_its_credits(self):
        order = self._request(self.pack)
        before = self.partner._fitness_credit_total()
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale", "approval did not confirm it")
        self.assertEqual(self.partner._fitness_credit_total(), before + 10,
                         "the pack's ten credits did not arrive")

    def test_approving_a_single_class_grants_one_credit(self):
        order = self._request(self.single)
        before = self.partner._fitness_credit_total()
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertEqual(self.partner._fitness_credit_total(), before + 1)

    def test_approving_a_membership_starts_it_running(self):
        order = self._request(self.membership, plan=self.plan)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertTrue(order.is_subscription, "not a subscription")
        self.assertEqual(order.subscription_state, "3_progress",
                         "the membership is not running after approval")

    def test_approval_records_who_and_when(self):
        order = self._request(self.pack)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.assertEqual(order.fitness_cash_approved_by, self.manager)
        self.assertTrue(order.fitness_cash_approved_on)

    def test_an_approved_request_leaves_the_pending_list(self):
        order = self._request(self.pack)
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertFalse(order.fitness_cash_pending,
                         "an approved request is still waiting to be approved")

    # ── the refusals ────────────────────────────────────────────────────────

    def test_approving_twice_is_refused(self):
        """Otherwise a second click grants the credits again."""
        order = self._request(self.pack)
        order.with_user(self.manager).action_fitness_approve_cash()
        with self.assertRaises(UserError):
            order.with_user(self.manager).action_fitness_approve_cash()

    def test_an_ordinary_order_cannot_be_approved_as_cash(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 120.0,
        })
        with self.assertRaises(UserError):
            order.with_user(self.manager).action_fitness_approve_cash()

    def test_a_manager_who_is_not_an_administrator_can_approve(self):
        """The desk is staffed by managers, not administrators. Cache
        invalidated first so the fixture, built by admin, cannot answer the
        reads from cache and hide a missing right."""
        order = self._request(self.pack)
        self.env.invalidate_all()
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertEqual(order.state, "sale")


@tagged("post_install", "-at_install")
class TestCashRequestFromThePortal(HttpCase, CashRequestFixture):
    """The student's half, driven through the real checkout URL."""

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()

    def _checkout_post(self, template, **extra):
        """POST the checkout form the way the page does, token and all."""
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        url = "/my/packages/%d/checkout" % template.id
        page = self.url_open(url, timeout=30)
        self.assertEqual(page.status_code, 200, page.text[:200])
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        self.assertTrue(token, "no csrf token on the checkout page")
        data = {"csrf_token": token.group(1), "terms_accepted": "1"}
        data.update(extra)
        return self.url_open(url, data=data, timeout=30)

    def test_the_checkout_page_offers_cash(self):
        """Alongside the card, not instead of it."""
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        page = self.url_open("/my/packages/%d/checkout" % self.pack.id,
                             timeout=30)
        self.assertIn('value="cash"', page.text,
                      "cash is not offered at checkout at all")

    def test_choosing_cash_creates_a_pending_request_and_says_so(self):
        res = self._checkout_post(self.pack, payment_method="cash")
        self.assertEqual(res.status_code, 200, res.text[:200])

        order = self.env["sale.order"].sudo().search(
            [("partner_id", "=", self.partner.id),
             ("fitness_cash_requested_on", "!=", False)], limit=1)
        self.assertTrue(order, "choosing cash created no request")
        self.assertEqual(order.state, "draft",
                         "the portal confirmed a cash order")
        self.assertTrue(order.fitness_cash_pending)
        self.assertIn("within 24 hours", res.text,
                      "she was not told when to come and pay")

    def test_a_student_cannot_approve_her_own_request(self):
        """The sudo inside the action exists so a manager can read the order.
        Without an explicit gate in front of it, it would also let the person
        who owes the money mark it as paid."""
        order = self._request(self.pack)
        with self.assertRaises(AccessError):
            order.with_user(self.user).action_fitness_approve_cash()
