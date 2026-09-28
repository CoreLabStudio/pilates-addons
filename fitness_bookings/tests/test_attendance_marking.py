# -*- coding: utf-8 -*-
"""Marking attendance: who may, and what the seat counter does about it.

Three things were true before this, and each was invisible from a screen:

  * there was no way to mark attendance from the back office at all. The
    Roster is readonly with only a Cancel/Move button, the booking form's
    statusbar is not clickable (the widget disables itself unless the
    clickable option is set, and it is not), and there is no list action.
    The only route was the instructor portal, which requires being the
    teacher the class is assigned to - so a manager could not correct a
    booking left on 'booked' from 18 September;

  * a state written any other way - an import, an RPC call, a server
    action - did not move the seat. booked_seats counts booked and
    attended, so no_show frees a seat and nothing recounted it. The same
    drift the calendar_event_id fix dealt with, by a different door;

  * and a student could mark herself. She has write access to her own
    booking, because that is how cancelling works, and nothing in the
    method asked who was calling. No screen offered it; a screen is not a
    permission.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttendanceMarking(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Attend Room", "classroom_type": "barre", "capacity": 10,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Attend Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Attend Teacher",
                "login": "attend.teacher@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Attend Manager",
                "login": "attend.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Attend Student",
                "login": "attend.student@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.student.partner_id
        cls.pack = cls.env["product.template"].create({
            "name": "Attend Pack", "type": "service", "list_price": 100.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 10, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })

    def setUp(self):
        super().setUp()
        self.env.invalidate_all()

    # ── fixtures ────────────────────────────────────────────────────────────

    def _event(self, days_offset=-2):
        """A class, by default one that has already happened."""
        start = (fields.Datetime.now() + timedelta(days=days_offset)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": "Attend class %+d" % days_offset,
            "start": start,
            "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True, "capacity": 10,
            "user_id": self.teacher.id,
        })

    def _booking(self, event):
        order = self.env["sale.order"].sudo().create(
            {"partner_id": self.partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0,
        })
        order.action_confirm()
        booking = self.env["fitness.booking"].sudo().with_context(
            _fitness_clase_fija_placement=True).create({
                "student_id": self.partner.id,
                "calendar_event_id": event.id,
                "package_order_line_id": order.order_line[:1].id,
            })
        booking._refresh_booked_seats()
        self.env.invalidate_all()
        return booking

    def _seats(self, event):
        event.invalidate_recordset(["booked_seats"])
        return event.booked_seats

    # ── the seat counter ────────────────────────────────────────────────────

    def test_booked_to_no_show_frees_the_seat(self):
        event = self._event()
        booking = self._booking(event)
        self.assertEqual(self._seats(event), 1, "fixture wrong")

        booking.with_user(self.manager).action_mark_no_show()
        self.env.invalidate_all()

        self.assertEqual(
            self._seats(event), 0,
            "a no-show kept its seat, so the class reads fuller than it is")

    def test_no_show_back_to_booked_takes_the_seat_again(self):
        """The other direction, which a correction takes."""
        event = self._event()
        booking = self._booking(event)
        booking.with_user(self.manager).action_mark_no_show()
        self.env.invalidate_all()
        self.assertEqual(self._seats(event), 0, "fixture wrong")

        booking.sudo().write({"state": "booked"})
        self.env.invalidate_all()

        self.assertEqual(
            self._seats(event), 1,
            "putting a no-show back did not reclaim the seat")

    def test_marking_attended_leaves_the_count_alone(self):
        """attended is counted as occupying a seat, so nothing moves."""
        event = self._event()
        booking = self._booking(event)
        self.assertEqual(self._seats(event), 1, "fixture wrong")

        booking.with_user(self.manager).action_mark_attended()
        self.env.invalidate_all()

        self.assertEqual(
            self._seats(event), 1,
            "marking somebody present changed the seat count")

    def test_a_plain_write_recounts_too(self):
        """An import or an RPC call never touches the action methods."""
        event = self._event()
        booking = self._booking(event)
        self.assertEqual(self._seats(event), 1, "fixture wrong")

        booking.sudo().write({"state": "no_show"})
        self.env.invalidate_all()

        self.assertEqual(
            self._seats(event), 0,
            "a state written directly left the seat counter behind - the "
            "same drift a typed calendar_event_id used to cause")

    # ── who and when ────────────────────────────────────────────────────────

    def test_the_buttons_record_who_marked_and_when(self):
        event = self._event()
        booking = self._booking(event)
        before = fields.Datetime.now()

        booking.with_user(self.manager).action_mark_attended()
        self.env.invalidate_all()

        self.assertEqual(booking.state, "attended")
        self.assertEqual(
            booking.marked_by_id, self.manager,
            "nothing records who marked it")
        self.assertTrue(
            booking.marked_date and booking.marked_date >= before,
            "nothing records when it was marked")

    # ── the past booking a manager has to fix ───────────────────────────────

    def test_a_manager_can_fix_a_booking_from_weeks_ago(self):
        """The 18 September case: still 'booked' long after the class ran."""
        event = self._event(days_offset=-10)
        booking = self._booking(event)

        booking.with_user(self.manager).action_mark_attended()
        self.env.invalidate_all()

        self.assertEqual(
            booking.state, "attended",
            "a manager cannot correct a booking after the fact, so the "
            "roster stays wrong forever")

    def test_the_form_and_the_roster_both_offer_the_buttons(self):
        """The methods existed and nothing in the back office called them."""
        form = self.env["fitness.booking"].with_user(
            self.manager).get_view(view_type="form")["arch"]
        self.assertIn("action_mark_attended", form)
        self.assertIn("action_mark_no_show", form)

        roster = self.env["calendar.event"].with_user(
            self.manager).get_view(view_type="form")["arch"]
        self.assertIn(
            "action_mark_attended", roster,
            "the class Roster still has no way to mark anybody")

    # ── who may not ─────────────────────────────────────────────────────────

    def test_a_student_cannot_mark_her_own_booking(self):
        """She has write access to it - that is how cancelling works."""
        event = self._event()
        booking = self._booking(event)

        with self.assertRaises(UserError):
            booking.with_user(self.student).action_mark_attended()
        with self.assertRaises(UserError):
            booking.with_user(self.student).action_mark_no_show()

        self.env.invalidate_all()
        self.assertEqual(
            booking.state, "booked",
            "she marked herself present")

    def test_the_instructor_whose_class_it_is_may_still_mark(self):
        """The negative of the above: the guard must not break the portal,
        where attendance is actually taken."""
        event = self._event()
        booking = self._booking(event)

        booking.with_user(self.teacher).action_mark_attended()
        self.env.invalidate_all()

        self.assertEqual(
            booking.state, "attended",
            "the instructor can no longer mark her own class, which is the "
            "one screen that ever could")
