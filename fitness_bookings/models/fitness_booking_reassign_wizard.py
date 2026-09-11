# -*- coding: utf-8 -*-
"""Cancel one student's booking, and optionally put them in another class.

Cancelling a single student used to mean cancelling and then telling them to
go and rebook themselves, which is the studio doing half a job: the person who
knows a space just opened is the person at the desk, not the student at home.
This does both in one step - and, deliberately, will do only the first.

The assignment is optional on purpose. A student who wants their credit back
and no replacement must not be moved somewhere they did not ask to go, so
"Cancel only" is a first-class outcome rather than a thing you reach by
leaving a field blank and hoping.

Reached from both sides of the same fact: from the student's booking under
Students, and from the class roster under Classes. One wizard either way, so
the two entry points cannot drift apart.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FitnessBookingReassignWizard(models.TransientModel):
    _name = 'fitness.booking.reassign.wizard'
    _description = 'Cancel a booking, optionally moving the student'

    booking_id = fields.Many2one(
        'fitness.booking', required=True, ondelete='cascade', readonly=True)

    student_id = fields.Many2one(related='booking_id.student_id', readonly=True,
                                 string='Student')
    from_event_id = fields.Many2one(related='booking_id.calendar_event_id',
                                    readonly=True, string='Leaving')
    from_start = fields.Datetime(related='booking_id.calendar_event_id.start',
                                 readonly=True, string='Class date')

    target_event_id = fields.Many2one(
        'calendar.event', string='Move to',
        domain="[('id', 'in', available_event_ids)]",
        help="Leave empty to cancel without moving the student anywhere.")
    available_event_ids = fields.Many2many(
        'calendar.event', compute='_compute_available_event_ids')

    restore_credit = fields.Boolean(
        'Return the credit', default=True,
        help="Applies to a cancellation inside the studio's cancellation "
             "window, where credit would not normally come back.")

    @api.depends('booking_id')
    def _compute_available_event_ids(self):
        """Classes this student could actually be moved into.

        Same discipline, still to come, not cancelled, and with a seat free -
        anything else would offer the desk a choice the booking rules would
        then refuse. The class they are leaving is excluded; moving somebody
        to where they already are is not a move.
        """
        for wiz in self:
            booking = wiz.booking_id
            event = booking.calendar_event_id
            if not event:
                wiz.available_event_ids = False
                continue
            domain = [
                ('is_fitness_class', '=', True),
                ('id', '!=', event.id),
                ('start', '>', fields.Datetime.now()),
                ('class_state', '!=', 'cancelled'),
            ]
            if event.class_type_id:
                domain.append(('class_type_id', '=', event.class_type_id.id))
            candidates = self.env['calendar.event'].search(domain, order='start', limit=200)
            # Capacity is a computed field, so it is filtered here rather than
            # in the domain: a full class must not be offered as an option.
            free = candidates.filtered(
                lambda e: not e.capacity or e.available_seats > 0)
            wiz.available_event_ids = [(6, 0, free.ids)]

    # ── outcomes ─────────────────────────────────────────────────────────────
    def action_cancel_only(self):
        """Cancel, and leave the student where they chose to be: nowhere."""
        self.ensure_one()
        self._do_cancel()
        return {'type': 'ir.actions.act_window_closed'}

    def action_cancel_and_assign(self):
        """Cancel, then book the same student into the class chosen above."""
        self.ensure_one()
        if not self.target_event_id:
            raise UserError(_(
                "Choose a class to move %(name)s into, or use Cancel Only.",
                name=self.student_id.name or _('this student'),
            ))
        target = self.target_event_id
        student = self.booking_id.student_id
        self._do_cancel()
        # Booked by the studio on the student's behalf, so the ordinary booking
        # rules apply to the credit but not to the booking window: the desk is
        # allowed to place somebody in a class the portal would not yet offer.
        #
        # The override is a field on the booking, not a context key - the check
        # reads vals and re-tests the group server-side, so a non-manager who
        # sends it anyway is still refused. Passing it in the context looked
        # right and did nothing.
        self.env['fitness.booking'].create({
            'student_id': student.id,
            'calendar_event_id': target.id,
            'state': 'booked',
            'manager_override_timewindow': True,
        })
        return {'type': 'ir.actions.act_window_closed'}

    def _do_cancel(self):
        booking = self.booking_id
        if booking.state == 'cancelled':
            raise UserError(_("That booking is already cancelled."))
        booking.with_context(
            _admin_cancel_direct=True,
            admin_force_refund=bool(self.restore_credit),
        ).action_cancel()
