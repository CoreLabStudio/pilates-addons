# -*- coding: utf-8 -*-
"""The studio's own clock, for decisions that belong to the studio.

An offer that ends "on 16 October" ends at the end of 16 October IN
BARCELONA. It does not end at a different moment for each student
depending on what timezone her account happens to carry.

fields.Date.context_today() answers in the READER's timezone, falling
back to UTC when she has none - which most portal accounts do. That put
the end of the free trial at 02:00 Madrid on the 17th for those students
and at midnight for everybody else: the same offer closing at two
different moments, decided by a field nobody ever filled in.

So every gate that asks "is the offer still open" asks this instead.
Nothing here depends on the reader at all.
"""
import pytz

from odoo import fields

STUDIO_TZ = 'Europe/Madrid'


def studio_tz():
    """The studio's timezone, never the reader's."""
    try:
        return pytz.timezone(STUDIO_TZ)
    except pytz.UnknownTimeZoneError:          # pragma: no cover
        return pytz.UTC


def studio_today():
    """Today's calendar date in the studio's timezone.

    Localise the stored UTC instant and read the date off it, so the
    answer follows Spanish daylight saving without anything else having
    to know about it.
    """
    return pytz.utc.localize(
        fields.Datetime.now()).astimezone(studio_tz()).date()


def studio_now():
    """The current moment as a studio-local aware datetime."""
    return pytz.utc.localize(fields.Datetime.now()).astimezone(studio_tz())


def studio_midnight_utc(local_date):
    """Midnight of a studio calendar date, as the naive UTC stored.

    Localise FIRST, then convert. Adding a day to a UTC instant is not
    the next local midnight: the Madrid day is 25 hours on 25 October
    2026 and 23 hours on 29 March 2027.
    """
    from datetime import datetime, time
    naive = datetime.combine(local_date, time(0, 0))
    return studio_tz().localize(naive).astimezone(
        pytz.UTC).replace(tzinfo=None)
