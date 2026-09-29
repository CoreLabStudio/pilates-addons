# -*- coding: utf-8 -*-
"""Both routes tell the incoming instructor, and both record who did it.

A class's instructor can change two ways, and they behaved differently in
ways nobody chose:

  editing the Organizer in the back office told the new instructor,
  through the write() hook;

  the swap screen - two instructors arranging a handover between
  themselves - did not. It writes under skip_fitness_notification=True
  and sends its own notifications, and its own set left her out. So the
  students heard, and the person who now has to teach the class did not.

Whichever route somebody happened to use decided whether she was told,
which is why it stayed invisible.

And the swap record said what KIND of change it was - initiated_by
'admin' or 'teacher' - but on the admin path that is a label, not a
person. A swap made from the back office recorded that somebody with
rights did it, never which somebody.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSwapTellsTheNewInstructor(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        portal = cls.env.ref("base.group_portal").id
        teacher = cls.env.ref("fitness_core.group_fitness_teacher").id
        cls.teacher_a = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Swap Notify A", "login": "swapnotify.a@example.invalid",
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.teacher_b = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Swap Notify B", "login": "swapnotify.b@example.invalid",
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Swap Notify Manager",
                "login": "swapnotify.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id])]})
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Swap Notify Room", "classroom_type": "barre",
            "capacity": 8})
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Swap Notify Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id})

    def _class(self, tag, teacher=None, days=4):
        """A class shaped like a real one: no attendees.

        fitness_core's create() clears partner_ids on every fitness class,
        so a class HAS no calendar attendees however it is made - the
        roster is fitness.booking. Passing them here would be discarded,
        and the production database bears it out: 959 fitness classes,
        nought attendee rows.

        What lets the instructor read her own class is
        fitness_core.rule_fitness_teacher_calendar_event, which is why
        these tests need it and why it is now in the repository.
        """
        who = teacher or self.teacher_a
        start = (fields.Datetime.now() + timedelta(days=days)).replace(
            hour=18, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": "Swap notify %s" % tag,
            "start": start, "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id, "is_fitness_class": True,
            "capacity": 8, "user_id": who.id})

    def _notifs_for(self, user, since_id=0):
        return self.env["fitness.notification"].sudo().search([
            ("user_id", "=", user.id),
            ("notification_type", "=", "teacher_swap"),
            ("id", ">", since_id),
        ])

    def _latest_notif_id(self):
        last = self.env["fitness.notification"].sudo().search(
            [], order="id desc", limit=1)
        return last.id if last else 0

    def _swaps_for(self, event):
        return self.env["fitness.teacher.swap"].sudo().search(
            [("calendar_event_id", "=", event.id)])

    # ── the gap this closes ─────────────────────────────────────────────────

    def test_the_swap_screen_now_tells_the_incoming_instructor(self):
        event = self._class("swaproute")
        mark = self._latest_notif_id()

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id, reason="Dentist")
        self.env.invalidate_all()

        told = self._notifs_for(self.teacher_b, mark)
        self.assertEqual(
            len(told), 1,
            "the incoming instructor was told %d times; a handover between "
            "two instructors reached the students and not her" % len(told))
        self.assertIn(
            "Swap notify swaproute", told.title or "",
            "the notification does not name the class she has been given")

    def test_the_direct_write_still_tells_her_exactly_once(self):
        """It already did. It must not now do it twice."""
        event = self._class("writeroute")
        mark = self._latest_notif_id()

        event.sudo().write({"user_id": self.teacher_b.id})
        self.env.invalidate_all()

        told = self._notifs_for(self.teacher_b, mark)
        self.assertEqual(
            len(told), 1,
            "the back-office route now tells her %d times" % len(told))

    # ── who made the change ─────────────────────────────────────────────────

    def test_the_swap_route_records_who_and_why(self):
        event = self._class("whoswap")
        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id, reason="Family thing")
        self.env.invalidate_all()

        swap = self._swaps_for(event)
        self.assertEqual(len(swap), 1, "expected one swap record")
        self.assertEqual(
            swap.changed_by_id, self.teacher_a,
            "the swap does not record which account made it")
        self.assertEqual(swap.initiated_by, "teacher")
        self.assertEqual(
            swap.reason, "Family thing",
            "the reason typed on the swap screen was lost")

    def test_the_direct_write_records_who_made_it(self):
        event = self._class("whowrite")
        event.with_user(self.manager).write({"user_id": self.teacher_b.id})
        self.env.invalidate_all()

        swap = self._swaps_for(event)
        self.assertEqual(len(swap), 1, "expected one swap record")
        self.assertEqual(
            swap.changed_by_id, self.manager,
            "'admin' says what kind of change it was, not which person - "
            "and that was all there was")
        self.assertEqual(swap.initiated_by, "admin")

    # ── what must not have changed ──────────────────────────────────────────

    def test_the_outgoing_instructor_loses_the_class(self):
        event = self._class("access")
        self.assertEqual(event.user_id, self.teacher_a, "fixture wrong")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id, reason="Handover")
        self.env.invalidate_all()

        self.assertEqual(
            event.user_id, self.teacher_b,
            "the class did not move to the new instructor")
        self.assertNotEqual(
            event.user_id, self.teacher_a,
            "the outgoing instructor still owns it, so she keeps the "
            "roster at /my/instructor")

    def test_the_students_are_still_told(self):
        """Telling her must not have replaced telling them."""
        student = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Swap Notify Student",
                "login": "swapnotify.stu@example.invalid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id])]})
        pack = self.env["product.template"].create({
            "name": "Swap Notify Pack", "type": "service",
            "list_price": 100.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 10, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        event = self._class("students")
        order = self.env["sale.order"].sudo().create(
            {"partner_id": student.partner_id.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0})
        order.action_confirm()
        self.env["fitness.booking"].sudo().with_context(
            _fitness_clase_fija_placement=True).create({
                "student_id": student.partner_id.id,
                "calendar_event_id": event.id,
                "package_order_line_id": order.order_line[:1].id})
        self.env.invalidate_all()
        mark = self._latest_notif_id()

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id, reason="Cover")
        self.env.invalidate_all()

        self.assertEqual(
            len(self._notifs_for(student, mark)), 1,
            "the student booked into the class was not told her instructor "
            "changed")
        self.assertEqual(
            len(self._notifs_for(self.teacher_b, mark)), 1,
            "and the incoming instructor should still be told once")
