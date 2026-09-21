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
from datetime import timedelta

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


@tagged("post_install", "-at_install")
class TestNoPhantomAttendees(TransactionCase):
    """A fitness class has no calendar attendees. The roster is the list.

    calendar.event.partner_ids defaults to the creating user's partner, so
    every class the nightly cron generated carried OdooBot - and the form
    header counts that field, not the roster. Yoleyva reported a class
    showing "1 person" with nobody in it on 2026-09-21 and was right: 456
    classes carried OdooBot, and one pattern's phantom was inherited by every
    occurrence it generated, because occurrences are built from the base
    event's copy_data().

    The header was not merely counting the wrong thing - it was arithmetic
    nonsense, reporting "-1 Awaiting" on the same class.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Phantom room", "classroom_type": "barre", "capacity": 9})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Phantom Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})

    def test_a_fitness_class_is_created_with_no_attendees(self):
        start = fields.Datetime.now() + timedelta(days=5)
        event = self.env["calendar.event"].create({
            "name": "Phantom probe", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True})
        self.assertFalse(
            event.partner_ids,
            "a fitness class was created carrying calendar attendees: %s"
            % event.partner_ids.mapped("display_name"))
        self.assertFalse(
            event.attendee_ids,
            "a fitness class was created with calendar.attendee rows, which "
            "is what the form header counts as guests")

    def test_an_ordinary_meeting_still_gets_its_attendee(self):
        """Only classes are stripped. Odoo's own behaviour is untouched."""
        start = fields.Datetime.now() + timedelta(days=5)
        meeting = self.env["calendar.event"].create({
            "name": "Ordinary meeting", "start": start,
            "stop": start + timedelta(hours=1)})
        self.assertTrue(
            meeting.partner_ids or meeting.attendee_ids,
            "an ordinary meeting lost its attendees - the fix was applied too "
            "widely and has broken Odoo's calendar for everyone else")

    def test_classes_generated_by_the_schedule_have_none(self):
        """Through the real recurring path, which is what made the phantoms.

        A manual create would prove nothing about the generator: the phantom
        arrived on classes the schedule laid down, and spread through
        copy_data() to every occurrence of the pattern.
        """
        teacher = self.env["res.users"].create({
            "name": "Phantom teacher",
            "login": "phantom.teacher@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        schedule = self.env["fitness.class.schedule"].create({
            "name": "Phantom schedule",
            "class_type_id": self.ctype.id,
            "weekday": "tue",
            "start_time": 7.0,
            "teacher_user_id": teacher.id})
        schedule.action_generate()
        events = schedule.recurrence_id.calendar_event_ids
        self.assertTrue(events, "the schedule generated nothing to check")
        carrying = events.filtered(lambda e: e.partner_ids or e.attendee_ids)
        self.assertFalse(
            carrying,
            "%d of %d generated classes carry a phantom attendee"
            % (len(carrying), len(events)))
