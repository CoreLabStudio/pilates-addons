# -*- coding: utf-8 -*-
"""Two silent failures around fixed slots, made loud.

Both are ordinary admin actions with consequences nobody could see:

  * Editing or closing a schedule row moves or breaks the weekly class of
    every member attached to its series, and said nothing.
  * The nightly generation job swallows a failing schedule on purpose, so it
    reports success while generating nothing. The timetable runs dry weeks
    later and every fixed-slot renewal fails at once.

These pin that both now name what is about to happen, and - just as
important - that they stay quiet when there is nothing to say. An alert that
fires on a healthy studio is an alert that gets ignored.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestScheduleSafeguards(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Room (safeguards test)",
            "classroom_type": "reformer", "capacity": 6,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Reformer Sculpt (safeguards test)",
            "classroom_type": "reformer", "session_type": "group",
            "level": "all", "classroom_id": cls.room.id,
        })
        cls.teacher = cls.env["res.users"].create({
            "name": "Safeguards Teacher",
            "login": "safeguards.teacher@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.product = cls.env["product.template"].create({
            "name": "Reformer Fixed Class (safeguards test)",
            "type": "service", "list_price": 70.0, "sale_ok": True,
            "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_is_clase_fija": True,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group",
            "weekly_class_allowance": 1,
        })

    def _schedule(self, weekday="wed", start_time=18.0, horizon=8):
        sched = self.env["fitness.class.schedule"].create({
            "class_type_id": self.class_type.id,
            "teacher_user_id": self.teacher.id,
            "classroom_id": self.room.id,
            "weekday": weekday, "start_time": start_time,
            "duration": 1.0, "capacity": 6,
            "date_start": fields.Date.today(), "horizon_weeks": horizon,
        })
        sched.action_generate()
        return sched

    def _member_on(self, sched, name="Safeguards Member"):
        """A running subscription whose fixed slot is that schedule's series."""
        user = self.env["res.users"].create({
            "name": name,
            "login": "%s@example.invalid" % name.lower().replace(" ", "."),
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id])],
        })
        order = self.env["sale.order"].create({
            "partner_id": user.partner_id.id, "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_ids[:1].id,
                "product_uom_qty": 1})],
        })
        order.action_confirm()
        anchor = self.env["calendar.event"].search(
            [("recurrence_id", "=", sched.recurrence_id.id)],
            order="start asc", limit=1)
        self.env["fitness.clase.fija"].create({
            "subscription_id": order.id, "calendar_event_id": anchor.id,
        })
        return order

    # ── PART 1: a schedule edit names who it lands on ───────────────────────

    def test_a_schedule_with_nobody_on_it_says_nothing(self):
        """The quiet case matters most: this is the common one."""
        sched = self._schedule()
        self.assertEqual(sched.fixed_slot_count, 0)
        self.assertFalse(sched.fixed_slot_names)
        self.assertFalse(sched._fixed_slot_note(),
                         "a slot nobody is on produced a warning anyway")

        form = self.env["fitness.class.schedule"].browse(sched.id)
        with self.env.cr.savepoint():
            warned = form._onchange_warn_fixed_slot_members()
        self.assertFalse(warned, "warned about an edit that affects nobody")

    def test_a_schedule_with_a_member_names_her(self):
        sched = self._schedule()
        order = self._member_on(sched, "Attached Member")
        sched.invalidate_recordset()

        self.assertEqual(sched.fixed_slot_count, 1,
                         "the member attached to this series was not found")
        self.assertIn("Attached Member", sched.fixed_slot_names)
        self.assertIn(order.fitness_clase_fija_ids[:1], sched.fixed_slot_ids)

    def test_editing_warns_and_names_the_member(self):
        sched = self._schedule()
        self._member_on(sched, "Warned Member")
        sched.invalidate_recordset()

        warned = sched._onchange_warn_fixed_slot_members()
        self.assertTrue(warned, "changing a slot somebody is on did not warn")
        message = warned["warning"]["message"]
        self.assertIn("Warned Member", message,
                      "the warning does not say who is affected")
        self.assertIn("1", message, "the warning does not say how many")

    def test_a_member_on_a_different_series_is_not_counted(self):
        """Attachment is to the series, not to a weekday that looks similar."""
        wed = self._schedule("wed", 18.0)
        thu = self._schedule("thu", 18.0)
        self._member_on(wed, "Wednesday Member")
        wed.invalidate_recordset()
        thu.invalidate_recordset()

        self.assertEqual(wed.fixed_slot_count, 1)
        self.assertEqual(thu.fixed_slot_count, 0,
                         "a member was counted against a series she is not on")

    def test_closing_the_slot_reports_who_lost_their_class(self):
        sched = self._schedule()
        self._member_on(sched, "Cut Off Member")
        sched.invalidate_recordset()

        note = sched._fixed_slot_note()
        self.assertIn("Cut Off Member", note)

        result = sched.action_close_for_booking()
        self.assertFalse(sched.active, "the slot was not actually closed")
        self.assertIn("Cut Off Member", result["params"]["message"],
                      "closing the slot did not say whose class it removed")

    def test_an_ended_subscription_is_not_somebody_an_edit_can_hurt(self):
        sched = self._schedule()
        order = self._member_on(sched, "Former Member")
        sched.invalidate_recordset()
        self.assertEqual(sched.fixed_slot_count, 1)

        order.subscription_state = "6_churn"
        sched.invalidate_recordset()
        self.assertEqual(sched.fixed_slot_count, 0,
                         "a finished subscription still counted as affected")

    # ── PART 2: generation that has stopped is reported ─────────────────────

    def test_a_healthy_studio_raises_nothing(self):
        self._schedule()
        stale, reason = self.env["fitness.class.schedule"]._generation_health()
        self.assertFalse(reason, "a freshly generated schedule was called stale")
        self.assertFalse(stale)

    def test_a_schedule_left_behind_is_caught(self):
        sched = self._schedule()
        Schedule = self.env["fitness.class.schedule"]
        slack = Schedule.GENERATION_SLACK_DAYS

        # Exactly at the limit is still fine: the cron runs daily and running
        # late is not the same as having stopped.
        sched.generated_until = sched._target_until() - timedelta(days=slack)
        stale, reason = Schedule._generation_health()
        self.assertFalse(reason, "a schedule inside the slack window alerted")

        # A day past it is the signal.
        sched.generated_until = sched._target_until() - timedelta(days=slack + 1)
        stale, reason = Schedule._generation_health()
        self.assertTrue(reason, "a stalled schedule did not raise anything")
        self.assertIn(sched, stale)

    def test_a_switched_off_cron_is_itself_the_fault(self):
        self._schedule()
        Schedule = self.env["fitness.class.schedule"]
        cron = self.env.ref("fitness_core.ir_cron_extend_class_schedules")
        cron.sudo().active = False
        stale, reason = Schedule._generation_health()
        self.assertTrue(reason, "generation switched off was reported as healthy")
        self.assertIn("off", reason.lower())

    def test_a_finished_schedule_is_not_a_fault(self):
        """A row past its end date has stopped generating on purpose."""
        sched = self._schedule()
        sched.date_end = fields.Date.today() - timedelta(days=1)
        sched.generated_until = fields.Date.today() - timedelta(days=90)
        stale, reason = self.env["fitness.class.schedule"]._generation_health()
        self.assertNotIn(sched, stale,
                         "a deliberately ended schedule was reported as stalled")

    def test_the_cron_runs_clean_when_all_is_well(self):
        self._schedule()
        self.assertTrue(
            self.env["fitness.class.schedule"]._cron_check_generation_health())
