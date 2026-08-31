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
        'res.users', string="Teacher", required=True,
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
