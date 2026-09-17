# -*- coding: utf-8 -*-
"""Cancelling a booking cancels the trial request behind it.

An approved trial is one thing wearing two faces: a place on the student's
schedule, and a request in the studio's trial list. Cancelling the booking
left the request reading Scheduled, so the list claimed a class was happening
that was not, and somebody had to go and cancel it a second time.

Hooked on the booking rather than on the class: a single student's place and
a whole class being called off both end up in fitness.booking.action_cancel,
so one hook covers both.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class FitnessBooking(models.Model):
    _inherit = 'fitness.booking'

    def action_cancel(self):
        # Collected before the cancellation, while the bookings are still the
        # ones the requests point at.
        trials = self.env['fitness.trial.request'].browse()
        if not self.env.context.get('_trial_request_declining'):
            trials = self.env['fitness.trial.request']._scheduled_behind(self)

        result = super().action_cancel()

        # After, and only for bookings that actually ended up cancelled: a
        # refusal further down must not leave the request saying the class is
        # off when the student still has their place.
        if trials:
            cancelled = self.filtered(lambda b: b.state == 'cancelled')
            if cancelled:
                trials.filtered(
                    lambda r: r._find_booking() in cancelled
                    or not r._find_booking()
                )._cancelled_with_booking()
        return result
