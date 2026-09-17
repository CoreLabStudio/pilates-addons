# -*- coding: utf-8 -*-
"""PART G - cancel a day's classes in one pass.

Cancelling a snow day meant opening each class in turn and cancelling it, with
no view of how many students that added up to until it was done. This is the
same operation with the day in front of you: pick the date, see what runs and
how full each one is, tick the ones that are off, say why if you want to, and
cancel them together.

It does not reimplement cancelling. Each class still goes through
calendar.event.action_cancel_class, which is what returns the credits and
tells the students and the instructor - so a class cancelled here and a class
cancelled from its own form end up in exactly the same state.

The day's classes are lines rather than a many2many. A many2many renders as
an "Add a line" picker: you would have to know which class you wanted and go
looking for it, one at a time, which is the thing this page exists to avoid.
Lines let the day arrive already listed, with its times and how full each one
is, and a tick box against each.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import format_date

_logger = logging.getLogger(__name__)


class FitnessBulkCancelWizard(models.TransientModel):
    _name = 'fitness.class.bulk.cancel.wizard'
    _description = 'Cancel several classes at once'

    day = fields.Date(
        string='Day', required=True, default=fields.Date.context_today,
        help="The day to look at. Changing it reloads the classes below.")

    line_ids = fields.One2many(
        'fitness.class.bulk.cancel.line', 'wizard_id', string='Classes')

    reason = fields.Text(
        string='Reason',
        help="Optional. Goes to every student on the classes you cancel, with "
             "the message they already get, and is kept on their booking.")

    day_summary = fields.Char(compute='_compute_summaries')
    selection_summary = fields.Char(compute='_compute_summaries')
    selected_count = fields.Integer(compute='_compute_summaries')

    @api.depends('line_ids', 'line_ids.selected', 'day')
    def _compute_summaries(self):
        for wiz in self:
            events = wiz.line_ids.mapped('event_id')
            wiz.day_summary = wiz._summarise(events, wiz.day)
            chosen = wiz.line_ids.filtered('selected')
            wiz.selected_count = len(chosen)
            if not chosen:
                wiz.selection_summary = False
            else:
                wiz.selection_summary = _(
                    'Cancelling %(classes)s classes will cancel %(students)s '
                    'student bookings and return their credits.',
                    classes=len(chosen),
                    students=sum(chosen.mapped('event_id.booked_seats')))

    @api.onchange('day')
    def _onchange_day(self):
        """Load the day, already listed. Fires when the dialog opens too."""
        for wiz in self:
            wiz.line_ids = [(5, 0, 0)] + [
                (0, 0, {'event_id': e.id}) for e in wiz._classes_on(wiz.day)]

    def _classes_on(self, day):
        """Everything that runs that day and has not already been cancelled."""
        if not day:
            return self.env['calendar.event'].browse()
        return self.env['calendar.event'].search([
            ('is_fitness_class', '=', True),
            ('class_state', '!=', 'cancelled'),
            # A Date against a Datetime column: Odoo compares the stored UTC
            # value, so this is the studio's day give or take the offset. Good
            # enough to choose from, and every line shows its own time.
            ('start', '>=', fields.Datetime.to_datetime(day)),
            ('start', '<', fields.Datetime.to_datetime(
                fields.Date.add(day, days=1))),
        ], order='start asc')

    def _summarise(self, events, day):
        """"14 students booked across 5 classes on 17 Sept"."""
        if not day:
            return False
        if not events:
            return _('No classes on %(day)s.',
                     day=format_date(self.env, day, date_format='d MMM'))
        return _(
            '%(students)s students booked across %(classes)s classes on %(day)s',
            students=sum(events.mapped('booked_seats')),
            classes=len(events),
            day=format_date(self.env, day, date_format='d MMM'))

    def action_select_all(self):
        """Tick everything that day - the snow-day case, which is the point."""
        self.ensure_one()
        self.line_ids.selected = True
        return self._reopen()

    def action_select_none(self):
        self.ensure_one()
        self.line_ids.selected = False
        return self._reopen()

    def _reopen(self):
        """Keep the dialog on screen after a button that only changed ticks."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_cancel_selected(self):
        self.ensure_one()
        chosen = self.line_ids.filtered('selected').mapped('event_id')
        if not chosen:
            raise UserError(_("Tick at least one class to cancel."))

        reason = (self.reason or '').strip()
        # Threaded through the context so it reaches the students the same way
        # a single cancellation does, rather than being written on the side
        # where nobody would ever read it.
        events = chosen.with_context(cancel_reason=reason or False)

        cancelled = 0
        students = 0
        for event in events:
            if event.class_state == 'cancelled':
                # Somebody cancelled it while this dialog was open. Skipping
                # is right; failing the whole batch over it is not.
                continue
            students += event.booked_seats or 0
            event.action_cancel_class()
            cancelled += 1

        _logger.info(
            "[BULK CANCEL] %s class(es) on %s cancelled by %s, %s student "
            "booking(s) affected, reason=%r",
            cancelled, self.day, self.env.user.login, students, reason or '')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Classes cancelled"),
                'message': _(
                    '%(classes)s classes cancelled. %(students)s student '
                    'bookings were cancelled and their credits returned.',
                    classes=cancelled, students=students),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class FitnessBulkCancelLine(models.TransientModel):
    _name = 'fitness.class.bulk.cancel.line'
    _description = 'A class offered for cancelling'
    _order = 'start asc'

    wizard_id = fields.Many2one(
        'fitness.class.bulk.cancel.wizard', required=True, ondelete='cascade')
    event_id = fields.Many2one('calendar.event', required=True, readonly=True)
    selected = fields.Boolean(string='Off?')

    # Read off the class. Related rather than copied so a line cannot drift
    # from the class it stands for while the dialog is open.
    start = fields.Datetime(related='event_id.start', string='Time', readonly=True)
    name = fields.Char(related='event_id.name', string='Class', readonly=True)
    classroom_id = fields.Many2one(
        related='event_id.classroom_id', string='Studio', readonly=True)
    teacher_id = fields.Many2one(
        related='event_id.user_id', string='Instructor', readonly=True)
    booked_seats = fields.Integer(
        related='event_id.booked_seats', string='Booked', readonly=True)
    capacity = fields.Integer(
        related='event_id.capacity', string='Capacity', readonly=True)
