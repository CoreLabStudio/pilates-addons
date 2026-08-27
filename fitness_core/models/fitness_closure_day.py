"""Studio closure days (holidays, one-off shutdowns).

A closure suppresses the class occurrences on one specific date. It deliberately
does NOT touch the recurring schedule that produced them: the pattern stays
intact and keeps generating on every other date, so a bank holiday never
silently rewrites the timetable.

Suppression reuses ``calendar.event.action_cancel_class`` rather than
re-implementing it, so closed-day students get exactly the same treatment as a
manually cancelled class - credit refunded, in-app bell, email.
"""

import logging
from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'Europe/Madrid'


class FitnessClosureDay(models.Model):
    _name = 'fitness.closure.day'
    _description = 'Studio Closure Day'
    _order = 'date desc'

    name = fields.Char("Reason", required=True, help="e.g. Christmas Day, staff training")
    date = fields.Date(required=True, index=True)
    tz = fields.Selection(
        lambda self: [(t, t) for t in pytz.common_timezones],
        string="Studio Timezone", required=True, default=DEFAULT_TZ,
        help="Defines where the closed day starts and ends. Not the admin's timezone.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('applied', 'Applied'),
    ], default='draft', required=True, copy=False)

    affected_event_ids = fields.Many2many(
        'calendar.event', string="Suppressed Classes", readonly=True, copy=False)
    affected_count = fields.Integer(compute='_compute_affected_count')
    refunded_booking_count = fields.Integer(readonly=True, copy=False)

    # Odoo 19 dropped _sql_constraints. It logs a warning and creates nothing,
    # so this table had no unique index on date and the same day could be
    # closed twice.
    _unique_date = models.Constraint(
        'unique (date)',
        "That date is already marked as a closure day.",
    )

    @api.depends('affected_event_ids')
    def _compute_affected_count(self):
        for rec in self:
            rec.affected_count = len(rec.affected_event_ids)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _day_bounds_utc(self):
        """Start/end of the closed date in studio-local time, as naive UTC."""
        self.ensure_one()
        tz = pytz.timezone(self.tz or DEFAULT_TZ)
        start_local = tz.localize(datetime.combine(self.date, time.min))
        end_local = tz.localize(datetime.combine(self.date, time.max))
        to_utc = lambda d: d.astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(start_local), to_utc(end_local)

    def _classes_on_day(self):
        self.ensure_one()
        start, end = self._day_bounds_utc()
        return self.env['calendar.event'].search([
            ('is_fitness_class', '=', True),
            ('start', '>=', start),
            ('start', '<=', end),
        ])

    def action_preview(self):
        """Show what would be suppressed, without changing anything."""
        self.ensure_one()
        events = self._classes_on_day()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Classes on %s", self.date),
            'res_model': 'calendar.event',
            'view_mode': 'list,form',
            'domain': [('id', 'in', events.ids)],
        }

    # ── apply ────────────────────────────────────────────────────────────────
    def action_apply(self):
        """Cancel every class on this date, reusing the studio cancellation flow."""
        for rec in self:
            if rec.state == 'applied':
                raise UserError(_("This closure day has already been applied."))

            events = rec._classes_on_day()
            open_events = events.filtered(lambda e: e.class_state != 'cancelled')
            refunded = 0

            for event in open_events:
                refunded += len(event.booking_ids.filtered(lambda b: b.state == 'booked'))
                # Reuses the existing studio cancellation: refunds credit, sends
                # the in-app bell and the email. No duplicate logic here.
                event.action_cancel_class()

            rec.write({
                'state': 'applied',
                'affected_event_ids': [(6, 0, events.ids)],
                'refunded_booking_count': refunded,
            })
            _logger.info("Closure %s (%s): suppressed %s class(es), refunded %s booking(s)",
                         rec.name, rec.date, len(open_events), refunded)
        return True

    def action_reopen(self):
        """Undo the suppression flag on the classes.

        Note: this does NOT un-refund anyone. Students who were refunded and
        notified stay refunded; they simply become able to book again.
        """
        for rec in self:
            rec.affected_event_ids.write({'class_state': 'scheduled'})
            rec.state = 'draft'
            _logger.info("Closure %s (%s): reopened %s class(es)",
                         rec.name, rec.date, len(rec.affected_event_ids))
        return True
