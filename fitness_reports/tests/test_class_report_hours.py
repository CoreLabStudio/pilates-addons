# -*- coding: utf-8 -*-
"""Classes taught per instructor: which classes count, and for how long.

The report could already be grouped by instructor and month. What it could
not do was answer the question the studio actually asks, because it
counted the wrong rows:

  * archived classes were included. The view is raw SQL, so Odoo's
    active_test never reached it. On the production restore it returned
    959 rows of which 404 were archived - 42% of every figure anybody
    read off it;
  * cancelled classes were included, and so were classes still in the
    future, so "classes taught this month" counted next week's timetable;
  * and there were no hours at all, only a count of classes.

These pin where each kind of class lands, one test each, because the
difference between them is the whole point of the change. A class that
ran with nobody in it counts: the instructor was there.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestClassReportHours(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Report Room", "classroom_type": "barre", "capacity": 10,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Report Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Report Teacher",
                "login": "report.teacher@example.invalid",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            })
        cls.other_teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Report Other Teacher",
                "login": "report.other@example.invalid",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            })

    # ── fixtures ────────────────────────────────────────────────────────────

    def _class(self, days_offset, hours=1.0, cancelled=False,
               archived=False, teacher=None, name=None):
        """One class, placed before or after now by days_offset."""
        start = (fields.Datetime.now() + timedelta(days=days_offset)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        vals = {
            "name": name or "Report class %+d" % days_offset,
            "start": start,
            "stop": start + timedelta(hours=hours),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
            "capacity": 10,
            "user_id": (teacher or self.teacher).id,
        }
        if cancelled:
            vals["class_state"] = "cancelled"
        event = self.env["calendar.event"].sudo().create(vals)
        if archived:
            event.active = False
        self.env.flush_all()
        return event

    def _rows(self, event):
        """The report rows for one class. Empty means it is not in the view."""
        self.env.flush_all()
        return self.env["fitness.report.class"].sudo().search(
            [("event_id", "=", event.id)])

    # ── where each kind of class lands ──────────────────────────────────────

    def test_a_class_that_ran_is_in_the_report_and_marked_as_run(self):
        event = self._class(-7)
        rows = self._rows(event)
        self.assertEqual(len(rows), 1, "a finished class is not in the report")
        self.assertTrue(
            rows.did_run, "a finished, uncancelled class is not marked as run")
        self.assertEqual(
            rows.teacher_user_id, self.teacher,
            "the class is credited to the wrong instructor")

    def test_a_future_class_is_present_but_not_marked_as_run(self):
        """It has to stay visible - the timetable is worth looking at - but
        it must not count towards classes taught."""
        event = self._class(+7)
        rows = self._rows(event)
        self.assertEqual(len(rows), 1, "the future class vanished entirely")
        self.assertFalse(
            rows.did_run,
            "a class that has not happened yet counts as taught, so this "
            "month's figure includes next week")

    def test_a_cancelled_class_is_present_but_not_marked_as_run(self):
        event = self._class(-7, cancelled=True)
        rows = self._rows(event)
        self.assertEqual(len(rows), 1, "the cancelled class vanished entirely")
        self.assertEqual(rows.class_state, "cancelled")
        self.assertFalse(
            rows.did_run,
            "a class the studio cancelled counts as taught")

    def test_an_archived_class_is_not_in_the_report_at_all(self):
        """Not merely unmarked - gone. Nobody taught it, and it was 42% of
        the rows on the production restore."""
        event = self._class(-7, archived=True)
        self.assertFalse(
            self._rows(event),
            "an archived class is still counted; raw SQL does not apply "
            "active_test, so it has to be excluded in the WHERE clause")

    def test_a_class_that_ran_with_nobody_in_it_still_counts(self):
        event = self._class(-7, name="Report empty class")
        rows = self._rows(event)
        self.assertEqual(rows.booked_count, 0, "fixture wrong: not empty")
        self.assertTrue(
            rows.did_run,
            "a class nobody booked did not count - the instructor was there "
            "and should be paid for it")

    # ── counted once, and for the right length ──────────────────────────────

    def test_a_class_counts_once_under_the_instructor_who_taught_it(self):
        mine = self._class(-7, teacher=self.teacher)
        theirs = self._class(-6, teacher=self.other_teacher)
        self.env.flush_all()

        Report = self.env["fitness.report.class"].sudo()
        hers = Report.search([
            ("teacher_user_id", "=", self.teacher.id),
            ("event_id", "in", (mine | theirs).ids),
        ])
        self.assertEqual(
            len(hers), 1,
            "her class is counted %d times, or somebody else's is on her "
            "row" % len(hers))
        self.assertEqual(hers.event_id, mine)

    def test_hours_come_from_the_scheduled_span(self):
        event = self._class(-7, hours=1.5)
        rows = self._rows(event)
        self.assertAlmostEqual(
            rows.duration_hours, 1.5, places=2,
            msg="a 90 minute class reports %s hours" % rows.duration_hours)

    def test_hours_add_up_across_a_month_for_one_instructor(self):
        """The measure is a sum, which is the whole reason it exists."""
        a = self._class(-7, hours=1.0, teacher=self.other_teacher)
        b = self._class(-6, hours=0.75, teacher=self.other_teacher)
        skipped = self._class(-5, hours=2.0, teacher=self.other_teacher,
                              cancelled=True)
        self.env.flush_all()

        Report = self.env["fitness.report.class"].sudo()
        ran = Report.search([
            ("teacher_user_id", "=", self.other_teacher.id),
            ("event_id", "in", (a | b | skipped).ids),
            ("did_run", "=", True),
        ])
        self.assertEqual(
            len(ran), 2, "the cancelled class is in the ran total")
        self.assertAlmostEqual(
            sum(ran.mapped("duration_hours")), 1.75, places=2,
            msg="hours for the month came to %s, expected 1.75"
                % sum(ran.mapped("duration_hours")))
