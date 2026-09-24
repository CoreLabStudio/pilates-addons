# -*- coding: utf-8 -*-
"""Giving something away, from both directions, for all three kinds of thing.

The rule the whole feature rests on: a gift must leave the student in the
same place a purchase would, minus the money. So these tests check what she
actually ends up holding - credits, a running membership, a booked seat -
rather than that a wizard returned without raising.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGivingAFreeGift(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Gift Manager",
                "login": "gift.manager2@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Gift Student",
                "login": "gift.student2@example.invalid",
                "email": "gift.student2@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.student.partner_id

        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Gift Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group",
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Gift Pack 5", "list_price": 70.0, "type": "service",
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        cls.membership = cls.env["product.template"].create({
            "name": "Gift Membership", "list_price": 95.0, "type": "service",
            "sale_ok": True, "fitness_is_subscription_plan": True,
            "recurring_invoice": True, "fitness_class_type": "barre",
            "fitness_session_type": "group", "weekly_class_allowance": 2,
        })
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")

    def _event(self, days=5, capacity=7):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": "Gift Class +%sd" % days,
            "start": start, "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id,
            "is_fitness_class": True, "capacity": capacity,
        })

    def _wizard(self, **vals):
        base = {"student_id": self.partner.id,
                "reason": "Birthday, agreed with Yoleyva"}
        base.update(vals)
        return self.env["fitness.gift.wizard"].with_user(
            self.manager).create(base)

    # ── a class ─────────────────────────────────────────────────────────────

    def test_giving_a_class_books_the_seat(self):
        event = self._event()
        self._wizard(gift_type="class",
                     calendar_event_id=event.id).action_give()
        self.env.invalidate_all()
        booking = self.env["fitness.booking"].sudo().search([
            ("student_id", "=", self.partner.id),
            ("calendar_event_id", "=", event.id)])
        self.assertTrue(booking, "the gifted spot was never booked")
        self.assertEqual(booking.state, "booked")

    def test_giving_a_class_costs_the_student_nothing(self):
        event = self._event()
        log = self._wizard(gift_type="class",
                           calendar_event_id=event.id).action_give()
        rec = self.env["fitness.gift.log"].browse(log["res_id"])
        self.assertEqual(rec.order_id.amount_total, 0.0,
                         "the student was charged for a gift")

    def test_giving_a_class_gifts_one_spot_not_the_class(self):
        """The wording risk made concrete: nobody else is booked."""
        event = self._event()
        self._wizard(gift_type="class",
                     calendar_event_id=event.id).action_give()
        self.env.invalidate_all()
        self.assertEqual(len(event.booking_ids), 1,
                         "gifting one spot booked more than one student")

    def test_a_full_class_is_refused(self):
        event = self._event(capacity=1)
        self._wizard(gift_type="class",
                     calendar_event_id=event.id).action_give()
        self.env.invalidate_all()
        other = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Second Gift Student",
                "login": "gift.student3@example.invalid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id])],
            })
        wiz = self._wizard(gift_type="class",
                           calendar_event_id=event.id,
                           student_id=other.partner_id.id)
        with self.assertRaises(UserError):
            wiz.action_give()

    def test_a_cancelled_class_is_refused(self):
        event = self._event()
        event.write({"class_state": "cancelled"})
        wiz = self._wizard(gift_type="class", calendar_event_id=event.id)
        with self.assertRaises(UserError):
            wiz.action_give()

    def test_the_seat_count_is_the_real_one(self):
        """Shown so the studio picks a class with room, so it must be true."""
        event = self._event(capacity=7)
        wiz = self._wizard(gift_type="class", calendar_event_id=event.id)
        self.assertIn("7", wiz.seats_label)
        self.assertIn("0", wiz.seats_label)

    # ── a package ───────────────────────────────────────────────────────────

    def test_giving_a_package_grants_its_credits(self):
        before = self.partner._fitness_credit_total()
        self._wizard(gift_type="package",
                     product_id=self.pack.id).action_give()
        self.env.invalidate_all()
        self.assertEqual(self.partner._fitness_credit_total(), before + 5,
                         "the gifted pack granted no credits")

    def test_a_gifted_package_costs_nothing(self):
        log = self._wizard(gift_type="package",
                           product_id=self.pack.id).action_give()
        rec = self.env["fitness.gift.log"].browse(log["res_id"])
        self.assertEqual(rec.order_id.amount_total, 0.0)

    # ── a membership ────────────────────────────────────────────────────────

    def test_giving_a_membership_starts_it_running(self):
        log = self._wizard(gift_type="membership",
                           product_id=self.membership.id,
                           plan_id=self.plan.id).action_give()
        rec = self.env["fitness.gift.log"].browse(log["res_id"])
        self.env.invalidate_all()
        self.assertTrue(rec.order_id.is_subscription)
        self.assertEqual(rec.order_id.subscription_state, "3_progress")

    def test_a_membership_without_a_period_is_refused(self):
        wiz = self._wizard(gift_type="membership",
                           product_id=self.membership.id)
        with self.assertRaises(UserError):
            wiz.action_give()

    # ── the reason, and who may give ────────────────────────────────────────

    def test_a_gift_without_a_reason_is_refused(self):
        wiz = self._wizard(gift_type="package",
                           product_id=self.pack.id, reason="   ")
        with self.assertRaises(UserError):
            wiz.action_give()

    def test_a_student_cannot_give_herself_a_gift(self):
        """Refused at the door: a portal user has no rights on the wizard at
        all, so she cannot even open it, let alone press the button."""
        with self.assertRaises(AccessError):
            self.env["fitness.gift.wizard"].with_user(self.student).create({
                "student_id": self.partner.id, "gift_type": "package",
                "product_id": self.pack.id, "reason": "I would like this",
            }).action_give()

    # ── the log ─────────────────────────────────────────────────────────────

    def test_every_gift_is_written_down(self):
        event = self._event()
        self._wizard(gift_type="class",
                     calendar_event_id=event.id).action_give()
        self._wizard(gift_type="package",
                     product_id=self.pack.id).action_give()
        logs = self.env["fitness.gift.log"].sudo().search(
            [("student_id", "=", self.partner.id)])
        self.assertEqual(len(logs), 2, "not every gift reached the log")
        self.assertEqual(set(logs.mapped("gift_type")), {"class", "package"})

    def test_the_log_keeps_the_reason_and_the_giver(self):
        self._wizard(gift_type="package", product_id=self.pack.id,
                     reason="Apology for the cancelled class").action_give()
        log = self.env["fitness.gift.log"].sudo().search(
            [("student_id", "=", self.partner.id)], limit=1)
        self.assertEqual(log.reason, "Apology for the cancelled class")
        self.assertEqual(log.given_by, self.manager)

    def test_the_log_records_what_was_given_away(self):
        """The studio's real question is what this is costing them."""
        self._wizard(gift_type="package",
                     product_id=self.pack.id).action_give()
        log = self.env["fitness.gift.log"].sudo().search(
            [("student_id", "=", self.partner.id)], limit=1)
        self.assertEqual(log.value, 70.0,
                         "the log does not say what was given away")

    # ── the two entry points reach the same wizard ──────────────────────────

    def test_starting_from_a_class_prefills_that_class(self):
        """The timetable button passes the class in context. Asserted on the
        defaults rather than on a created record: creating would need the
        required fields the studio has not filled in yet, which is precisely
        the state the wizard opens in."""
        event = self._event()
        defaults = self.env["fitness.gift.wizard"].with_user(
            self.manager).with_context(
                default_calendar_event_id=event.id,
                default_gift_type="class").default_get(
                    ["calendar_event_id", "gift_type", "student_id"])
        self.assertEqual(defaults.get("calendar_event_id"), event.id,
                         "the class was not carried through from the button")
        self.assertEqual(defaults.get("gift_type"), "class")
        self.assertFalse(defaults.get("student_id"),
                         "starting from a class should not guess the student")

    def test_starting_from_a_profile_prefills_that_student(self):
        defaults = self.env["fitness.gift.wizard"].with_user(
            self.manager).with_context(
                default_student_id=self.partner.id).default_get(
                    ["student_id", "calendar_event_id"])
        self.assertEqual(defaults.get("student_id"), self.partner.id,
                         "the student was not carried through from her page")
        self.assertFalse(defaults.get("calendar_event_id"),
                         "starting from a profile should not guess a class")
