# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    """Cancelling a class has to reach the people holding a trial on it.

    The studio's cancellation flow works through bookings: it cancels them,
    returns the credit and tells the student. A trial booked from the public
    form is not a booking yet - it is a fitness.trial.request holding a slot,
    and the booking only exists once someone presses "Approve and book". So
    the one person who had heard nothing was the one who had never been to the
    studio before: their first class was cancelled and the cancellation flow
    had no record of them to notify.
    """
    _inherit = 'calendar.event'

    def action_cancel_class(self):
        # Read the affected requests before super() runs, while the slot is
        # still attached to a class that exists.
        Trial = self.env['fitness.trial.request'].sudo()
        pending = Trial.search([
            ('occurrence_id', 'in', self.ids),
            ('status', 'in', ('scheduled', 'contacted')),
        ])

        result = super().action_cancel_class()

        for req in pending:
            # Someone whose request was already approved holds a real booking,
            # and the booking flow has just told them. Telling them twice about
            # one cancellation is worse than saying nothing.
            if req.partner_id and self.env['fitness.booking'].sudo().search_count([
                ('student_id', '=', req.partner_id.id),
                ('calendar_event_id', '=', req.occurrence_id.id),
            ]):
                continue
            req._send_cancelled_email()
            # Hand them back to the studio's queue rather than leaving them
            # pointing at a class that is not happening.
            req.write({
                'status': 'pending',
                'occurrence_id': False,
                'scheduled_datetime': False,
            })
            _logger.info(
                "[TRIAL] Class cancelled: request %s returned to pending and "
                "%s was told", req.id, req.email)
        return result
