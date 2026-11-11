# -*- coding: utf-8 -*-
"""A renamed class type reaches its timetable slots and the weeks the night job adds.

Two places kept the old name after a class type was renamed:

* the slot's stored name ("Barre Pump it — Monday 18:00") recomputed only
  when the slot itself changed, not when its class type was renamed;
* the nightly job extends a slot by copying the series' first class, so new
  weeks came out under the old name - the same fault the teacher had.

What must not change: classes already on the calendar. Renaming those is the
studio's own step (the apply script), so a class somebody is booked into
keeps its name until then, and the past stays as it was taught.

The clock is pinned to a Wednesday in November, away from a clock change.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

from odoo.addons.fitness_core.models.fitness_class_schedule import WEEKDAYS
from odoo.addons.fitness_core.models.studio_time import studio_today

WEEKDAY_CODES = [code for code, _label in WEEKDAYS]
NOW = datetime(2026, 11, 11, 9, 0, 0)        # Wednesday, 10:00 Madrid
PAST_DAYS = 21


@tagged("post_install", "-at_install")
class TestClassTypeRenameReachesSlots(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(NOW)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        teacher = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Rename Teacher", "login": "rename.teacher@example.invalid", "lang": "en_US",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id,
                                  self.env.ref("fitness_core.group_fitness_teacher").id])]})
        room = self.env["fitness.classroom"].create({
            "name": "Rename Room", "classroom_type": "barre", "capacity": 8})
        self.ctype = self.env["fitness.class.type"].create({
            "name": "Barre Pump it", "classroom_type": "barre",
            "session_type": "group", "level": "all", "classroom_id": room.id})
        start = studio_today() - timedelta(days=PAST_DAYS)
        self.sched = self.env["fitness.class.schedule"].create({
            "class_type_id": self.ctype.id, "classroom_id": room.id, "teacher_user_id": teacher.id,
            "weekday": WEEKDAY_CODES[start.weekday()], "start_time": 18.0,
            "duration": 1.0, "capacity": 8, "date_start": start, "horizon_weeks": 2})
        self.sched.action_generate()
        Event = self.env["calendar.event"].with_context(active_test=False)
        self.series = lambda: Event.search([("recurrence_id", "=", self.sched.recurrence_id.id)])
        self.before = self.series()
        self.assertTrue(self.before, "fixture: the slot generated nothing")

    def test_the_slot_name_follows_a_rename(self):
        self.assertTrue(self.sched.name.startswith("Barre Pump it"), self.sched.name)
        self.ctype.name = "Barre Core"
        self.env.flush_all()
        self.sched.invalidate_recordset(["name"])
        self.assertTrue(self.sched.name.startswith("Barre Core"),
                        "the slot kept the old name after the rename: %r" % self.sched.name)

    def test_new_weeks_take_the_class_type_name(self):
        self.ctype.name = "Barre Core"
        self.sched.horizon_weeks = 4
        self.sched._extend()
        new = self.series() - self.before
        self.assertTrue(new, "fixture: the job generated nothing")
        self.assertEqual(set(new.mapped("name")), {"Barre Core"},
                         "weeks generated after the rename came out as %s"
                         % sorted(set(new.mapped("name"))))

    def test_classes_already_on_the_calendar_keep_their_name(self):
        self.ctype.name = "Barre Core"
        self.sched.horizon_weeks = 4
        self.sched._extend()
        self.before.invalidate_recordset(["name"])
        self.assertEqual(set(self.before.mapped("name")), {"Barre Pump it"},
                         "the job renamed classes already on the calendar")

    def test_the_nightly_job_does_it_too(self):
        self.ctype.name = "Barre Core"
        self.sched.horizon_weeks = 4
        self.env["fitness.class.schedule"]._cron_extend_schedules()
        new = self.series() - self.before
        self.assertTrue(new, "fixture: the nightly job generated nothing")
        self.assertEqual(set(new.mapped("name")), {"Barre Core"})
