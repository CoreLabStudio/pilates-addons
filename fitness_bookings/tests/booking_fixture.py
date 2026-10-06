# -*- coding: utf-8 -*-
"""A booking a test can build for itself, instead of borrowing one.

Several suites used to open with

    booking = self.env['fitness.booking'].search([], limit=1)
    if not booking:
        self.skipTest("no booking on this database to render against")

which meant they ran on the production restore and skipped on every fresh
database - and a skip reads as a pass while testing nothing. Sixteen
tests across three modules were silent that way, including the whole
cancellation-policy wording set.

Lives in fitness_bookings because fitness_notifications,
fitness_teacher_swap and fitness_portal all depend on it, so none of them
gains a dependency by importing this.

A SEAT IS NOT FREE. The first version of this fixture created a student,
a class and a booking, and nothing else - and every test using it errored
with "No active subscription or package covers this class type".
_select_payment_source() requires a confirmed package line that covers
the class's studio and session type and still has credits on it. On the
restore the borrowed bookings had real packages behind them, so only a
fresh database showed it. The lesson is the fixture's, not the product's:
a booking without something paying for it is not a booking the app would
ever have made.

Three sources are offered, because what a student paid with changes what
the emails and screens say about her credit:

    'pack'   a full-price ten-class package
    'trial'  a single class at a total of zero - the free trial
    'gift'   a courtesy package the studio gave her, also at zero

Nothing here reads the clock beyond "now": the class is built at an
explicit hour tomorrow, because a class in the past is refused outright
by _validate_new_booking, and an hour-of-day that comes from when the
suite happens to run is how a test passes all morning and fails all
afternoon.
"""
from datetime import timedelta

from odoo import fields

#: the courtesy products the gift wizard itself gives away
COURTESY = {
    'reformer': 'fitness_packages.product_courtesy_reformer',
    'barre': 'fitness_packages.product_courtesy_barre',
}

SOURCES = ('pack', 'trial', 'gift')


class BookingFixture:
    """Mix in beside TransactionCase or HttpCase."""

    #: bumped per booking so repeated calls cannot collide on login
    _booking_fixture_seq = 0

    def _a_booking(self, tag=None, hours_ahead=24, student=None,
                   source='pack', studio='reformer'):
        """One student, one future class, something that pays for it, and
        her seat in it.

        Returns the fitness.booking. The order line behind it is reachable
        as booking.package_order_line_id for a test that wants to assert on
        what was spent.
        """
        assert source in SOURCES, 'unknown payment source %r' % source
        cls = type(self)
        cls._booking_fixture_seq += 1
        tag = tag or 'fx%d' % cls._booking_fixture_seq

        classroom = self.env['fitness.classroom'].sudo().create({
            'name': 'Fixture Room %s' % tag,
            'classroom_type': studio,
            'capacity': 8,
        })
        class_type = self.env['fitness.class.type'].sudo().create({
            'name': 'Fixture %s %s' % (studio, tag),
            'classroom_type': studio,
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
        line = self._a_payment_source(student.partner_id, source, studio, tag)
        return self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': line.id,
        })

    def _a_payment_source(self, partner, source, studio, tag):
        """A CONFIRMED package line with credits left on it.

        Confirmed matters: fitness_remaining_classes only counts against a
        confirmed order, so a quotation here would leave the booking with
        nothing to spend and raise the same UserError as no line at all.
        """
        product, price = self._source_product(source, studio, tag)
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            'price_unit': price,
        })
        order.action_confirm()
        return order.order_line[:1]

    def _source_product(self, source, studio, tag):
        """(product.template, price_unit) for each kind of credit."""
        if source == 'gift':
            # The studio's own courtesy product, the one the gift wizard
            # gives away, so this really is the gift path and not a pack
            # with the price typed to zero. If the database has not got
            # it, fall back and say so in the product name rather than
            # pretending.
            courtesy = self.env.ref(COURTESY.get(studio, ''),
                                    raise_if_not_found=False)
            if courtesy:
                return courtesy, 0.0
            return self._a_pack('Gift (no courtesy product here) %s' % tag,
                                studio, classes=1), 0.0
        if source == 'trial':
            return self._a_pack('Fixture Trial %s' % tag, studio,
                                classes=1), 0.0
        return self._a_pack('Fixture Pack %s' % tag, studio,
                            classes=10), 100.0

    def _a_pack(self, name, studio, classes):
        return self.env['product.template'].sudo().create({
            'name': name,
            'type': 'service',
            'list_price': 100.0,
            'sale_ok': True,
            'fitness_is_package': True,
            'fitness_class_count': classes,
            'fitness_validity_days': 90,
            # Must match the class: _select_payment_source compares the
            # line's pool against the event's studio, and the product's
            # session type against the event's.
            'fitness_class_type': studio,
            'fitness_session_type': 'group',
        })
