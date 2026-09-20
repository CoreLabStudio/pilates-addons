# -*- coding: utf-8 -*-
"""The alert that fires when the timetable stops being generated.

Detection lives in fitness_core and is tested there. This is the other half:
that a stalled studio actually reaches a human, in their own language, once
rather than once per schedule - and that a healthy studio reaches nobody,
because an alert that fires on a working system is an alert that gets muted.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


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
        cls.sched = cls.Schedule.create({
            "class_type_id": ctype.id, "teacher_user_id": teacher.id,
            "classroom_id": room.id, "weekday": "wed", "start_time": 18.0,
            "duration": 1.0, "capacity": 6,
            "date_start": fields.Date.today(), "horizon_weeks": 8})
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

    def test_a_healthy_studio_alerts_nobody(self):
        before = len(self._alerts())
        self.Schedule._cron_check_generation_health()
        self.assertEqual(len(self._alerts()), before,
                         "a working studio produced an alert")

    def test_a_stalled_studio_reaches_a_manager(self):
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

    def test_many_stalled_schedules_are_one_alert_not_many(self):
        """Twelve rows going stale is one fault, and twelve alerts mute it."""
        others = self.Schedule.browse()
        for day in ("mon", "tue", "thu"):
            s = self.Schedule.create({
                "class_type_id": self.sched.class_type_id.id,
                "teacher_user_id": self.sched.teacher_user_id.id,
                "classroom_id": self.sched.classroom_id.id,
                "weekday": day, "start_time": 18.0, "duration": 1.0,
                "capacity": 6, "date_start": fields.Date.today(),
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
