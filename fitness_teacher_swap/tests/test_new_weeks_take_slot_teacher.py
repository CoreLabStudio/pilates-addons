# -*- coding: utf-8 -*-
"""A slot handed to another teacher generates its new weeks for her.

The nightly job extends each weekly slot by copying the series' first class,
and that class is in the past. So when the studio moved a slot to Naivi -
the slot and every class already on the calendar - the next weeks still came
out for the old teacher, one day at a time, five weeks ahead.

The fix takes the teacher from the slot. What it must not do is reach back:
the classes already taught stay with whoever taught them (the hours report
reads them), and a class somebody is booked into is not touched by the job.
"""
from datetime import timedelta

from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_core.models.fitness_class_schedule import WEEKDAYS
from odoo.addons.fitness_core.models.studio_time import studio_today

WEEKDAY_CODES = [code for code, _label in WEEKDAYS]

#: Three weeks back, so the series has a first class and two more behind now.
PAST_DAYS = 21


@tagged("post_install", "-at_install")
class TestNewWeeksTakeSlotTeacher(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref("base.group_portal").id
        teacher = cls.env.ref("fitness_core.group_fitness_teacher").id
        student = cls.env.ref("fitness_core.group_fitness_student").id
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.old = Users.create({
            "name": "Slot Old Teacher", "login": "slot.old@example.invalid",
            "lang": "en_US", "group_ids": [(6, 0, [portal, teacher])]})
        cls.naivi = Users.create({
            "name": "Slot Naivi", "login": "slot.naivi@example.invalid",
            "lang": "en_US", "group_ids": [(6, 0, [portal, teacher])]})
        cls.student = Users.create({
            "name": "Slot Student", "login": "slot.student@example.invalid",
            "lang": "en_US", "group_ids": [(6, 0, [portal, student])]})
        room = cls.env["fitness.classroom"].create({
            "name": "Slot Room", "classroom_type": "barre", "capacity": 8})
        ctype = cls.env["fitness.class.type"].create({
            "name": "Slot Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all", "classroom_id": room.id})
        cls.pack = cls.env["product.template"].create({
            "name": "Slot Pack", "type": "service", "list_price": 100.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 20, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        start = studio_today() - timedelta(days=PAST_DAYS)
        cls.sched = cls.env["fitness.class.schedule"].create({
            "class_type_id": ctype.id, "teacher_user_id": cls.old.id,
            "classroom_id": room.id, "weekday": WEEKDAY_CODES[start.weekday()],
            "start_time": 9.0, "duration": 1.0, "capacity": 8,
            "date_start": start, "horizon_weeks": 2})
        cls.sched.action_generate()

    def setUp(self):
        super().setUp()
        Event = self.env["calendar.event"].with_context(active_test=False)
        self.series = lambda: Event.search(
            [("recurrence_id", "=", self.sched.recurrence_id.id)])
        self.before = self.series()
        self.past = self.before.filtered(lambda e: e.start.date() < studio_today())
        self.booked_class = self.sched._future_occurrences().sorted("start")[:1]
        self.assertTrue(self.past and self.booked_class,
                        "fixture drifted: the series needs past and future classes")

        order = self.env["sale.order"].sudo().create(
            {"partner_id": self.student.partner_id.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0})
        order.action_confirm()
        self.booking = self.env["fitness.booking"].sudo().with_context(
            _fitness_clase_fija_placement=True).create({
                "student_id": self.student.partner_id.id,
                "calendar_event_id": self.booked_class.id,
                "package_order_line_id": order.order_line[:1].id})

        # The studio hands the slot over; the job runs on a later night.
        self.sched.teacher_user_id = self.naivi
        self.sched.horizon_weeks = 4
        self.sched._extend()
        self.new = self.series() - self.before

    def test_a_new_week_gets_the_slot_teacher(self):
        self.assertTrue(self.new, "fixture drifted: the job generated nothing")
        self.assertEqual(
            self.new.mapped("user_id"), self.naivi,
            "a week generated after the handover went to %s, not to the slot's "
            "teacher" % ", ".join(self.new.mapped("user_id.name")))

    def test_a_past_class_keeps_its_teacher(self):
        self.assertIn(self.sched.recurrence_id.base_event_id, self.past,
                      "fixture drifted: the series' first class should be past")
        self.assertEqual(
            self.past.mapped("user_id"), self.old,
            "a class already taught was rewritten to another teacher")

    def test_a_booked_class_is_left_alone(self):
        self.assertTrue(self.booked_class.active)
        self.assertEqual(self.booked_class.user_id, self.old,
                         "the job changed the teacher of a class already on the calendar")
        self.assertEqual(self.booking.calendar_event_id, self.booked_class)
        self.assertEqual(self.booking.state, "booked")
