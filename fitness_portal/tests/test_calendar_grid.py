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

from odoo.tests import TransactionCase, common, tagged


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

    def test_a_student_slot_carries_no_registration_count(self):
        """The count is opt-in, and the booking pages must not grow one.

        A student choosing a class is told how many places are left by the
        booking page itself; putting a second, differently-worded number on
        the calendar cell is how the two start disagreeing.
        """
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
        days, _meta = self._build(ev)
        slot = [s for d in days for s in d["slots"]][0]
        self.assertNotIn("capacity", slot)
        self.assertNotIn("taken", slot)

    def test_the_caller_supplies_the_count_not_the_event(self):
        """Whoever builds the grid decides what "registered" means.

        booked_seats counts booked and attended, because it governs whether a
        class is full. The instructor's own list counts no-shows as well - they
        registered, and she is looking at who was expected. Reading the event
        here would print one number on the calendar and another in the list
        directly beneath it, for the same class.
        """
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
        ev.capacity = 8
        ev.booked_seats = 2
        days, _meta = self.env["fitness.calendar.grid"].build(
            ev, self.tz, date.today(),
            dow_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            counts={ev.id: 3})
        slot = [s for d in days for s in d["slots"]][0]
        self.assertEqual(slot["taken"], 3,
                         "the number given by the caller must win")
        self.assertEqual(slot["capacity"], 8)

    def test_a_class_nobody_booked_reads_zero(self):
        """An empty class is missing from the grouped read, not present as 0."""
        day = date.today() + timedelta(days=3)
        ev = self._event(self.ct, datetime(day.year, day.month, day.day, 7, 0))
        ev.capacity = 6
        days, _meta = self.env["fitness.calendar.grid"].build(
            ev, self.tz, date.today(),
            dow_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            counts={})
        slot = [s for d in days for s in d["slots"]][0]
        self.assertEqual(slot["taken"], 0)
        self.assertEqual(slot["capacity"], 6)

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

    # ── a class that runs past the reader's midnight ───────────────────────
    #
    # Each case is a fixed date with the clock pinned to it. The first
    # version took "today + 3 days" and Madrid 20:00, which is 23:30 in
    # Asia/Calcutta only while Spain is on summer time: from 22 Oct 2026 that
    # day fell after the clocks went back, Madrid 20:00 became 00:30 the next
    # day in Calcutta, the class no longer crossed midnight, and the test
    # failed on every winter date with 2 != 24. Madrid is UTC+2 in summer and
    # UTC+1 in winter, so the hour that lands at 23:30 in Calcutta is 20:00 in
    # summer and 19:00 in winter.

    FAR = pytz.timezone("Asia/Calcutta")

    def _past_midnight(self, *local_dts):
        """meta for classes at these Madrid wall-clock times, read from Calcutta."""
        events = self.env["calendar.event"]
        for local_dt in local_dts:
            events |= self._event(self.ct, local_dt)
        for ev in events:
            far_start = pytz.UTC.localize(ev.start).astimezone(self.FAR)
            self.assertEqual(far_start.strftime("%H:%M"), "23:30",
                             "fixture error: %s is not 23:30 in Calcutta" % ev.start)
        first = min(local_dts).date()
        with common.freeze_time(datetime(first.year, first.month, first.day, 6, 0)):
            return self.env["fitness.calendar.grid"].build(
                events, self.FAR, first,
                dow_labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def _assert_clipped_at_midnight(self, meta):
        self.assertEqual(meta["hour_end"], 24)
        self.assertEqual(meta["hours"][-1], "23:00")
        self.assertNotIn("24:00", meta["hours"])

    def test_a_class_running_past_midnight_does_not_invent_a_24th_hour(self):
        """Summer: Madrid's 20:00 is 23:30 for a reader in Asia/Calcutta.

        Fifty minutes of it fall on the next day, and ceiling the range to the
        end of the last class then produced an hour labelled "24:00" - not a
        time, and a grid an hour taller than a day. The tail is clipped at the
        bottom of its own day instead.
        """
        _days, meta = self._past_midnight(datetime(2026, 7, 15, 20, 0))
        self._assert_clipped_at_midnight(meta)

    def test_in_winter_the_same_clip_holds(self):
        """Winter: Madrid is UTC+1, so 19:00 is the class that ends past midnight."""
        _days, meta = self._past_midnight(datetime(2026, 1, 14, 19, 0))
        self._assert_clipped_at_midnight(meta)

    def test_across_the_october_clock_change(self):
        """Saturday on summer time and Sunday on winter time, one grid.

        Spain's clocks went back at 03:00 on Sunday 25 Oct 2026. Saturday's
        20:00 (UTC+2) and Sunday's 19:00 (UTC+1) are both 18:00 UTC, both
        23:30 in Calcutta, and both clipped at the bottom of their own day.
        """
        days, meta = self._past_midnight(datetime(2026, 10, 24, 20, 0),
                                         datetime(2026, 10, 25, 19, 0))
        self._assert_clipped_at_midnight(meta)
        by_iso = {d["iso"]: [s["time"] for s in d["slots"]] for d in days}
        self.assertEqual(by_iso.get("2026-10-24"), ["23:30"])
        self.assertEqual(by_iso.get("2026-10-25"), ["23:30"])
