"""Recurring weekly class schedules.

Design note
-----------
This model is a thin admin-facing wrapper over Odoo's native
``calendar.recurrence``; it deliberately does NOT implement its own recurrence
engine. A class already *is* a ``calendar.event``, and every field the studio
cares about maps cleanly onto one:

    class type  -> class_type_id      teacher  -> user_id
    studio/room -> classroom_id       capacity -> capacity

so ``_apply_recurrence`` (which builds occurrences from ``base_event_id.copy_data()``)
carries them without any special handling.

The one thing native recurrence does not give us is a *rolling* window: its
"forever" mode is capped at ``MAX_RECURRENT_EVENT`` (720) and generates the whole
batch up front. So we use ``end_type='end_date'`` with ``until`` held a fixed
number of weeks ahead, and a nightly cron nudges ``until`` forward. That keeps
rrule handling, "update this/future/all", and occurrence detachment in Odoo's
hands while giving the studio a schedule that never runs dry.
"""

import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

WEEKDAYS = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]
WEEKDAY_INDEX = {code: i for i, (code, _label) in enumerate(WEEKDAYS)}

DEFAULT_TZ = 'Europe/Madrid'


class FitnessClassSchedule(models.Model):
    _name = 'fitness.class.schedule'
    _description = 'Recurring Class Schedule'
    _order = 'weekday, start_time'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)

    class_type_id = fields.Many2one(
        'fitness.class.type', string="Class Type", required=True, ondelete='restrict')
    teacher_user_id = fields.Many2one(
        'res.users', string="Instructor", required=True,
        help="Becomes the organiser (user_id) on each generated class.")
    classroom_id = fields.Many2one(
        'fitness.classroom', string="Studio / Room", ondelete='restrict')

    weekday = fields.Selection(WEEKDAYS, required=True, default='mon')
    start_time = fields.Float(
        "Start Time", required=True, default=9.0,
        help="Local studio time, 24h. 9.5 = 09:30.")
    duration = fields.Float("Duration (hours)", required=True, default=1.0)
    capacity = fields.Integer("Capacity", default=0,
                              help="0 keeps whatever the class type / room implies.")
    session_type = fields.Selection(
        related='class_type_id.session_type', readonly=True, store=False)

    tz = fields.Selection(
        lambda self: [(t, t) for t in pytz.common_timezones],
        string="Studio Timezone", required=True, default=DEFAULT_TZ,
        help="Times above are in this timezone. Deliberately NOT the logged-in "
             "user's timezone - an admin abroad must not shift the studio's schedule.")

    date_start = fields.Date("First Class", required=True, default=fields.Date.context_today)
    date_end = fields.Date("Last Class", help="Leave empty to run indefinitely.")
    horizon_weeks = fields.Integer(
        "Weeks Ahead", default=8, required=True,
        help="How far into the future occurrences are kept generated. "
             "A nightly job tops this up, so the schedule never runs dry.")

    base_event_id = fields.Many2one('calendar.event', readonly=True, copy=False)
    recurrence_id = fields.Many2one('calendar.recurrence', readonly=True, copy=False)
    generated_until = fields.Date(readonly=True, copy=False)
    occurrence_count = fields.Integer(compute='_compute_occurrence_count')


    # ── display ──────────────────────────────────────────────────────────────
    @api.depends('class_type_id', 'weekday', 'start_time')
    def _compute_name(self):
        labels = dict(WEEKDAYS)
        for rec in self:
            if not rec.class_type_id:
                rec.name = _("New Schedule")
                continue
            rec.name = "%s — %s %s" % (
                rec.class_type_id.name,
                labels.get(rec.weekday, ''),
                rec._format_time(rec.start_time),
            )

    @staticmethod
    def _format_time(value):
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        return "%02d:%02d" % (hours, minutes)

    def _compute_occurrence_count(self):
        for rec in self:
            rec.occurrence_count = len(rec.recurrence_id.calendar_event_ids) \
                if rec.recurrence_id else 0


    @api.onchange('class_type_id')
    def _onchange_class_type_id(self):
        """Prefill from the class type; the admin can still override any of it."""
        for rec in self:
            ct = rec.class_type_id
            if not ct:
                continue
            if ct.duration:
                rec.duration = ct.duration / 60.0  # class type stores minutes
            if ct.classroom_id and not rec.classroom_id:
                rec.classroom_id = ct.classroom_id
            if ct.max_capacity and not rec.capacity:
                rec.capacity = ct.max_capacity

    # ── helpers ──────────────────────────────────────────────────────────────
    def _tz(self):
        return pytz.timezone(self.tz or DEFAULT_TZ)

    def _first_occurrence_date(self):
        """First date on/after date_start that falls on the chosen weekday."""
        self.ensure_one()
        target = WEEKDAY_INDEX[self.weekday]
        d = self.date_start
        return d + timedelta(days=(target - d.weekday()) % 7)

    def _local_to_utc(self, date_value):
        """Combine a date with start_time in studio-local tz, return naive UTC."""
        self.ensure_one()
        hours = int(self.start_time)
        minutes = int(round((self.start_time - hours) * 60))
        naive = datetime.combine(date_value, time(hour=hours % 24, minute=minutes))
        return self._tz().localize(naive).astimezone(pytz.utc).replace(tzinfo=None)

    def _target_until(self):
        """How far ahead occurrences should exist, respecting date_end."""
        self.ensure_one()
        horizon = fields.Date.context_today(self) + timedelta(weeks=max(self.horizon_weeks, 1))
        if self.date_end and self.date_end < horizon:
            return self.date_end
        return horizon

    # ── generation ───────────────────────────────────────────────────────────
    def action_generate(self):
        """Create the base event + native recurrence, then materialise occurrences."""
        for rec in self:
            if rec.recurrence_id:
                rec._extend()
                continue

            first = rec._first_occurrence_date()
            if rec.date_end and first > rec.date_end:
                raise UserError(_(
                    "The first %(day)s on or after %(start)s falls after the end date.",
                    day=dict(WEEKDAYS)[rec.weekday], start=rec.date_start))

            start = rec._local_to_utc(first)
            vals = {
                'name': rec.class_type_id.name,
                'start': start,
                'stop': start + timedelta(hours=rec.duration or 1.0),
                'allday': False,
                'is_fitness_class': True,
                'class_type_id': rec.class_type_id.id,
                'classroom_id': rec.classroom_id.id or False,
                'user_id': rec.teacher_user_id.id,
                'recurrency': True,
                'event_tz': rec.tz or DEFAULT_TZ,
                'rrule_type': 'weekly',
                'interval': 1,
                'end_type': 'end_date',
                'until': rec._target_until(),
                rec.weekday: True,
            }
            if rec.capacity:
                vals['capacity'] = rec.capacity

            event = self.env['calendar.event'].with_context(
                no_mail_to_attendees=True, mail_create_nolog=True).create(vals)

            rec.write({
                'base_event_id': event.id,
                'recurrence_id': event.recurrence_id.id,
                'generated_until': event.recurrence_id.until,
            })
            _logger.info("Schedule %s: created recurrence %s until %s",
                         rec.name, event.recurrence_id.id, event.recurrence_id.until)
            # The pattern has no notion of closures, so anything it just laid
            # down on a closed date has to be taken straight back out.
            rec._apply_closures(first, event.recurrence_id.until)
        return True

    def _extend(self):
        """Push `until` forward so the rolling window stays populated.

        Writing a later `until` and re-applying is enough: `_apply_recurrence`
        reconciles against existing events and only creates the missing ones.
        """
        for rec in self.filtered('recurrence_id'):
            target = rec._target_until()
            current = rec.recurrence_id.until
            if current and current >= target:
                continue
            rec.recurrence_id.write({'end_type': 'end_date', 'until': target})
            rec.recurrence_id._apply_recurrence()
            rec.generated_until = target
            _logger.info("Schedule %s: extended to %s", rec.name, target)
            # Only the stretch just added needs sweeping; dates before `current`
            # were dealt with when they were generated.
            rec._apply_closures(current or fields.Date.context_today(rec), target)
        return True

    def _apply_closures(self, date_from, date_to):
        """Hand the newly generated range to the closure days to police.

        Generation deliberately does not know how to cancel a class: it asks
        fitness.closure.day, which runs the same action_cancel_class path a
        manual Apply does, so refunds, the in-app bell and the email are
        identical however the class came to exist.
        """
        swept = self.env['fitness.closure.day']._reapply_to_new_classes(
            date_from=date_from, date_to=date_to)
        if swept:
            _logger.info("Schedule %s: %s generated class(es) cancelled by closure days",
                         self.name, swept)
        return swept

    def action_extend_now(self):
        return self._extend()

    @api.model
    def _cron_extend_schedules(self):
        """Nightly: keep every active schedule topped up to its horizon."""
        schedules = self.search([('recurrence_id', '!=', False)])
        _logger.info("Rolling schedule cron: %s schedule(s)", len(schedules))
        for schedule in schedules:
            try:
                schedule._extend()
            except Exception:  # one bad schedule must not stop the rest
                _logger.exception("Could not extend schedule %s", schedule.id)
        return True

    # ── is generation actually keeping up? ───────────────────────────────────
    #
    # The cron above swallows a failing schedule on purpose, so one bad row
    # cannot stop the rest. The cost is that it reports success while quietly
    # generating nothing, and the studio only finds out weeks later when the
    # timetable runs dry: bookings fail, and every Clase Fija renewal fails
    # together with "no occurrences found". Nothing watches for that today.
    #
    # So the check is on the *outcome*, not the run. A schedule that has been
    # extended is generated to roughly today + horizon_weeks; one that is
    # materially behind is the symptom, whatever the cause - the cron
    # disabled, the worker dead, or an exception hit every night on that row.

    #: How far behind its horizon a schedule may fall before it is a problem.
    #: The cron runs daily, so a day of slack is ordinary; this is deliberately
    #: wider than that, to report a cron that has actually stopped rather than
    #: one that ran late.
    GENERATION_SLACK_DAYS = 3

    @api.model
    def _generation_health(self):
        """(stale_schedules, reason) - what is wrong with generation, if anything.

        Split from the cron so a test can ask the question without a cron, and
        so the answer is one thing rather than a judgement made twice.
        """
        today = fields.Date.context_today(self)
        cron = self.env.ref('fitness_core.ir_cron_extend_class_schedules',
                            raise_if_not_found=False)
        if cron and not cron.sudo().active:
            return self.browse(), _("The class generation job is switched off.")

        stale = self.browse()
        for rec in self.search([('active', '=', True),
                                ('recurrence_id', '!=', False)]):
            # A schedule with an end date stops generating on purpose once it
            # is reached; that is not a fault.
            if rec.date_end and rec.date_end <= today:
                continue
            expected = rec._target_until()
            if not rec.generated_until:
                stale |= rec
                continue
            behind = (expected - rec.generated_until).days
            if behind > self.GENERATION_SLACK_DAYS:
                stale |= rec
        if stale:
            return stale, _(
                "%(count)s schedule(s) have not been generated forward for more "
                "than %(days)s days.", count=len(stale), days=self.GENERATION_SLACK_DAYS)
        return self.browse(), ''

    @api.model
    def _cron_check_generation_health(self):
        """Daily: shout if the timetable has stopped being generated.

        Alerts rather than repairs. Extending here would paper over whatever
        stopped the nightly job and leave the real fault running - and the
        thing worth knowing is that it stopped, not that something caught up.
        """
        stale, reason = self._generation_health()
        if not reason:
            _logger.info("[SCHEDULE HEALTH] generation is up to date")
            return True

        detail = reason
        if stale:
            detail += "\n" + "\n".join(
                "  - %s (generated to %s)" % (rec.name, rec.generated_until or _("never"))
                for rec in stale[:10])
            if len(stale) > 10:
                detail += "\n  - " + _("...and %s more", len(stale) - 10)
        _logger.error("[SCHEDULE HEALTH] %s", detail)
        self._notify_generation_stalled(stale, reason, detail)
        return True

    @api.model
    def _notify_generation_stalled(self, stale, reason, detail):
        """Tell somebody. Overridden where a notification channel exists.

        fitness_core cannot reach the in-app notification model, which lives
        downstream of it, so this logs and leaves a seam. The point of keeping
        it separate is that the detection above is testable without any
        alerting being installed at all.
        """
        return False

    # ── opening and closing a slot ─────────────────────────────────────────

    def _future_occurrences(self):
        """Occurrences from today onward, for every schedule in self."""
        recurrences = self.mapped('recurrence_id')
        if not recurrences:
            return self.env['calendar.event']
        return self.env['calendar.event'].with_context(active_test=False).search([
            ('recurrence_id', 'in', recurrences.ids),
            ('start', '>=', fields.Datetime.now()),
        ])

    @staticmethod
    def _booked_event_ids(events):
        """Which of these classes somebody is actually booked into."""
        if not events:
            return set()
        Booking = events.env['fitness.booking'].sudo()
        return {
            event.id
            for event, _count in Booking._read_group(
                [('calendar_event_id', 'in', events.ids),
                 ('state', 'in', ('booked', 'attended', 'no_show'))],
                groupby=['calendar_event_id'], aggregates=['__count'])
        }

    def _fixed_slot_note(self):
        """Anything worth saying about members whose fixed class is these rows.

        Empty here deliberately. Clase Fija lives in fitness_subscriptions,
        which depends on this module and not the other way round, so core
        cannot ask the question - it only leaves somewhere for the answer to
        go. On a database without that module there is nothing to say.
        """
        return ''

    def action_close_for_booking(self):
        """Take these slots off the timetable and out of the booking list.

        Archives rather than cancels: cancelling is a studio decision about a
        class that was going to run, and it emails students and returns
        credits. This is the studio deciding the slot is not offered any more,
        which should be silent and reversible.

        A class somebody is already booked into is left exactly as it is. It
        would be trivial to archive it too, and it would strand the student:
        their booking would point at a class that no longer appears anywhere.
        Those are reported back so an admin can deal with them deliberately.
        """
        # Members attached to this series are collected before anything is
        # archived: once the row is inactive the slots still point at it, but
        # an admin reading the notification afterwards has no way to find out
        # who she just cut off. Named here so the consequence arrives with the
        # action rather than as a support message three weeks later, when a
        # renewal fails with "no occurrences found".
        fixed_slot_note = self._fixed_slot_note()

        events = self._future_occurrences()
        booked = self._booked_event_ids(events)
        closeable = events.filtered(lambda e: e.id not in booked and e.active)
        closeable.write({'active': False})
        self.write({'active': False})

        msg = _("%(slots)s slot(s) closed. %(hidden)s upcoming class(es) hidden.",
                slots=len(self), hidden=len(closeable))
        if booked:
            msg += " " + _(
                "%(kept)s class(es) were left alone because students are booked "
                "into them - handle those from Bulk Cancel Classes.", kept=len(booked))
        if fixed_slot_note:
            msg += "\n\n" + fixed_slot_note
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Slots closed"),
                'message': msg,
                'type': 'warning' if booked else 'success',
                'sticky': bool(booked),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_open_for_booking(self):
        """Put these slots back. The exact inverse of closing them."""
        events = self.with_context(active_test=False)._future_occurrences()
        hidden = events.filtered(lambda e: not e.active)
        hidden.write({'active': True})
        self.write({'active': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Slots opened"),
                'message': _("%(slots)s slot(s) opened. %(shown)s upcoming class(es) "
                             "back on the booking list.",
                             slots=len(self), shown=len(hidden)),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_view_occurrences(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Occurrences — %s", self.name),
            'res_model': 'calendar.event',
            'view_mode': 'list,calendar,form',
            'domain': [('recurrence_id', '=', self.recurrence_id.id)],
            'context': {'default_is_fitness_class': True},
        }
