# -*- coding: utf-8 -*-
"""A booking a test can build for itself, instead of borrowing one.

Several suites used to open with

    booking = self.env['fitness.booking'].search([], limit=1)
    if not booking:
        self.skipTest("no booking on this database to render against")

which meant they ran on the production restore and skipped on every fresh
database - and a skip reads as a pass while testing nothing. Twenty-one
tests across three modules were silent that way, including the whole
cancellation-policy wording set.

Lives in fitness_bookings because fitness_notifications,
fitness_teacher_swap and fitness_portal all depend on it, so none of them
gains a dependency by importing this.

Nothing here reads the clock beyond "now": the class is built at an
explicit hour tomorrow, because a class in the past is refused outright
by _validate_new_booking, and an hour-of-day that comes from when the
suite happens to run is how a test passes all morning and fails all
afternoon.
"""
from datetime import timedelta

from odoo import fields


class BookingFixture:
    """Mix in beside TransactionCase or HttpCase."""

    #: bumped per booking so repeated calls cannot collide on login
    _booking_fixture_seq = 0

    def _a_booking(self, tag=None, hours_ahead=24, student=None):
        """One student, one future class, and her seat in it."""
        cls = type(self)
        cls._booking_fixture_seq += 1
        tag = tag or 'fx%d' % cls._booking_fixture_seq

        classroom = self.env['fitness.classroom'].sudo().create({
            'name': 'Fixture Room %s' % tag,
            'classroom_type': 'reformer',
            'capacity': 8,
        })
        class_type = self.env['fitness.class.type'].sudo().create({
            'name': 'Fixture Reformer %s' % tag,
            'classroom_type': 'reformer',
            'session_type': 'group',
            'level': 'all',
            'classroom_id': classroom.id,
        })
        start = (fields.Datetime.now()
                 + timedelta(hours=hours_ahead)).replace(
                     minute=0, second=0, microsecond=0)
        event = self.env['calendar.event'].sudo().create({
            'name': 'Fixture class %s' % tag,
            'start': start,
            'stop': start + timedelta(minutes=55),
            'class_type_id': class_type.id,
            'is_fitness_class': True,
            'capacity': 8,
        })
        if student is None:
            student = self.env['res.users'].with_context(
                no_reset_password=True).create({
                    'name': 'Fixture Student %s' % tag,
                    'login': 'fixture.%s@example.invalid' % tag,
                    'email': 'fixture.%s@example.invalid' % tag,
                    'group_ids': [(6, 0, [
                        self.env.ref('base.group_portal').id,
                        self.env.ref(
                            'fitness_core.group_fitness_student').id])],
                })
        return self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id,
            'calendar_event_id': event.id,
        })
