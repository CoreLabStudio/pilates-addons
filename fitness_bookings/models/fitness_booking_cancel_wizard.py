from odoo import models, fields


class FitnessBookingCancelWizard(models.TransientModel):
    _name = 'fitness.booking.cancel.wizard'
    _description = 'Admin Late Cancellation'

    booking_id = fields.Many2one('fitness.booking', required=True, ondelete='cascade')
    student_name = fields.Char(related='booking_id.student_id.name', readonly=True, string='Student')
    class_name = fields.Char(related='booking_id.calendar_event_id.name', readonly=True, string='Class')
    class_start = fields.Datetime(related='booking_id.calendar_event_id.start', readonly=True, string='Start Time')
    restore_credit = fields.Boolean(
        'Restore Credit', default=False,
        help='Return the student\'s credit even though this cancellation is within 2 hours of class.',
    )

    def action_confirm(self):
        self.ensure_one()
        ctx = dict(self.env.context, _admin_cancel_direct=True)
        if self.restore_credit:
            ctx['admin_force_refund'] = True
        self.booking_id.with_context(ctx).action_cancel()
        return {'type': 'ir.actions.act_window_close'}
