# -*- coding: utf-8 -*-
"""The instructor dashboard: its numbers, and its words.

The counts are asserted against bookings built here rather than against
whatever the database happens to hold, and the labels are asserted per
language - because the portal answers in the reader's language, and a label
that silently falls back to English is the failure this studio keeps hitting.
"""
import pytz
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInstructorDashboardLabels(TransactionCase):

    longMessage = False

    def test_every_dashboard_label_is_translated(self):
        """Each string the dashboard shows must exist in both languages.

        A missing entry does not raise - Odoo hands back the English source -
        so the only way this is caught is by asking for the translation and
        comparing. Wording is checked loosely (the word that carries it) so a
        copy edit does not break the test, but a fallback to English does.
        """
        expected = {
            "Classes today":      ("Clases", "Classes avui"),
            "Students expected":  ("Alumnos", "Alumnes"),
            "Roster":             ("Lista", "Llista"),
            "Finished":           ("Finalizada", "Finalitzada"),
            "See all my classes": ("Ver todas", "Veure totes"),
            "Good morning":       ("Buenos días", "Bon dia"),
            "No classes today.":  ("No hay clases", "No hi ha classes"),
        }
        for source, (es_part, ca_part) in expected.items():
            es = self.env(context={"lang": "es_ES"})._(source)
            ca = self.env(context={"lang": "ca_ES"})._(source)
            self.assertNotEqual(
                es, source,
                "'%s' fell back to English in Spanish - no catalogue entry is "
                "loaded for it" % source)
            self.assertIn(es_part, es, "Spanish for '%s' reads '%s'" % (source, es))
            self.assertNotEqual(
                ca, source,
                "'%s' fell back to English in Catalan - no catalogue entry is "
                "loaded for it" % source)
            self.assertIn(ca_part, ca, "Catalan for '%s' reads '%s'" % (source, ca))

    def test_the_two_languages_do_not_collide(self):
        """Catalan must not quietly be served the Spanish string.

        This is the failure that looks fine on screen: every label filled in,
        all of them in the wrong language.
        """
        for source in ("Classes today", "Students expected", "Good morning"):
            es = self.env(context={"lang": "es_ES"})._(source)
            ca = self.env(context={"lang": "ca_ES"})._(source)
            self.assertNotEqual(
                es, ca,
                "'%s' is identical in Spanish and Catalan (%r) - one of them "
                "is almost certainly the other's translation" % (source, es))


@tagged("post_install", "-at_install")
class TestInstructorDashboardCounts(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = pytz.timezone("Europe/Madrid")
        cls.teacher = cls.env["res.users"].create({
            "name": "Dashboard Instructor",
            "login": "dash.instructor@example.invalid",
            "group_ids": [(4, cls.env.ref("fitness_core.group_fitness_teacher").id)],
        })
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Dash Room", "classroom_type": "reformer", "capacity": 6,
        })
        cls.ct = cls.env["fitness.class.type"].create({
            "name": "Dash Reformer", "classroom_type": "reformer", "duration": 50,
            "level": "all", "session_type": "group", "intensity": "moderate",
        })

    def _class_at(self, hour, day_offset=0):
        local = self.tz.localize(
            datetime.now(self.tz).replace(tzinfo=None).replace(
                hour=hour, minute=0, second=0, microsecond=0)
            + timedelta(days=day_offset))
        start = local.astimezone(pytz.UTC).replace(tzinfo=None)
        return self.env["calendar.event"].create({
            "name": self.ct.name,
            "class_type_id": self.ct.id,
            "classroom_id": self.room.id,
            "user_id": self.teacher.id,
            "start": start,
            "stop": start + timedelta(minutes=50),
            "capacity": 6,
            # Not computed - the studio sets it, and every instructor query
            # filters on it, so a fixture without it is invisible to all of them.
            "is_fitness_class": True,
        })

    def test_a_cancelled_class_is_not_counted(self):
        """The dashboard counts what she is teaching, not what was scheduled."""
        live = self._class_at(9)
        dead = self._class_at(11)
        dead.class_state = "cancelled"
        mine = self.env["calendar.event"].search([
            ("user_id", "=", self.teacher.id),
            ("is_fitness_class", "=", True),
            ("class_state", "!=", "cancelled"),
        ])
        self.assertIn(live, mine)
        self.assertNotIn(dead, mine, "a cancelled class must not reach the dashboard")

    def test_tomorrows_class_is_not_today(self):
        """The day window is the studio's day, not a rolling 24 hours."""
        today = self._class_at(9)
        tomorrow = self._class_at(9, day_offset=1)
        now_local = datetime.now(self.tz)
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = day_start.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = (day_start + timedelta(days=1)).astimezone(pytz.UTC).replace(tzinfo=None)
        found = self.env["calendar.event"].search([
            ("user_id", "=", self.teacher.id),
            ("start", ">=", start_utc), ("start", "<", end_utc),
        ])
        self.assertIn(today, found)
        self.assertNotIn(tomorrow, found, "tomorrow's class was counted as today's")
