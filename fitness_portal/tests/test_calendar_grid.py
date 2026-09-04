# -*- coding: utf-8 -*-
"""Where a class sits in the day.

The calendar renders three ways off one set of cells: month as compact bars,
the phone week as a stacked list, and day and the desktop week as a real time
grid with the hours down the side. Only the last of those needs to know when a
class starts and how long it runs, and that is the part tested here - the
placement itself happens in the browser, but it is arithmetic on these two
numbers, so a wrong number here is a class drawn at the wrong hour.

The hour range matters as much as the positions. It is taken from the classes
rather than assumed, because a fixed 00:00-24:00 grid would be nine-tenths
empty; asserting it against the fixtures is what stops that regressing to a
constant.
"""
import pytz
from datetime import date, datetime, timedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCalendarGridTimes(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = pytz.timezone("Europe/Madrid")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Grid Room",
            "classroom_type": "reformer",
            "capacity": 6,
        })
        cls.ct = cls.env["fitness.class.type"].create({
            "name": "Grid Reformer",
            "classroom_type": "reformer",
            "duration": 50,
            "level": "all",
            "session_type": "group",
            "intensity": "moderate",
        })
        cls.ct_barre = cls.env["fitness.class.type"].create({
            "name": "Grid Barre",
            "classroom_type": "barre",
            "duration": 50,
            "level": "all",
            "session_type": "group",
            "intensity": "very_high",
        })

    def _event(self, ct, local_dt, minutes=50):
        """A class at a wall-clock time in the studio's timezone."""
        start = self.tz.localize(local_dt).astimezone(pytz.UTC).replace(tzinfo=None)
        return self.env["calendar.event"].create({
            "name": ct.name,
            "class_type_id": ct.id,
            "start": start,
            "stop": start + timedelta(minutes=minutes),
        })

    def _build(self, events):
        return self.env["fitness.calendar.grid"].build(
            events, self.tz, date.today(),
            dow_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def test_a_slot_knows_when_it_starts_and_how_long_it_runs(self):
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
        days, _meta = self._build(ev)
        slots = [s for d in days for s in d["slots"]]
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["start_min"], 7 * 60,
                         "07:00 local must be 420 minutes into the day")
        self.assertEqual(slots[0]["dur_min"], 50)
        # and the human-readable time still agrees with the position
        self.assertEqual(slots[0]["time"], "07:00")

    def test_the_position_is_local_time_not_utc(self):
        """Madrid is one or two hours off UTC, so a naive read is an hour out.

        This is the failure that would look almost right - every class drawn
        neatly, all of them in the wrong row.
        """
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 20, 0))
        days, _meta = self._build(ev)
        slot = [s for d in days for s in d["slots"]][0]
        self.assertEqual(slot["start_min"], 20 * 60)
        self.assertNotEqual(slot["start_min"], ev.start.hour * 60,
                            "the slot was positioned from the stored UTC hour")

    def test_the_hour_range_comes_from_the_classes(self):
        """07:00 to 21:00 for a studio that runs 07:00 to 20:50 - not 00:00."""
        day = date.today() + timedelta(days=3)
        evs = (self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
               | self._event(self.ct, datetime(day.year, day.month, day.day, 13, 0))
               | self._event(self.ct, datetime(day.year, day.month, day.day, 20, 0)))
        _days, meta = self._build(evs)
        self.assertEqual(meta["hour_start"], 7)
        # 20:50 has to fit, so the range ends at 21
        self.assertEqual(meta["hour_end"], 21)
        self.assertEqual(meta["hours"][0], "07:00")
        self.assertEqual(meta["hours"][-1], "20:00")
        self.assertEqual(len(meta["hours"]), 14)

    def test_the_empty_afternoon_is_left_in_the_range(self):
        """The gap between 13:00 and 18:00 is the shape of the studio's day.

        Compressing it would make the grid shorter and the day unreadable, so
        every hour between the first and the last is present whether or not a
        class falls in it.
        """
        day = date.today() + timedelta(days=3)
        evs = (self._event(self.ct, datetime(day.year, day.month, day.day, 13, 0))
               | self._event(self.ct, datetime(day.year, day.month, day.day, 18, 0)))
        _days, meta = self._build(evs)
        self.assertEqual(
            meta["hours"],
            ["13:00", "14:00", "15:00", "16:00", "17:00", "18:00"],
            "hours were dropped for having no class in them")

    def test_two_rooms_at_the_same_hour_both_survive(self):
        """The lanes are drawn in the browser, but both classes must be there.

        If one were dropped server-side the grid would look tidy and be wrong.
        """
        day = date.today() + timedelta(days=3)
        evs = (self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
               | self._event(self.ct_barre, datetime(day.year, day.month, day.day, 7, 0)))
        days, _meta = self._build(evs)
        slots = [s for d in days for s in d["slots"]]
        self.assertEqual(len(slots), 2)
        self.assertEqual({s["start_min"] for s in slots}, {7 * 60})
        self.assertEqual({s["ct"] for s in slots}, {"reformer", "barre"})
        # and they are told apart by shade, which is the whole point
        self.assertEqual(len({s["shade"] for s in slots}), 2)

    def test_a_class_with_no_end_still_gets_a_height(self):
        """A zero-height block is invisible; give it the studio's usual length."""
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 9, 0))
        ev.write({"stop": ev.start})
        days, _meta = self._build(ev)
        slot = [s for d in days for s in d["slots"]][0]
        self.assertEqual(slot["dur_min"], 50)

    def test_no_classes_still_returns_the_keys_the_page_reads(self):
        """The template reads hour_start and hours unconditionally."""
        _days, meta = self._build(self.env["calendar.event"])
        self.assertEqual(meta["hours"], [])
        self.assertEqual(meta["hour_start"], 0)
        self.assertEqual(meta["count"], 0)

    def test_a_class_running_past_midnight_does_not_invent_a_24th_hour(self):
        """Madrid's 20:00 is 23:30 for a reader in Asia/Calcutta.

        Fifty minutes of it fall on the next day, and ceiling the range to the
        end of the last class then produced an hour labelled "24:00" - not a
        time, and a grid an hour taller than a day. The tail is clipped at the
        bottom of its own day instead.
        """
        day = date.today() + timedelta(days=3)
        far = pytz.timezone("Asia/Calcutta")
        start = self.tz.localize(
            datetime(day.year, day.month, day.day, 20, 0)
        ).astimezone(pytz.UTC).replace(tzinfo=None)
        ev = self.env["calendar.event"].create({
            "name": self.ct.name,
            "class_type_id": self.ct.id,
            "start": start,
            "stop": start + timedelta(minutes=50),
        })
        _days, meta = self.env["fitness.calendar.grid"].build(
            ev, far, date.today(),
            dow_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self.assertEqual(meta["hour_end"], 24)
        self.assertEqual(meta["hours"][-1], "23:00")
        self.assertNotIn("24:00", meta["hours"])
