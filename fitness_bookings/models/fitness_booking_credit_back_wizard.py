# -*- coding: utf-8 -*-
"""Give a credit back on a booking that was cancelled late.

Deliberately a dialog and not a bare button. The reason is the only
record anyone will have of why a credit was returned against the policy,
and a button with no reason is how a studio ends up unable to explain its
own numbers three months later.
"""
from odoo import models, fields


class FitnessBookingCreditBackWizard(models.TransientModel):
    _name = 'fitness.booking.credit.back.wizard'
    _description = 'Give a credit back after a late cancellation'

    booking_id = fields.Many2one(
        'fitness.booking', required=True, ondelete='cascade')
    student_name = fields.Char(
        related='booking_id.student_id.name', readonly=True,
        string="Student")
    class_name = fields.Char(
        related='booking_id.calendar_event_id.name', readonly=True,
        string="Class")
    class_start = fields.Datetime(
        related='booking_id.calendar_event_id.start', readonly=True,
        string="Started")
    cancelled_on = fields.Datetime(
        related='booking_id.cancellation_date', readonly=True,
        string="Cancelled")
    # NOT required on the field: that is a NOT NULL column, and the
    # action creates this record before anybody has typed anything.
    # The form marks it required and _give_credit_back refuses a blank,
    # which is the guard that holds over RPC as well.
    reason = fields.Text(
        "Why",
        help="Why the studio is returning a credit the policy says was "
             "forfeited. It is the only record anyone will have of it.")

    def action_confirm(self):
        self.ensure_one()
        # The booking re-checks the manager group and every precondition
        # for itself: _give_credit_back is reachable over RPC.
        self.booking_id._give_credit_back(self.reason)
        return {'type': 'ir.actions.act_window_close'}
