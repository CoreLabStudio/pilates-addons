# -*- coding: utf-8 -*-
"""The alert that fires when the timetable stops being generated.

Detection lives in fitness_core and is tested there. This is the other half:
that a stalled studio actually reaches a human, in their own language, once
rather than once per schedule - and that a healthy studio reaches nobody,
because an alert that fires on a working system is an alert that gets muted.
"""
from datetime import timedelta

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.fitness_core.models.fitness_class_schedule import WEEKDAYS
from odoo.addons.fitness_core.models.studio_time import studio_today

#: The schedule model's own codes, not a hand-written copy of them.
WEEKDAY_CODES = [code for code, _label in WEEKDAYS]

#: Far enough ahead that no hour of any day puts the first generated
#: class behind now. A named weekday starting today is a different
#: fixture depending on which day the suite runs on, and on that weekday
#: it depends on the hour as well.
FIXTURE_LEAD_DAYS = 2

#: The health check logs at ERROR when generation has stalled, which is the
#: right level for a studio whose timetable has stopped. These tests stall one
#: on purpose, so that ERROR is expected output - and odoo.sh reads an ERROR
#: line in a build log as a failed build. Muted here so a passing test cannot
#: paint the branch red, without softening what a real stall reports.
HEALTH_LOGGER = 'odoo.addons.fitness_core.models.fitness_class_schedule'


@tagged("post_install", "-at_install")
class TestGenerationAlert(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Schedule = cls.env["fitness.class.schedule"]
        cls.manager = cls.env["res.users"].create({
            "name": "Alert Manager",
            "login": "alert.manager@example.invalid",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        room = cls.env["fitness.classroom"].create({
            "name": "Room (alert test)", "classroom_type": "reformer", "capacity": 6})
        ctype = cls.env["fitness.class.type"].create({
            "name": "Reformer Sculpt (alert test)", "classroom_type": "reformer",
            "session_type": "group", "level": "all", "classroom_id": room.id})
        teacher = cls.env["res.users"].create({
            "name": "Alert Teacher", "login": "alert.teacher@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])]})
        cls.anchor = studio_today() + timedelta(days=FIXTURE_LEAD_DAYS)
        cls.sched = cls.Schedule.create({
            "class_type_id": ctype.id, "teacher_user_id": teacher.id,
            "classroom_id": room.id,
            # Derived from the anchor: this file is about schedules going
            # stale, not about which weekday they run on.
            "weekday": WEEKDAY_CODES[cls.anchor.weekday()],
            "start_time": 18.0,
            "duration": 1.0, "capacity": 6,
            "date_start": cls.anchor, "horizon_weeks": 8})
        cls.sched.action_generate()

    def _alerts(self):
        return self.env["fitness.notification"].sudo().search([
            ("notification_type", "=", "generation_stalled"),
            ("user_id", "=", self.manager.id),
        ])

    def _stall(self, sched=None):
        """Put a schedule well past the slack window, as a dead cron would."""
        sched = sched or self.sched
        sched.generated_until = sched._target_until() - timedelta(
            days=self.Schedule.GENERATION_SLACK_DAYS + 5)

    def _only_ours(self, *keep):
        """Make every other schedule healthy, so the alert is about ours.

        On a fresh install there are no others and this does nothing. On a
        copy of the live studio there are seventy-five, and every one of
        them is stale - the dump froze generated_until while _target_until()
        goes on moving with today's date. So the cron legitimately alerts
        about them, and these assertions, which are about THIS schedule,
        were being answered by somebody else's.

        That also made the alert body useless to the test: it names only the
        first ten stale rows, and ours was never among seventy-five.

        Writes are rolled back with the test like every other write here.
        Nothing in the production code changes - the health check was right
        both times, and it was the question that was badly posed.
        """
        keep_ids = [s.id for s in keep]
        others = self.Schedule.search([('active', '=', True),
                                       ('recurrence_id', '!=', False),
                                       ('id', 'not in', keep_ids)])
        for rec in others:
            rec.generated_until = rec._target_until()

    def test_a_healthy_studio_alerts_nobody(self):
        self._only_ours(self.sched)
        before = len(self._alerts())
        self.Schedule._cron_check_generation_health()
        self.assertEqual(len(self._alerts()), before,
                         "a working studio produced an alert")

    @mute_logger(HEALTH_LOGGER)
    def test_a_stalled_studio_reaches_a_manager(self):
        self._only_ours(self.sched)
        before = len(self._alerts())
        self._stall()
        self.Schedule._cron_check_generation_health()

        alerts = self._alerts()
        self.assertEqual(len(alerts), before + 1,
                         "generation stalled and nobody was told")
        alert = alerts.sorted("id")[-1]
        self.assertIn("scheduled", alert.title.lower())
        # The body has to be actionable: which rows, and what it costs.
        self.assertIn(self.sched.name, alert.body,
                      "the alert does not say which schedule stalled")
        self.assertIn("renew", alert.body.lower(),
                      "the alert does not say what it breaks")

    @mute_logger(HEALTH_LOGGER)
    def test_many_stalled_schedules_are_one_alert_not_many(self):
        """Twelve rows going stale is one fault, and twelve alerts mute it."""
        others = self.Schedule.browse()
        # Three weekdays that are not the main schedule's, derived from
        # the same anchor so they stay distinct from it on any day of
        # the week.
        for offset in (1, 2, 3):
            day_start = self.anchor + timedelta(days=offset)
            s = self.Schedule.create({
                "class_type_id": self.sched.class_type_id.id,
                "teacher_user_id": self.sched.teacher_user_id.id,
                "classroom_id": self.sched.classroom_id.id,
                "weekday": WEEKDAY_CODES[day_start.weekday()],
                "start_time": 18.0, "duration": 1.0,
                "capacity": 6, "date_start": day_start,
                "horizon_weeks": 8})
            s.action_generate()
            others |= s

        before = len(self._alerts())
        self._stall()
        for s in others:
            self._stall(s)
        self.Schedule._cron_check_generation_health()

        self.assertEqual(len(self._alerts()), before + 1,
                         "one stalled studio produced more than one alert")

    @mute_logger(HEALTH_LOGGER)
    def test_the_alert_is_written_in_the_managers_language(self):
        es = self.env["res.lang"]._activate_lang("es_ES")
        if not es:
            self.skipTest("Spanish not installed in this database")
        self.manager.lang = "es_ES"
        self._stall()
        self.Schedule._cron_check_generation_health()

        alert = self._alerts().sorted("id")[-1]
        self.assertNotIn("Classes are no longer being scheduled", alert.title,
                         "the alert reached a Spanish manager in English")
