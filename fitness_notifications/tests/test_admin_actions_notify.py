# -*- coding: utf-8 -*-
"""What a student actually receives when the studio changes her plans.

Four admin actions, each asked the same two questions: does the bell fire,
and does an email go out. They are asked of the real actions the admin uses,
not of the notification helpers underneath them, because the defect the
studio reported is "nobody told the student" and that can come from either
layer.

Written after a client report that some of these were silent.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAdminActionsNotifyTheStudent(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Notify Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group",
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Notify Pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

    # ── fixtures ────────────────────────────────────────────────────────────

    def _student(self, suffix):
        """A student with an email, because a template with no recipient
        queues nothing and the test would pass for the wrong reason."""
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Notify Student %s" % suffix,
            "login": "notify.%s@example.invalid" % suffix,
            "email": "notify.%s@example.invalid" % suffix,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        user.partner_id.write({"email": "notify.%s@example.invalid" % suffix})
        return user

    def _event(self, days=3, capacity=10):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": "Notify Class +%sd" % days,
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
            "capacity": capacity,
        })

    def _booked(self, user, event):
        order = self.env["sale.order"].create({"partner_id": user.partner_id.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": self.pack.list_price,
            "fitness_class_type": "barre",
        })
        order.action_confirm()
        return self.env["fitness.booking"].create({
            "student_id": user.partner_id.id,
            "calendar_event_id": event.id,
            "package_order_line_id": order.order_line[:1].id,
            "manager_override_timewindow": True,
        })

    # ── measurement ─────────────────────────────────────────────────────────

    def _bells(self, user, kind=None):
        domain = [("user_id", "=", user.id)]
        if kind:
            domain.append(("notification_type", "=", kind))
        return self.env["fitness.notification"].sudo().search(domain)

    def _emails_for(self, booking):
        """Mail queued against this booking. force_send=False means the row
        is what exists, so this is the honest measure of "an email went"."""
        return self.env["mail.mail"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("res_id", "=", booking.id),
        ])

    # ── 1. the studio cancels the whole class ───────────────────────────────

    def test_cancelling_a_class_tells_every_booked_student(self):
        event = self._event()
        a, b = self._student("cls_a"), self._student("cls_b")
        ba, bb = self._booked(a, event), self._booked(b, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        event.with_user(self.env.ref("base.user_admin")).action_cancel_class()

        for user, booking in ((a, ba), (b, bb)):
            self.assertTrue(
                self._bells(user, "booking_cancelled"),
                "%s got no bell when the studio cancelled the class" % user.name)
            self.assertTrue(
                self._emails_for(booking),
                "%s got no email when the studio cancelled the class" % user.name)

    def test_cancelling_a_class_tells_each_student_exactly_once(self):
        """The per-booking bell is suppressed by _class_cancelled so that the
        class-level one is not a duplicate. If that guard ever goes, students
        get told twice for one cancellation."""
        event = self._event()
        a = self._student("once")
        self._booked(a, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        event.with_user(self.env.ref("base.user_admin")).action_cancel_class()

        self.assertEqual(
            len(self._bells(a, "booking_cancelled")), 1,
            "one cancellation produced more than one bell")

    # ── 2. the studio cancels one student's booking ─────────────────────────

    def test_cancelling_one_booking_tells_that_student(self):
        event = self._event()
        a, b = self._student("one_a"), self._student("one_b")
        ba = self._booked(a, event)
        self._booked(b, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        ba.with_context(_admin_cancel_direct=True,
                        admin_force_refund=True).action_cancel()

        self.assertTrue(self._bells(a, "booking_cancelled"),
                        "the cancelled student got no bell")
        self.assertTrue(self._emails_for(ba),
                        "the cancelled student got no email")

    def test_cancelling_one_booking_leaves_the_others_alone(self):
        event = self._event()
        a, b = self._student("only_a"), self._student("only_b")
        ba = self._booked(a, event)
        self._booked(b, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        ba.with_context(_admin_cancel_direct=True,
                        admin_force_refund=True).action_cancel()

        self.assertFalse(
            self._bells(b, "booking_cancelled"),
            "a student whose booking was untouched was told it was cancelled")

    # ── 3. the studio moves the whole class to a new time ───────────────────

    def test_rescheduling_a_class_tells_every_booked_student(self):
        event = self._event(days=3)
        a, b = self._student("res_a"), self._student("res_b")
        self._booked(a, event)
        self._booked(b, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        new_start = fields.Datetime.now() + timedelta(days=5)
        event.write({"start": new_start,
                     "stop": new_start + timedelta(minutes=45)})

        for user in (a, b):
            self.assertTrue(
                self._bells(user, "class_rescheduled"),
                "%s was not told the class moved" % user.name)

    def test_rescheduling_a_class_emails_every_booked_student(self):
        """The defect this fix exists for.

        Until now a time change reached the student through the bell and
        nothing else, so a student who did not open the app before the old
        start time was never told at all. Cancellation had always sent both.
        """
        event = self._event(days=3)
        a, b = self._student("res_m1"), self._student("res_m2")
        ba, bb = self._booked(a, event), self._booked(b, event)
        for booking in (ba, bb):
            self.env["mail.mail"].sudo().search([
                ("model", "=", "fitness.booking"),
                ("res_id", "=", booking.id)]).unlink()

        new_start = fields.Datetime.now() + timedelta(days=5)
        event.write({"start": new_start,
                     "stop": new_start + timedelta(minutes=45)})

        for user, booking in ((a, ba), (b, bb)):
            self.assertTrue(
                self._emails_for(booking),
                "%s got no email when her class was moved" % user.name)

    def test_the_reschedule_email_carries_the_new_time(self):
        """An email that says the class moved without saying where to is
        worse than none: it makes her open the app to find out, which is the
        thing she was not doing."""
        event = self._event(days=3)
        a = self._student("res_when")
        booking = self._booked(a, event)
        self.env["mail.mail"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("res_id", "=", booking.id)]).unlink()

        new_start = (fields.Datetime.now() + timedelta(days=5)).replace(
            hour=8, minute=30, second=0, microsecond=0)
        event.write({"start": new_start,
                     "stop": new_start + timedelta(minutes=45)})

        mails = self._emails_for(booking)
        self.assertTrue(mails, "no email to inspect")
        body = mails[0].body_html or ""
        self.assertIn(event.name, body, "the email does not name the class")
        # 08:30 UTC is 10:30 in Madrid, and the studio clock is what she
        # turns up by. A body carrying 08:30 would send her an hour early.
        self.assertIn("10:30", body,
                      "the new time is missing or not in studio time")

    def test_rescheduling_tells_her_by_both_channels_not_one(self):
        """The pair, asserted together, so a future change cannot quietly
        drop one of them and still look green."""
        event = self._event(days=3)
        a = self._student("res_both")
        booking = self._booked(a, event)
        self.env["fitness.notification"].sudo().search([]).unlink()
        self.env["mail.mail"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("res_id", "=", booking.id)]).unlink()

        new_start = fields.Datetime.now() + timedelta(days=5)
        event.write({"start": new_start,
                     "stop": new_start + timedelta(minutes=45)})

        self.assertTrue(self._bells(a, "class_rescheduled"), "no bell")
        self.assertTrue(self._emails_for(booking), "no email")

    def test_a_tiny_time_correction_does_not_alarm_anybody(self):
        """The guard is >60s, so fixing a typo in the minutes does not mail
        the whole class."""
        event = self._event(days=3)
        a = self._student("tiny")
        self._booked(a, event)
        self.env["fitness.notification"].sudo().search([]).unlink()

        booking = self.env["fitness.booking"].sudo().search(
            [("calendar_event_id", "=", event.id)], limit=1)
        self.env["mail.mail"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("res_id", "=", booking.id)]).unlink()

        event.write({"start": event.start + timedelta(seconds=30)})

        self.assertFalse(
            self._bells(a, "class_rescheduled"),
            "a 30-second correction told the student the class had moved")
        self.assertFalse(
            self._emails_for(booking),
            "a 30-second correction emailed the whole class")

    # ── 4. the studio moves one student to another class ────────────────────

    def test_moving_one_student_tells_her_and_only_her(self):
        origin = self._event(days=3)
        target = self._event(days=4)
        a, b = self._student("mv_a"), self._student("mv_b")
        ba = self._booked(a, origin)
        self._booked(b, origin)
        self.env["fitness.notification"].sudo().search([]).unlink()

        wizard = self.env["fitness.booking.reassign.wizard"].with_user(
            self.env.ref("base.user_admin")).create({
                "booking_id": ba.id,
                "target_event_id": target.id,
            })
        wizard.action_move_student()

        self.assertTrue(self._bells(a, "class_rescheduled"),
                        "the moved student was not told")
        self.assertTrue(self._emails_for(ba),
                        "the moved student got no email")
        self.assertFalse(
            self._bells(b, "class_rescheduled"),
            "a student who was not moved was told she had been")

    def test_the_moved_student_is_still_on_the_target_roster(self):
        """The 'no roster' complaint. The roster is booking-based, so a move
        that keeps the booking row must move the seat with it - the student
        should leave the old class's roster and appear on the new one."""
        origin = self._event(days=3)
        target = self._event(days=4)
        a = self._student("roster")
        ba = self._booked(a, origin)

        wizard = self.env["fitness.booking.reassign.wizard"].with_user(
            self.env.ref("base.user_admin")).create({
                "booking_id": ba.id,
                "target_event_id": target.id,
            })
        wizard.action_move_student()

        self.assertIn(ba, target.booking_ids,
                      "the moved student is missing from the new class roster")
        self.assertNotIn(ba, origin.booking_ids,
                         "the moved student is still on the old class roster")
        self.assertEqual(ba.state, "booked",
                         "the move left the booking in a non-booked state, "
                         "which is what would empty a roster")
