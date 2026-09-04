# -*- coding: utf-8 -*-
"""One calendar grid, three pages.

The timetable, the booking list and a student's own schedule all show classes
on dates. They differ only in which classes, so the grid is built once here and
each page hands it a different set. Building it three times is how the three
would drift apart.

The output is deliberately dumb: a flat list of day cells, Monday-aligned at
both ends so a month renders as whole weeks. The browser decides which cells to
show for day, week or month - no second server round trip to change view, and
no second copy of the same classes in the page.

Each slot also carries where it sits in the day - minutes from midnight and
how long it runs - so day and desktop-week can render as a real time grid with
hours down the side. That is a rendering decision made in the browser; the data
is the same either way, which is why month and the stacked phone week keep
working off these very same cells.

Colour is the light/mid/deep tier per class type. That scale was mapped and
contrast-checked earlier but deliberately left unrendered: down a single list
column three blues read as noise, whereas here class types sit side by side in
one row and the shade is the only thing separating them. This is the view it
was built for.
"""
from datetime import timedelta

import pytz

from odoo import models
from odoo.addons.fitness_core import class_colors


class FitnessCalendarGrid(models.AbstractModel):
    _name = 'fitness.calendar.grid'
    _description = 'Shared calendar grid builder for the student portal'

    def build(self, events, tz, today_local, booked_event_ids=None,
              href_pattern='/my/classes/%d', dow_labels=None):
        """Return (days, meta) for a set of calendar.event records.

        days -- Monday-aligned list of {date, iso, day, month, in_past,
                is_today, slots[]}, contiguous, covering every event given.
        meta -- {first, last, count} so the page can label itself without
                re-deriving the range from the cells.
        """
        booked_event_ids = booked_event_ids or set()
        by_date = {}

        for ev in events:
            if not ev.start:
                continue
            local = pytz.UTC.localize(ev.start).astimezone(tz)
            start_min = local.hour * 60 + local.minute
            # stop is the truth; duration is a float-hours convenience field and
            # a class with neither still has to be drawable, so it gets the
            # studio's usual length rather than a zero-height block.
            if ev.stop:
                dur_min = int(round((ev.stop - ev.start).total_seconds() / 60.0))
            else:
                dur_min = int(round((ev.duration or 0) * 60))
            if dur_min <= 0:
                dur_min = 50
            ct = ev.class_type_id
            room = (ct.classroom_type or '') if ct else ''
            # tier_for reads the studio's own intensity field, falling back to
            # the name table - see fitness_core/class_colors.py
            tier = class_colors.tier_for(ct) if ct else class_colors.DEFAULT_TIER
            by_date.setdefault(local.date(), []).append({
                'time': local.strftime('%H:%M'),
                'sort': local,
                'start_min': start_min,
                'dur_min': dur_min,
                'name': (ct.name if ct else ev.name) or ev.name or '',
                'href': href_pattern % ev.id,
                'shade': class_colors.css_class(room, tier),
                'ct': room,
                'booked': ev.id in booked_event_ids,
            })

        if not by_date:
            return [], {'first': None, 'last': None, 'count': 0,
                        'hour_start': 0, 'hour_end': 0, 'hours': []}

        first, last = min(by_date), max(by_date)
        # whole weeks at both ends, or a month view shows ragged part-rows
        start = first - timedelta(days=first.weekday())
        end = last + timedelta(days=6 - last.weekday())

        days, cur = [], start
        while cur <= end:
            slots = sorted(by_date.get(cur, []), key=lambda s: s['sort'])
            for s in slots:
                s.pop('sort', None)
            days.append({
                'date': cur,
                'iso': cur.strftime('%Y-%m-%d'),
                'day': cur.day,
                # Named for the stacked views. A column header only works while
                # the grid is seven wide; on a phone week and day are one
                # column, and a bare number tells you nothing.
                'dow': (dow_labels[cur.weekday()] if dow_labels else ''),
                'month': cur.strftime('%Y-%m'),
                'in_past': cur < today_local,
                'is_today': cur == today_local,
                'slots': slots,
            })
            cur += timedelta(days=1)

        # The hour range the time grid spans, taken from the classes rather
        # than assumed. A fixed 00:00-24:00 would be nine-tenths empty; this
        # studio runs 07:00 to just before 21:00, and the hole in the middle of
        # its day is real information, so the range is honest about both ends
        # and nothing between them is compressed away.
        starts = [s['start_min'] for v in by_date.values() for s in v]
        ends = [s['start_min'] + s['dur_min'] for v in by_date.values() for s in v]
        hour_start = min(starts) // 60
        hour_end = -(-max(ends) // 60)          # ceil, so the last class fits
        # A late class can end after midnight once the reader's timezone is far
        # enough from the studio's - Madrid's 20:00 is 23:30 in Asia/Calcutta,
        # and 50 minutes of it fall on the next day. The grid is one day tall,
        # so cap it there: the tail is clipped at the bottom of its day, which
        # is what every calendar does with a class that runs over midnight.
        # Without this the range ran to a "24:00" hour that is not a time.
        hour_end = min(hour_end, 24)
        if hour_end <= hour_start:
            hour_end = min(hour_start + 1, 24)

        return days, {
            'first': first.strftime('%Y-%m-%d'),
            'last': last.strftime('%Y-%m-%d'),
            'count': sum(len(v) for v in by_date.values()),
            'hour_start': hour_start,
            'hour_end': hour_end,
            'hours': ['%02d:00' % h for h in range(hour_start, hour_end)],
        }
