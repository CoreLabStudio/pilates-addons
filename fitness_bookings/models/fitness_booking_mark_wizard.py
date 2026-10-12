# -*- coding: utf-8 -*-
"""Correct an attendance mark, or cancel a marked booking, with a reason.

A dialog and not a bare button, for the same reason as Give the Credit
Back: the reason is the only record anyone will have of why a mark was
changed or a class was taken back after the fact.

The wizard decides nothing. The booking's own methods re-check the
manager group, the state and the reason, because they are reachable over
RPC without ever opening this.
"""
from odoo import models, fields


class FitnessBookingMarkWizard(models.TransientModel):
    _name = 'fitness.booking.mark.wizard'
    _description = 'Correct an attendance mark'

    booking_id = fields.Many2one(
        'fitness.booking', required=True, ondelete='cascade')
    kind = fields.Selection([
        ('attended', 'Mark as Attended'),
        ('no_show', 'Mark as No-show'),
        ('cancel', 'Cancel with reason'),
    ], required=True, readonly=True)
    student_name = fields.Char(
        related='booking_id.student_id.name', readonly=True,
        string="Student")
    class_name = fields.Char(
        related='booking_id.calendar_event_id.name', readonly=True,
        string="Class")
    class_start = fields.Datetime(
        related='booking_id.calendar_event_id.start', readonly=True,
        string="Started")
    current_state = fields.Selection(
        related='booking_id.state', readonly=True, string="Marked now")
    # NOT required on the field: a NOT NULL column, and the record is
    # created before anybody has typed. The form marks it required and the
    # booking refuses a blank, which is the guard that holds over RPC.
    reason = fields.Text(
        "Why",
        help="Why this is being changed. It is written to the booking's "
             "history with your name and the time.")
    return_credit = fields.Boolean(
        "Return the credit", default=True,
        help="Give back the credit this booking spent - a pack class, a "
             "trial, a gift or a make-up credit, whichever paid for it. "
             "Untick to cancel without returning anything.")

    def action_confirm(self):
        self.ensure_one()
        booking = self.booking_id
        if self.kind == 'cancel':
            booking._cancel_marked_with_reason(
                self.reason, self.return_credit)
        else:
            booking._correct_mark(self.kind, self.reason)
        return {'type': 'ir.actions.act_window_close'}
