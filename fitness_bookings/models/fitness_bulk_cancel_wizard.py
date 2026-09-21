# -*- coding: utf-8 -*-
"""Manage a day's classes in one pass - both directions.

Cancelling a snow day meant opening each class in turn and cancelling it, with
no view of how many students that added up to until it was done. This is the
same operation with the day in front of you: pick the date, see what runs and
how full each one is, switch off the ones that are off, say why if you want
to, and apply them together.

It reads both ways. The day arrives showing every class on it, running and
cancelled alike, each with a switch set to what it is now. Switching one off
cancels it; switching a cancelled one back on puts it on the timetable again.
That matters because calling a day off is a decision people change their mind
about - the storm passes, the instructor recovers - and putting classes back
used to mean finding them somewhere else entirely, in a list that hid them by
default. Seeing the whole day, in both states, is what makes changing your
mind possible in the place the decision was made.

It does not reimplement either direction. A class switched off goes through
calendar.event.action_cancel_class, which returns the credits and tells the
students; a class switched on goes through action_restore_classes, which
deliberately does NOT re-book anybody - their credits are back and they have
to book again, which is said out loud rather than left to be discovered. So a
class handled here ends up in exactly the same state as one handled from its
own form.

The day's classes are lines rather than a many2many. A many2many renders as
an "Add a line" picker: you would have to know which class you wanted and go
looking for it, one at a time, which is the thing this page exists to avoid.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import format_date

_logger = logging.getLogger(__name__)


class FitnessBulkCancelWizard(models.TransientModel):
    _name = 'fitness.class.bulk.cancel.wizard'
    _description = 'Manage a day of classes'

    day = fields.Date(
        string='Day', required=True, default=fields.Date.context_today,
        help="The day to look at. Changing it reloads the classes below.")

    line_ids = fields.One2many(
        'fitness.class.bulk.cancel.line', 'wizard_id', string='Classes')

    reason = fields.Text(
        string='Reason',
        help="Optional. Goes to every student on the classes you switch off, "
             "with the message they already get, and is kept on their booking.")

    day_summary = fields.Char(compute='_compute_summaries')
    selection_summary = fields.Char(compute='_compute_summaries')
    # How many lines differ from what the class is now. The apply button hangs
    # off this: with nothing changed there is nothing to apply.
    change_count = fields.Integer(compute='_compute_summaries')

    @api.depends('line_ids', 'line_ids.is_on', 'line_ids.class_state', 'day')
    def _compute_summaries(self):
        for wiz in self:
            events = wiz.line_ids.mapped('event_id')
            wiz.day_summary = wiz._summarise(events, wiz.day)
            off, on = wiz._pending()
            wiz.change_count = len(off) + len(on)
            wiz.selection_summary = wiz._describe_pending(off, on)

    def _pending(self):
        """The lines whose switch no longer matches the class.

        Returns (to_switch_off, to_switch_on) as line recordsets. Read from
        the class itself rather than from a remembered starting value, so a
        class somebody else changed while this dialog sat open is compared
        against what it actually is now.
        """
        self.ensure_one()
        off = self.line_ids.filtered(
            lambda l: not l.is_on and l.class_state != 'cancelled')
        on = self.line_ids.filtered(
            lambda l: l.is_on and l.class_state == 'cancelled')
        return off, on

    def _describe_pending(self, off, on):
        """What is about to happen, in students rather than in rows."""
        parts = []
        if off:
            students = sum(off.mapped('event_id.booked_seats'))
            # One class is the ordinary case - somebody's instructor is ill -
            # so "Switching off 1 classes" is the sentence the studio reads
            # most often. Spelled out rather than counted at.
            parts.append(_(
                'Switching off this class will cancel %(students)s student '
                'bookings and return their credits.', students=students)
                if len(off) == 1 else _(
                'Switching off %(classes)s classes will cancel %(students)s '
                'student bookings and return their credits.',
                classes=len(off), students=students))
        if on:
            # Said every time, because it is the half people assume works the
            # other way: putting a class back does not put its students back.
            parts.append(_(
                'Switching this class on puts it back on the timetable. '
                'Students who were cancelled are not re-booked - they keep '
                'their credits and book again.')
                if len(on) == 1 else _(
                'Switching on %(classes)s classes puts them back on the '
                'timetable. Students who were cancelled are not re-booked - '
                'they keep their credits and book again.', classes=len(on)))
        return ' '.join(parts) if parts else False

    @api.onchange('day')
    def _onchange_day(self):
        """Load the day, already listed, each switch set to what the class is."""
        for wiz in self:
            wiz.line_ids = [(5, 0, 0)] + [
                (0, 0, {
                    'event_id': e.id,
                    # The switch shows the truth on arrival; only a switch the
                    # studio moves means anything.
                    'is_on': e.class_state != 'cancelled',
                })
                for e in wiz._classes_on(wiz.day)
            ]

    def _classes_on(self, day):
        """Every class that day, running and cancelled alike.

        Cancelled ones used to be filtered out here, which made the dialog a
        one-way door: once a day was called off it vanished from the only
        screen that could have put it back.
        """
        if not day:
            return self.env['calendar.event'].browse()
        return self.env['calendar.event'].search([
            ('is_fitness_class', '=', True),
            # A Date against a Datetime column: Odoo compares the stored UTC
            # value, so this is the studio's day give or take the offset. Good
            # enough to choose from, and every line shows its own time.
            ('start', '>=', fields.Datetime.to_datetime(day)),
            ('start', '<', fields.Datetime.to_datetime(
                fields.Date.add(day, days=1))),
        ], order='start asc')

    def _summarise(self, events, day):
        """"14 students booked across 5 classes on 17 Sept, 2 cancelled"."""
        if not day:
            return False
        if not events:
            return _('No classes on %(day)s.',
                     day=format_date(self.env, day, date_format='d MMM'))
        running = events.filtered(lambda e: e.class_state != 'cancelled')
        text = _(
            '%(students)s students booked across %(classes)s classes on %(day)s',
            students=sum(running.mapped('booked_seats')),
            classes=len(running),
            day=format_date(self.env, day, date_format='d MMM'))
        cancelled = len(events) - len(running)
        if cancelled:
            text += ' ' + _('(%(cancelled)s already cancelled)',
                            cancelled=cancelled)
        return text

    def action_select_all(self):
        """Switch the whole day off - the snow-day case, which is the point."""
        self.ensure_one()
        self.line_ids.is_on = False
        return self._reopen()

    def action_select_none(self):
        """Put the whole day back on."""
        self.ensure_one()
        self.line_ids.is_on = True
        return self._reopen()

    def _reopen(self):
        """Keep the dialog on screen after a button that only moved switches."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        """Apply the switches that moved, in both directions."""
        self.ensure_one()
        off_lines, on_lines = self._pending()
        if not (off_lines or on_lines):
            raise UserError(_("Nothing has changed. Move a switch first."))

        reason = (self.reason or '').strip()
        cancelled = students = restored = 0

        # Threaded through the context so it reaches the students the same way
        # a single cancellation does, rather than being written on the side
        # where nobody would ever read it.
        for event in off_lines.mapped('event_id').with_context(
                cancel_reason=reason or False):
            if event.class_state == 'cancelled':
                # Somebody cancelled it while this dialog was open. Skipping is
                # right; failing the whole batch over it is not.
                continue
            students += event.booked_seats or 0
            event.action_cancel_class()
            cancelled += 1

        to_restore = on_lines.mapped('event_id').filtered(
            lambda e: e.class_state == 'cancelled')
        if to_restore:
            # The same method the Schedule's "Put classes back" uses, so the
            # two cannot drift - including its refusal for non-managers and
            # its rule about not re-booking anybody.
            to_restore.action_restore_classes()
            restored = len(to_restore)

        _logger.info(
            "[MANAGE CLASSES] %s on %s: %s cancelled (%s student bookings), "
            "%s put back, by %s, reason=%r",
            self.day, self.env.user.login, cancelled, students, restored,
            self.env.user.login, reason or '')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Day updated"),
                'message': self._applied_message(cancelled, students, restored),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _applied_message(self, cancelled, students, restored):
        parts = []
        if cancelled:
            parts.append(_(
                '%(classes)s classes cancelled. %(students)s student bookings '
                'were cancelled and their credits returned.',
                classes=cancelled, students=students))
        if restored:
            parts.append(_(
                '%(classes)s classes are back on the timetable. Students who '
                'were cancelled have not been re-booked - their credits are '
                'back and they need to book again.', classes=restored))
        return ' '.join(parts) if parts else _('Nothing changed.')


class FitnessBulkCancelLine(models.TransientModel):
    _name = 'fitness.class.bulk.cancel.line'
    _description = 'A class on the day being managed'
    _order = 'start asc'

    wizard_id = fields.Many2one(
        'fitness.class.bulk.cancel.wizard', required=True, ondelete='cascade')
    event_id = fields.Many2one('calendar.event', required=True, readonly=True)
    # The switch, and it reads as the class's own state rather than as an
    # instruction: it arrives showing what the class is, and moving it is what
    # asks for a change. A tick box labelled "Off?" could only ever say one
    # thing, which is why the screen could only ever do one thing.
    is_on = fields.Boolean(string='On')

    # Read off the class. Related rather than copied so a line cannot drift
    # from the class it stands for while the dialog is open.
    class_state = fields.Selection(
        related='event_id.class_state', string='Status', readonly=True)
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
