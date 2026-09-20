# -*- coding: utf-8 -*-
"""Telling one class from another, and opening on the right tab.

Two problems that only show up on a real screen:

  * A fitness class is named after its class type, and the timetable runs the
    same handful of names every weekday. In the "Move to" picker that came out
    as sixteen consecutive rows reading "Barre Pump it", "Barre Groove",
    "Barre Harmony", "Barre Pump it" - different classes on different days,
    identical on screen. On a phone, where the list is the whole interface,
    the right one could only be found by counting.

  * The class form opened on Notes. Opening a class from the Schedule is
    nearly always about who is in it, so every visit began with a tab nobody
    wanted.
"""
import pytz

from odoo import fields
from odoo.tests import TransactionCase, tagged

STUDIO_TZ = pytz.timezone('Europe/Madrid')


@tagged("post_install", "-at_install")
class TestClassNaming(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Room (naming test)", "classroom_type": "barre", "capacity": 7})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Barre Pump it (naming test)", "classroom_type": "barre",
            "session_type": "group", "level": "all", "classroom_id": cls.room.id})

    def _event(self, when):
        return self.env["calendar.event"].create({
            "name": "Barre Pump it (naming test)",
            "start": when, "stop": when,
            "is_fitness_class": True,
            "class_type_id": self.ctype.id,
        })

    def test_two_classes_with_the_same_name_are_told_apart(self):
        """The whole point: identical names, different days, must differ."""
        a = self._event("2026-10-05 07:00:00")   # Monday
        b = self._event("2026-10-07 07:00:00")   # Wednesday
        self.assertNotEqual(
            a.display_name, b.display_name,
            "two classes on different days are indistinguishable in a picker")

    def test_the_name_carries_the_studio_day_and_time(self):
        ev = self._event("2026-10-07 16:00:00")  # 18:00 in Madrid, CEST
        local = pytz.utc.localize(ev.start).astimezone(STUDIO_TZ)
        self.assertIn(local.strftime("%H:%M"), ev.display_name,
                      "the class name does not say what time it runs: %s"
                      % ev.display_name)
        self.assertIn("18:00", ev.display_name,
                      "named in UTC rather than the studio's clock: %s"
                      % ev.display_name)
        self.assertIn(local.strftime("%a"), ev.display_name,
                      "the class name does not say which day: %s" % ev.display_name)

    def test_an_ordinary_meeting_keeps_odoo_s_own_name(self):
        """Only fitness classes are renamed; nothing else is touched."""
        meeting = self.env["calendar.event"].create({
            "name": "Quarterly review",
            "start": "2026-10-07 09:00:00", "stop": "2026-10-07 10:00:00",
        })
        self.assertEqual(meeting.display_name, "Quarterly review",
                         "a plain calendar meeting was renamed")

    def test_a_class_with_no_start_does_not_break(self):
        """Defensive: naming must not raise on a half-built record."""
        ev = self.env["calendar.event"].create({
            "name": "Unscheduled class", "is_fitness_class": True,
            "class_type_id": self.ctype.id,
            "start": "2026-10-07 07:00:00", "stop": "2026-10-07 08:00:00",
        })
        ev.invalidate_recordset()
        self.assertTrue(ev.display_name, "display_name came back empty")


@tagged("post_install", "-at_install")
class TestRosterTabOrder(TransactionCase):

    longMessage = False

    def test_roster_is_the_first_tab_on_a_class(self):
        """Asserted on the arch the client actually renders, as a manager.

        Reading the inheriting view's own XML would only prove what we wrote;
        this asks Odoo for the combined result, which is what somebody opening
        a class really sees.

        It has to run as a manager. The Roster page carries
        groups="fitness_core.group_fitness_manager", and Odoo strips a page
        whose group the reader lacks before returning the arch - so asking as
        an ordinary user gets an answer with no Roster in it at all, which
        reads exactly like the reorder having failed.
        """
        from lxml import etree
        manager = self.env["res.users"].create({
            "name": "Roster Tab Probe",
            "login": "roster.tab.probe@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_manager").id])],
        })
        view = self.env.ref("calendar.view_calendar_event_form")
        arch = self.env["calendar.event"].with_user(manager).get_view(
            view.id, "form")["arch"]
        names = [p.get("name") or p.get("string")
                 for p in etree.fromstring(arch).xpath("//notebook/page")]
        self.assertIn("fitness_roster", names,
                      "the Roster tab is not on the class form at all")
        self.assertEqual(
            names[0], "fitness_roster",
            "Roster is not the first tab; the form opens on %r instead" % names[0])
