# -*- coding: utf-8 -*-
"""A class she is teaching right now is still on her page.

The default view listed start >= now, so a class left the page the
instant it began. An instructor checking at 10:05 what she was teaching
at 10:00 saw nothing - and the morning message that told her about it
would have linked to a list the class had already fallen off.

The day boundaries are the other half. They were computed as
today_start_utc + timedelta(days=N), which is not the next local
midnight: the Madrid day is 25 hours long on 25 October 2026 and 23
hours on 29 March 2027. A class at 23:30 on the long day fell outside
the Today chip entirely.

Every test here pins the clock with Odoo's own freeze_time, started in
setUp and stopped by addCleanup - never by overriding run(), so a
failure inside setUp cannot leave the clock frozen for whatever runs
next.
"""
from datetime import datetime, timedelta

import pytz

from odoo.tests import TransactionCase, common, tagged

# Imported by NAME, at module level, so a wrong one is an ImportError in
# seconds rather than thirteen AttributeErrors forty minutes into a gate
# run. The module object is imported too, because `request` is patched on
# it for the duration of a call.
from odoo.addons.fitness_teacher_swap.controllers import portal as tsp
from odoo.addons.fitness_teacher_swap.controllers.portal import (
    FitnessTeacherSwapPortal)

MADRID = pytz.timezone('Europe/Madrid')


def _utc(local_naive):
    """A Madrid wall clock time as the naive UTC the database stores."""
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class _InstructorPage(TransactionCase):
    """Shared fixture: one instructor, and a way to ask her page."""

    #: overridden per test; Madrid wall clock
    PINNED = datetime(2026, 10, 6, 9, 55)

    def setUp(self):
        super().setUp()
        # Pinned here, released by cleanup. The controller reads
        # fields.Datetime.now() and derives every boundary from it, so
        # the clock IS the input to this feature.
        freezer = common.freeze_time(_utc(self.PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)

        self.teacher = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Page Teacher',
                'login': 'page.teacher@example.invalid',
                'email': 'page.teacher@example.invalid',
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_teacher').id])]})
        self.room = self.env['fitness.classroom'].sudo().create({
            'name': 'Page Room', 'classroom_type': 'reformer',
            'capacity': 6})
        self.ctype = self.env['fitness.class.type'].sudo().create({
            'name': 'Page Reformer', 'classroom_type': 'reformer',
            'session_type': 'group', 'level': 'all',
            'classroom_id': self.room.id})

    def _class_at(self, local_naive, teacher=None, name=None):
        """A class at a Madrid wall clock time."""
        start = _utc(local_naive)
        return self.env['calendar.event'].sudo().create({
            'name': name or 'Class %s' % local_naive.strftime('%d %b %H:%M'),
            'start': start,
            'stop': start + timedelta(minutes=55),
            'class_type_id': self.ctype.id,
            'is_fitness_class': True,
            'capacity': 6,
            'user_id': (teacher or self.teacher).id,
        })

    def _shown(self, chip='all'):
        """The ids her page returns, through the controller itself."""
        class _Shim(object):
            def __init__(self, env):
                self.env = env
                self.captured = None

            def render(self, template, values=None):
                self.captured = values or {}
                return self.captured

            def redirect(self, url):
                self.captured = {'__redirect__': url}
                return self.captured

        real = getattr(tsp, 'request', None)
        shim = _Shim(self.env(user=self.teacher.id))
        tsp.request = shim
        try:
            ctrl = FitnessTeacherSwapPortal()
            # The undecorated function: @http.route wraps it in a
            # route_wrapper ending in Response.load(), which rejects the
            # plain dict a shim returns.
            endpoint = getattr(ctrl.my_classes, 'original_endpoint', None)
            if endpoint is not None:
                endpoint(ctrl, filter=chip)
            else:
                ctrl.my_classes(filter=chip)
        finally:
            if real is not None:
                tsp.request = real
        vals = shim.captured or {}
        return {r['event'].id for r in vals.get('events_ctx', [])}


@tagged("post_install", "-at_install")
class TestTodaysClassStaysOnHerPage(_InstructorPage):

    longMessage = False
    PINNED = datetime(2026, 10, 6, 9, 55)

    def test_before_it_starts_it_is_listed(self):
        ev = self._class_at(datetime(2026, 10, 6, 10, 0))
        self.assertIn(ev.id, self._shown(),
                      "a class starting in five minutes is not on her page")


@tagged("post_install", "-at_install")
class TestAClassAlreadyRunningIsStillListed(_InstructorPage):

    longMessage = False
    PINNED = datetime(2026, 10, 6, 10, 5)

    def test_five_minutes_in_it_is_still_listed(self):
        """The taxi case. She looks at 10:05 for her 10:00 class."""
        ev = self._class_at(datetime(2026, 10, 6, 10, 0))
        self.assertIn(
            ev.id, self._shown(),
            "the class she is teaching right now has dropped off her page")

    def test_it_is_on_the_today_chip_too(self):
        ev = self._class_at(datetime(2026, 10, 6, 10, 0))
        self.assertIn(ev.id, self._shown('today'))


@tagged("post_install", "-at_install")
class TestLateInTheDay(_InstructorPage):

    longMessage = False
    PINNED = datetime(2026, 10, 6, 23, 30)

    def test_the_whole_day_is_still_listed_at_half_past_eleven(self):
        morning = self._class_at(datetime(2026, 10, 6, 10, 0))
        evening = self._class_at(datetime(2026, 10, 6, 20, 0))
        shown = self._shown()
        self.assertIn(morning.id, shown)
        self.assertIn(evening.id, shown)

    def test_yesterday_is_not_listed(self):
        """Past days belong in History, not on today's page."""
        old = self._class_at(datetime(2026, 10, 5, 10, 0))
        self.assertNotIn(old.id, self._shown(),
                         "yesterday's class is on her current page")


@tagged("post_install", "-at_install")
class TestTheLongDay(_InstructorPage):
    """25 October 2026: Madrid clocks go back, the day is 25 hours."""

    longMessage = False
    PINNED = datetime(2026, 10, 25, 12, 0)

    def test_a_half_past_eleven_class_is_on_the_today_chip(self):
        ev = self._class_at(datetime(2026, 10, 25, 23, 30))
        self.assertIn(
            ev.id, self._shown('today'),
            "the last half hour of the 25-hour day is missing from Today")

    def test_it_is_on_the_default_view_too(self):
        ev = self._class_at(datetime(2026, 10, 25, 23, 30))
        self.assertIn(ev.id, self._shown())

    def test_the_next_day_is_not_on_the_today_chip(self):
        ev = self._class_at(datetime(2026, 10, 26, 0, 30))
        self.assertNotIn(ev.id, self._shown('today'),
                         "a class after midnight is being counted as today")


@tagged("post_install", "-at_install")
class TestTheShortDay(_InstructorPage):
    """29 March 2027: Madrid clocks go forward, the day is 23 hours."""

    longMessage = False
    PINNED = datetime(2027, 3, 29, 12, 0)

    def test_the_last_evening_class_is_on_the_today_chip(self):
        ev = self._class_at(datetime(2027, 3, 29, 23, 30))
        self.assertIn(ev.id, self._shown('today'))

    def test_the_next_day_is_not(self):
        ev = self._class_at(datetime(2027, 3, 30, 0, 30))
        self.assertNotIn(
            ev.id, self._shown('today'),
            "the 23-hour day has overrun into the following morning")


@tagged("post_install", "-at_install")
class TestItShowsOnlyHerOwnClasses(_InstructorPage):

    longMessage = False
    PINNED = datetime(2026, 10, 6, 9, 55)

    def test_another_instructors_class_is_not_listed(self):
        other = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Other Teacher',
                'login': 'other.teacher@example.invalid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_teacher').id])]})
        hers = self._class_at(datetime(2026, 10, 6, 10, 0))
        theirs = self._class_at(datetime(2026, 10, 6, 11, 0), teacher=other)
        shown = self._shown()
        self.assertIn(hers.id, shown)
        self.assertNotIn(theirs.id, shown,
                         "she can see another instructor's class")

    def test_an_empty_class_is_still_listed(self):
        """Nobody booked is not a reason to hide it - she still teaches."""
        ev = self._class_at(datetime(2026, 10, 6, 10, 0))
        self.assertFalse(self.env['fitness.booking'].sudo().search_count(
            [('calendar_event_id', '=', ev.id)]))
        self.assertIn(ev.id, self._shown(),
                      "a class with no bookings is hidden from her")

    def test_a_cancelled_class_is_not_listed(self):
        ev = self._class_at(datetime(2026, 10, 6, 10, 0))
        ev.sudo().write({'class_state': 'cancelled'})
        self.assertNotIn(ev.id, self._shown(),
                         "a cancelled class is still on her timetable")
