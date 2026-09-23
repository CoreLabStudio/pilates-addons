# -*- coding: utf-8 -*-
"""The trial request follows the booking behind it - cancelled or moved.

An approved trial is one thing wearing two faces: a place on the student's
schedule, and a request in the studio's trial list. Cancelling the booking
left the request reading Scheduled, so the list claimed a class was happening
that was not, and somebody had to go and cancel it a second time.

Moving one was the same fault in the other direction. Approval creates the
booking *on* the request's slot, so the two agree until something separates
them; the reassign wizard moved the seat, refreshed both rosters and told the
student, and left the request naming the class she had just been moved out of.
Four requests on production were in that state, and the confirmation email
quotes the request.

Hooked on the booking rather than on the class: a single student's place and
a whole class being called off both end up in fitness.booking.action_cancel,
so one hook covers both.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class FitnessBooking(models.Model):
    _inherit = 'fitness.booking'

    def write(self, vals):
        """Moving a booking moves the trial request behind it.

        Hooked on write rather than on _notify_moved, the other candidate:
        that hook lives in fitness_notifications and is skipped when
        confirmations are switched off or when the caller passes
        skip_fitness_notification. Whether the studio has emails enabled has
        nothing to do with whether its own records agree with each other, and
        tying them together would mean the request quietly stops following the
        booking the day somebody turns notifications off.

        It also covers the path the wizard does not. Typing a new class into
        calendar_event_id on the booking form skips the wizard entirely, so
        nothing fires - no notification, no rules. That happened: one student
        was moved that way and never heard about it. Whether to tell her is a
        separate question, but the records should agree either way.

        fitness.booking had no write() override of its own when this was
        written, and d132f6e added one: it recounts both events and tells the
        student. super() reaches it, so that fix still runs underneath this -
        do not stop calling super(), and do not duplicate the recount here.
        This override adds no booking rules of its own; it reads the new event
        and syncs another model.
        """
        moving = 'calendar_event_id' in vals
        # Collected before the write, while the bookings still point at the
        # class the requests name. _scheduled_behind falls back to matching on
        # student and class for anything approved before booking_id existed,
        # and that fallback can only match against the old event.
        trials = {}
        if moving:
            requests = self.env['fitness.trial.request']
            for booking in self:
                found = requests._scheduled_behind(booking)
                if found:
                    trials[booking.id] = found

        result = super().write(vals)

        for booking in self:
            found = trials.get(booking.id)
            if found:
                found._moved_with_booking(booking.calendar_event_id)
        return result

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
