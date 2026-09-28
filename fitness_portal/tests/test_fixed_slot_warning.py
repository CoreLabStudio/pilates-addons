# -*- coding: utf-8 -*-
"""Telling the studio when a fixed-class membership has no weekly hour.

A Clase Fija membership promises the same class every week without saying
which, and the hour is chosen in the app. Sell one at the desk, or approve
one from a cash request, and it arrives with no slot at all: placement walks
the slots, finds none, books nothing and raises nothing. The absence of an
error reads as success, and the member pays weekly for an empty schedule.

Laura Bucur, 28 September 2026: paid, active, 0 slots, 0 bookings, nobody
told.

What these pin:

  * the rule has ONE implementation. The member's prompt in the app and the
    manager's warning in the back office ask the same method, so they cannot
    come to different answers about the same membership - which is exactly
    what happened when only the app asked;
  * it fires for a membership that owes an hour and stays silent for every
    other kind of sale, because a warning that cries wolf on packs will be
    ignored on the one that matters;
  * a combined plan names the discipline that is missing - "choose an hour"
    is useless advice to somebody who has already chosen one of two;
  * the manager is told at the moment of sale, in both places money is
    taken, and it survives to the next day in the chatter;
  * nothing is blocked. The sale, the money and the invoice are untouched.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFixedSlotWarning(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")

        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Slot Warning Manager",
                "login": "slot.warn.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.partner = cls.env["res.partner"].create(
            {"name": "Slot Warning Student", "email": False})

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Barre Room (slot warning)",
            "classroom_type": "barre", "capacity": 8,
        })
        cls.barre_type = cls.env["fitness.class.type"].create({
            "name": "Barre (slot warning)", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.reformer_room = cls.env["fitness.classroom"].create({
            "name": "Reformer Room (slot warning)",
            "classroom_type": "reformer", "capacity": 6,
        })
        cls.reformer_type = cls.env["fitness.class.type"].create({
            "name": "Reformer (slot warning)", "classroom_type": "reformer",
            "session_type": "group", "level": "all",
            "classroom_id": cls.reformer_room.id,
        })

    # ── fixtures ────────────────────────────────────────────────────────────

    @classmethod
    def _fixed_plan(cls, name, allowance=1, secondary=None,
                    secondary_allowance=0):
        vals = {
            "name": name, "type": "service", "list_price": 90.0,
            "sale_ok": True, "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_is_clase_fija": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": allowance,
        }
        if secondary:
            vals["fitness_secondary_class_type"] = secondary
            vals["fitness_secondary_weekly_allowance"] = secondary_allowance
        return cls.env["product.template"].create(vals)

    def _subscribe(self, product, partner=None):
        order = self.env["sale.order"].sudo().create({
            "partner_id": (partner or self.partner).id,
            "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        })
        order.action_confirm()
        self.env.invalidate_all()
        return order

    def _event(self, class_type, days=3, hour=18):
        start = (fields.Datetime.now() + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": "%s slot class" % class_type.name,
            "start": start,
            "stop": start + timedelta(minutes=55),
            "class_type_id": class_type.id,
            "is_fitness_class": True,
            "capacity": 8,
        })

    def _give_slot(self, order, class_type):
        slot = self.env["fitness.clase.fija"].sudo().create({
            "subscription_id": order.id,
            "calendar_event_id": self._event(class_type).id,
        })
        self.env.invalidate_all()
        return slot

    # ── 1. the case it exists for, and its negative ─────────────────────────

    def test_a_fixed_class_membership_with_no_hour_warns(self):
        order = self._subscribe(self._fixed_plan("Warn Fixed 1"))
        self.assertTrue(
            order.fitness_needs_fixed_slot,
            "a paid fixed-class membership with no weekly hour said nothing")
        self.assertEqual(order.fitness_missing_fixed_slots(), {"barre": 1})
        self.assertIn(
            "Place Classes", order.fitness_fixed_slot_warning or "",
            "the warning does not say what to do about it")

    def test_once_the_hour_is_chosen_it_goes_quiet(self):
        order = self._subscribe(self._fixed_plan("Warn Fixed 2"))
        self.assertTrue(order.fitness_needs_fixed_slot, "fixture wrong")

        self._give_slot(order, self.barre_type)

        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "still warning after the hour was chosen - it would be ignored "
            "within a week")
        self.assertFalse(order.fitness_fixed_slot_warning)
        self.assertEqual(order.fitness_missing_fixed_slots(), {})

    def test_an_archived_slot_does_not_count_as_chosen(self):
        """The negative of the negative: unticking Active owes her again."""
        order = self._subscribe(self._fixed_plan("Warn Fixed 3"))
        slot = self._give_slot(order, self.barre_type)
        self.assertFalse(order.fitness_needs_fixed_slot, "fixture wrong")

        slot.active = False
        self.env.invalidate_all()
        self.assertTrue(
            order.fitness_needs_fixed_slot,
            "an archived slot still counted, so she owes an hour nobody "
            "will ask for")

    # ── 2. it stays silent on everything else ───────────────────────────────

    def test_a_membership_that_is_not_fixed_class_never_warns(self):
        plain = self.env["product.template"].create({
            "name": "Warn Plain Membership", "type": "service",
            "list_price": 95.0, "sale_ok": True, "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": self.plan.id,
            "fitness_class_type": "barre", "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })
        order = self._subscribe(plain)
        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "an ordinary membership was told to choose a weekly hour it "
            "does not have")

    def test_a_pack_never_warns(self):
        pack = self.env["product.template"].create({
            "name": "Warn Pack", "type": "service", "list_price": 100.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
            })],
        })
        order.action_confirm()
        self.env.invalidate_all()
        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "a pack was told to choose a weekly hour")

    def test_an_unconfirmed_membership_does_not_warn_yet(self):
        """Nothing has been paid and nothing is owed."""
        product = self._fixed_plan("Warn Draft")
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id, "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        })
        self.env.invalidate_all()
        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "a quotation nobody has paid for is already being chased")

    # ── 3. more than one hour a week ────────────────────────────────────────

    def test_a_two_a_week_plan_is_not_finished_after_one_hour(self):
        order = self._subscribe(self._fixed_plan("Warn Fixed Two", allowance=2))
        self.assertEqual(order.fitness_missing_fixed_slots(), {"barre": 2})

        self._give_slot(order, self.barre_type)
        self.assertEqual(
            order.fitness_missing_fixed_slots(), {"barre": 1},
            "one of two hours chosen and it already calls her finished")
        self.assertTrue(order.fitness_needs_fixed_slot)

        self._give_slot(order, self.barre_type)
        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "both hours chosen and it is still asking")

    # ── 4. a combined plan names the discipline ─────────────────────────────

    def test_a_combined_plan_names_the_discipline_still_missing(self):
        product = self._fixed_plan(
            "Warn Combined", allowance=1,
            secondary="reformer", secondary_allowance=1)
        order = self._subscribe(product)
        self.assertEqual(
            order.fitness_missing_fixed_slots(),
            {"barre": 1, "reformer": 1})

        self._give_slot(order, self.barre_type)

        missing = order.fitness_missing_fixed_slots()
        self.assertEqual(
            missing, {"reformer": 1},
            "Barre is chosen and Reformer is not, but the rule does not say "
            "so - counting the slots together calls her finished")
        warning = order.fitness_fixed_slot_warning or ""
        self.assertIn(
            "reformer", warning.lower(),
            "the warning does not name the discipline that is missing")
        self.assertNotIn(
            "barre", warning.lower(),
            "the warning chases a discipline she has already chosen")

    def test_a_combined_plan_goes_quiet_when_both_are_chosen(self):
        product = self._fixed_plan(
            "Warn Combined Done", allowance=1,
            secondary="reformer", secondary_allowance=1)
        order = self._subscribe(product)
        self._give_slot(order, self.barre_type)
        self._give_slot(order, self.reformer_type)
        self.assertFalse(
            order.fitness_needs_fixed_slot,
            "both disciplines chosen and it is still asking")

    # ── 5. the moment of sale: cash approval ────────────────────────────────

    def _cash_request(self, product):
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id, "plan_id": self.plan.id,
            "fitness_payment_method": "cash",
            "fitness_cash_requested_on": fields.Datetime.now(),
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        })
        self.env.invalidate_all()
        return order

    def _chatter(self, order):
        return " ".join(
            (m.body or "") for m in order.sudo().message_ids)

    def test_approving_a_cash_fixed_class_tells_the_manager(self):
        order = self._cash_request(self._fixed_plan("Warn Cash Fixed"))
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()

        self.assertIn(
            "Place Classes", self._chatter(order),
            "the manager took the money and was never told the membership "
            "books nothing")
        self.assertEqual(
            order.state, "sale",
            "the warning interfered with the sale - it must never block")

    def test_approving_a_cash_pack_says_nothing_about_weekly_hours(self):
        pack = self.env["product.template"].create({
            "name": "Warn Cash Pack", "type": "service", "list_price": 60.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 3, "fitness_validity_days": 60,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id,
            "fitness_payment_method": "cash",
            "fitness_cash_requested_on": fields.Datetime.now(),
            "order_line": [(0, 0, {
                "product_id": pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 60.0,
            })],
        })
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()

        self.assertNotIn(
            "Place Classes", self._chatter(order),
            "a pack was reported as needing a weekly hour; a warning that "
            "fires on everything gets ignored on the one that matters")

    def test_a_cash_fixed_class_with_its_hour_already_set_says_nothing(self):
        """The approval warning's negative: not every fixed-class sale warns.

        Asserted on the message the approval consults rather than by forcing
        an approved order back to draft, which the subscription state
        machine rightly refuses.
        """
        order = self._cash_request(self._fixed_plan("Warn Cash Ready"))
        order.with_user(self.manager).action_fitness_approve_cash()
        self.env.invalidate_all()
        self.assertTrue(
            order._fitness_fixed_slot_message(),
            "fixture wrong: this one should owe an hour")

        self._give_slot(order, self.barre_type)

        self.assertFalse(
            order._fitness_fixed_slot_message(),
            "a membership whose hour is chosen would still be reported at "
            "approval, and a warning that always fires is never read")

    # ── 6. the same question, asked once ────────────────────────────────────

    def test_the_app_prompt_and_the_admin_warning_agree_exactly(self):
        """Two copies of this rule is what caused the problem. One now."""
        from odoo.addons.fitness_portal.controllers.portal import (
            FitnessStudentPortal)

        owing = self._subscribe(self._fixed_plan("Warn Agree Owing"))
        settled = self._subscribe(self._fixed_plan("Warn Agree Settled"))
        self._give_slot(settled, self.barre_type)
        self.env.invalidate_all()

        from_model = self.env["sale.order"].sudo(
            ).fitness_subs_needing_fixed_slots(self.partner)
        self.assertIn(owing, from_model)
        self.assertNotIn(settled, from_model)

        flagged = from_model.filtered("fitness_needs_fixed_slot")
        self.assertEqual(
            set(from_model.ids), set(flagged.ids),
            "a membership the app would chase carries no warning for the "
            "studio, or the other way round")
        self.assertTrue(
            hasattr(FitnessStudentPortal, "_clase_fija_subs_needing_slots"),
            "the portal no longer exposes the member's side of the rule")


@tagged("post_install", "-at_install")
class TestFixedSlotWarningReachesHer(TransactionCase):
    """Who can actually see this, which is not who you would assume.

    A studio manager has no rights on sale.order at all. Opening the order
    form raises AccessError for her, so the banner reaches only a manager who
    is ALSO a Sales user - on production that is the owner and nobody else.
    That is not a fault in the banner; it is why the warning is said twice,
    and why the second place it is said is the one that matters for everyone
    else.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        base_groups = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("fitness_core.group_fitness_manager").id,
        ]
        # The owner: studio manager and Sales user both.
        cls.owner = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Banner Owner",
                "login": "banner.owner@example.invalid",
                "group_ids": [(6, 0, base_groups + [
                    cls.env.ref("sales_team.group_sale_salesman").id])],
            })
        # Everybody else at the desk.
        cls.desk = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Banner Desk Manager",
                "login": "banner.desk@example.invalid",
                "group_ids": [(6, 0, base_groups)],
            })
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.partner = cls.env["res.partner"].create({"name": "Banner Student"})
        cls.product = cls.env["product.template"].create({
            "name": "Banner Fixed Plan", "type": "service",
            "list_price": 90.0, "sale_ok": True, "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_is_clase_fija": True, "fitness_class_type": "barre",
            "fitness_session_type": "group", "weekly_class_allowance": 1,
        })

    def setUp(self):
        super().setUp()
        self.env.invalidate_all()

    def _confirmed_order(self):
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id, "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        })
        order.action_confirm()
        self.env.invalidate_all()
        return order

    # ── the owner, who can open the order ───────────────────────────────────

    def test_the_banner_is_in_the_form_the_owner_is_served(self):
        arch = self.env["sale.order"].with_user(
            self.owner).get_view(view_type="form")["arch"]
        self.assertIn(
            "fitness_fixed_slot_warning", arch,
            "the warning is not in the form, so nobody ever sees it")
        self.assertIn(
            "fitness_needs_fixed_slot", arch,
            "the field the banner's visibility depends on is missing")

    def test_the_owner_reads_the_warning_on_a_real_order(self):
        order = self._confirmed_order()
        as_owner = order.with_user(self.owner)
        self.assertTrue(
            as_owner.fitness_needs_fixed_slot,
            "the owner cannot see that the membership owes an hour")
        self.assertIn(
            "Place Classes", as_owner.fitness_fixed_slot_warning or "",
            "the warning reads empty for the person it is written for")

    # ── everybody else, who cannot ──────────────────────────────────────────

    def test_a_manager_without_sales_rights_cannot_open_the_order_at_all(self):
        """Not a fault to fix here - the reason the warning is said twice.

        If this ever starts passing, a manager has been given Sales rights
        and the banner has become her channel too.
        """
        order = self._confirmed_order()
        with self.assertRaises(AccessError):
            order.with_user(self.desk).read(["name"])

    def test_she_is_told_at_the_desk_instead(self):
        """The 'shows something' half: silent on the form must not mean
        silent everywhere."""
        wizard = self.env["fitness.desk.sale.wizard"].with_user(
            self.desk).create({
                "partner_id": self.partner.id,
                # product.template on this wizard, not a variant.
                "product_id": self.product.id,
                "plan_id": self.plan.id,
                "payment_method": "cash",
                "amount_paid": 90.0,
            })
        result = wizard.action_create_sale()
        self.env.invalidate_all()

        blob = str(result)
        self.assertIn(
            "Place Classes", blob,
            "a manager who cannot open the order was told nothing at the "
            "one moment she was looking - she sold a membership that books "
            "no classes and walked away")

        order = self.env["sale.order"].sudo().search(
            [("partner_id", "=", self.partner.id)], order="id desc", limit=1)
        self.assertIn(
            "Place Classes",
            " ".join((m.body or "") for m in order.message_ids),
            "nothing was left on the order for whoever picks this up later")

    def test_a_pack_sold_at_the_desk_says_nothing_about_hours(self):
        pack = self.env["product.template"].create({
            "name": "Banner Desk Pack", "type": "service",
            "list_price": 50.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 3, "fitness_validity_days": 60,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        wizard = self.env["fitness.desk.sale.wizard"].with_user(
            self.desk).create({
                "partner_id": self.partner.id,
                "product_id": pack.id,
                "payment_method": "cash",
                "amount_paid": 50.0,
            })
        self.assertNotIn(
            "Place Classes", str(wizard.action_create_sale()),
            "a pack sold at the desk was reported as owing a weekly hour")
