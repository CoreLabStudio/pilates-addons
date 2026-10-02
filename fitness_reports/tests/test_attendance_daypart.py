# -*- coding: utf-8 -*-
"""Morning against evening, and who was paying.

Two things here are easy to get wrong and expensive to get wrong
quietly.

THE CLOCK. calendar_event.start is stored UTC; the studio reads Madrid.
Spain is UTC+2 in summer and UTC+1 in winter, so a 13:00 Madrid class is
11:00 UTC in October and 12:00 UTC in December. Bucketing on the stored
column would file it as morning for half the year and evening for the
other half, and the report would look plausible throughout. The
fixtures here build their classes in Madrid time and convert, which is
the same direction the view works in, and the boundary is tested on
both sides of the changeover.

WHO COUNTS AS PAYING. A free trial carries fitness_is_package on this
system - "Clase de prueba de Barre" is a package worth 12.00 sold at
0.00 - so "has a package" is true of somebody who has never paid the
studio anything. The view asks for a confirmed line above zero euros
instead, and both halves of that are tested: the trial student is out,
the pack buyer and the membership buyer are both in.
"""

import datetime

import pytz

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_reports.models.report_attendance_daypart import (
    MORNING_ENDS_AT, STUDIO_TZ,
)

MADRID = pytz.timezone(STUDIO_TZ)


@tagged("post_install", "-at_install")
class TestAttendanceDaypart(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        cls.room = cls.env['fitness.classroom'].sudo().create({
            'name': 'Daypart Room', 'classroom_type': 'barre',
            'capacity': 10})
        cls.barre = cls.env['fitness.class.type'].sudo().create({
            'name': 'Daypart Barre', 'classroom_type': 'barre',
            'session_type': 'group', 'level': 'all',
            'classroom_id': cls.room.id})
        cls.reformer_room = cls.env['fitness.classroom'].sudo().create({
            'name': 'Daypart Reformer Room', 'classroom_type': 'reformer',
            'capacity': 6})
        cls.reformer = cls.env['fitness.class.type'].sudo().create({
            'name': 'Daypart Reformer', 'classroom_type': 'reformer',
            'session_type': 'group', 'level': 'all',
            'classroom_id': cls.reformer_room.id})

        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'Daypart Pack', 'type': 'service', 'list_price': 75.0,
            'sale_ok': True, 'fitness_is_package': True,
            'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        cls.plan = cls.env['sale.subscription.plan'].sudo().create({
            'name': 'Daypart Mensual',
            'billing_period_value': 1, 'billing_period_unit': 'month'})
        cls.membership = cls.env['product.template'].sudo().create({
            'name': 'Daypart Membership', 'type': 'service',
            'list_price': 130.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        # Something to book WITH. Bookings need a payment source or
        # fitness.booking.create() refuses outright, and these tests are
        # about when people came, not about how they paid - so the credit
        # is free, covers either room, and lasts the year. Free on
        # purpose: it must not make anybody count as a paying client.
        cls.credit_pack = cls.env['product.template'].sudo().create({
            'name': 'Daypart Credit', 'type': 'service', 'list_price': 0.0,
            'sale_ok': True, 'fitness_is_package': True,
            'fitness_class_count': 50, 'fitness_validity_days': 365,
            'fitness_class_type': 'any', 'fitness_session_type': 'group'})
        # A package sold at nothing: the shape a free trial has, and the
        # reason "owns a package" is not the same question as "has paid".
        cls.freebie = cls.env['product.template'].sudo().create({
            'name': 'Daypart Free Trial', 'type': 'service',
            'list_price': 12.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 1,
            'fitness_validity_days': 15,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})

    # ── fixtures ─────────────────────────────────────────────────────────

    def _student(self, tag):
        return self.env['res.partner'].sudo().create(
            {'name': 'Daypart %s' % tag})

    def _credit_line(self, partner):
        """A free credit for this student, made once and reused."""
        cache = getattr(self, '_credit_cache', None)
        if cache is None:
            cache = self._credit_cache = {}
        if partner.id not in cache:
            cache[partner.id] = self._confirmed_order(
                partner, self.credit_pack, 0.0).order_line[:1]
        return cache[partner.id]

    def _utc_for(self, madrid_dt):
        """Naive UTC for a Madrid wall-clock time, the way Odoo stores it.

        Through pytz's localize rather than a fixed offset, so the test is
        measuring the same thing the view is and not a second guess at it.
        """
        return MADRID.localize(madrid_dt).astimezone(pytz.utc).replace(
            tzinfo=None)

    def _past_class(self, madrid_dt, class_type=None):
        """A class to be dated into the past, and where it is going.

        Built in the future and moved back afterwards. A booking cannot be
        created on a class that has already started - _validate_new_booking
        refuses it outright - so the booking is made while the class is
        still ahead and the pair is dated back together, which is also what
        really happens to every class in the archive.

        Returns the pair rather than hanging the target on the record:
        Odoo recordsets use __slots__ and an invented attribute raises.
        """
        # Every placeholder gets its own slot. They used to share one, and
        # a student booking two classes was then booking the same moment
        # twice - which the overlap guard correctly refused. 90 minutes
        # apart against a 55-minute class leaves no overlap to find.
        self._ph_count = getattr(self, '_ph_count', 0) + 1
        ahead = (fields.Datetime.now()
                 + datetime.timedelta(days=3)
                 + datetime.timedelta(minutes=90 * self._ph_count))
        event = self.env['calendar.event'].sudo().create({
            'name': 'Daypart class',
            'start': ahead,
            'stop': ahead + datetime.timedelta(minutes=55),
            'class_type_id': (class_type or self.barre).id,
            'is_fitness_class': True, 'capacity': 10,
        })
        return event, self._utc_for(madrid_dt)

    def _land(self, event, start):
        """Move a class into the past, where it counts as having run."""
        event.sudo().write({
            'start': start,
            'stop': start + datetime.timedelta(minutes=55),
        })

    def _book(self, partner, event, state='attended'):
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': partner.id,
            'calendar_event_id': event.id,
            # Named explicitly. Left unset, create() goes looking for a
            # source of its own and refuses when it finds none.
            'package_order_line_id': self._credit_line(partner).id,
        })
        if state != 'booked':
            booking.sudo().write({'state': state})
        return booking

    def _confirmed_order(self, partner, product, price):
        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'plan_id': self.plan.id if product == self.membership else False,
        })
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': price,
        })
        order.action_confirm()
        return order

    def _rows(self, domain=None):
        self.env.flush_all()
        return self.env['fitness.report.attendance.daypart'].sudo().search(
            domain or [])

    def _mine(self, partner):
        return self._rows([('student_id', '=', partner.id)])

    def _days_back(self, days, hour, minute=0):
        """A Madrid wall-clock datetime, N days ago."""
        today = fields.Date.context_today(self.env.user)
        return datetime.datetime.combine(
            today - datetime.timedelta(days=days),
            datetime.time(hour, minute))

    # ── the boundary ─────────────────────────────────────────────────────

    def test_just_before_the_cutoff_is_morning(self):
        p = self._student('before')
        ev, at = self._past_class(self._days_back(7, MORNING_ENDS_AT - 1, 59))
        self._book(p, ev)
        self._land(ev, at)

        rows = self._mine(p)
        self.assertEqual(len(rows), 1, "the booking is not in the report")
        self.assertEqual(
            rows.daypart, 'morning',
            "a class at %02d:59 Madrid was filed as %s"
            % (MORNING_ENDS_AT - 1, rows.daypart))

    def test_exactly_the_cutoff_is_evening(self):
        """The boundary belongs to the evening: before, or at and after."""
        p = self._student('oncutoff')
        ev, at = self._past_class(self._days_back(7, MORNING_ENDS_AT, 0))
        self._book(p, ev)
        self._land(ev, at)

        self.assertEqual(
            self._mine(p).daypart, 'evening',
            "a class starting exactly at %02d:00 was filed as morning"
            % MORNING_ENDS_AT)

    def test_the_hour_recorded_is_the_madrid_hour_not_utc(self):
        """The fault this would hide: Spain is never on UTC.

        An 08:00 Madrid class is 06:00 UTC in summer. If the view read the
        stored column the report would say 6, and every reader would
        believe the studio ran classes at six in the morning.
        """
        p = self._student('tz')
        ev, at = self._past_class(self._days_back(7, 8, 0))
        self._book(p, ev)
        self._land(ev, at)

        row = self._mine(p)
        self.assertEqual(
            row.local_hour, 8,
            "an 08:00 Madrid class is recorded as hour %d" % row.local_hour)
        self.assertNotEqual(
            row.event_id.start.hour, 8,
            "fixture wrong: the stored time is not UTC, so this proves "
            "nothing about the conversion")

    def test_the_conversion_holds_across_the_october_changeover(self):
        """CEST to CET. A fixed offset would be wrong on one side."""
        p = self._student('dst')
        # Both behind us, and either side of the October clock change:
        # 8 September 2026 is CEST (+2), 8 December 2025 is CET (+1).
        # The first version used 5 October 2026, which is in the FUTURE -
        # the report only counts classes that have finished, so that row
        # never arrived and this compared one hour against two.
        summer, summer_at = self._past_class(
            datetime.datetime(2026, 9, 8, 13, 0))
        winter, winter_at = self._past_class(
            datetime.datetime(2025, 12, 8, 13, 0))
        self._book(p, summer)
        self._book(p, winter)
        self._land(summer, summer_at)
        self._land(winter, winter_at)

        hours = sorted(self._mine(p).mapped('local_hour'))
        self.assertEqual(
            hours, [13, 13],
            "two 13:00 Madrid classes either side of the clock change were "
            "recorded as %s - a fixed offset was used somewhere" % hours)

    # ── what is left out ─────────────────────────────────────────────────

    def test_a_cancelled_booking_is_not_attendance(self):
        p = self._student('cancelled_bk')
        ev, at = self._past_class(self._days_back(7, 9))
        self._book(p, ev, state='cancelled')
        self._land(ev, at)

        self.assertFalse(
            self._mine(p),
            "a booking she cancelled is being counted as her having come")

    def test_a_cancelled_class_is_not_attendance(self):
        p = self._student('cancelled_cls')
        ev, at = self._past_class(self._days_back(7, 9))
        self._book(p, ev)
        self._land(ev, at)
        ev.sudo().write({'class_state': 'cancelled'})

        self.assertFalse(
            self._mine(p),
            "a class the studio cancelled is being counted as attendance")

    def test_an_archived_class_is_not_attendance(self):
        """Raw SQL, so Odoo's active_test never reaches it.

        On the production restore archived classes were over a third of
        every row the reports returned.
        """
        p = self._student('archived')
        ev, at = self._past_class(self._days_back(7, 9))
        self._book(p, ev)
        self._land(ev, at)
        ev.sudo().write({'active': False})

        self.assertFalse(
            self._mine(p),
            "a class taken off the timetable is still being counted")

    def test_a_class_still_to_come_is_not_attendance(self):
        p = self._student('future')
        ahead = fields.Datetime.now() + datetime.timedelta(days=3)
        ev = self.env['calendar.event'].sudo().create({
            'name': 'Daypart future', 'start': ahead,
            'stop': ahead + datetime.timedelta(minutes=55),
            'class_type_id': self.barre.id,
            'is_fitness_class': True, 'capacity': 10})
        self._book(p, ev, state='booked')

        self.assertFalse(
            self._mine(p),
            "a class that has not happened yet is counted as attendance")

    def test_a_no_show_still_held_the_seat(self):
        """Counted, and counted separately. Both numbers are wanted."""
        p = self._student('noshow')
        ev, at = self._past_class(self._days_back(7, 9))
        self._book(p, ev, state='no_show')
        self._land(ev, at)

        row = self._mine(p)
        self.assertEqual(
            row.attendance_count, 1,
            "a no-show took a seat nobody else could have and is not "
            "counted as demand for that hour")
        self.assertEqual(
            row.attended_count, 0,
            "a no-show is being counted as having turned up")

    # ── paying students ──────────────────────────────────────────────────

    def _attended_row(self, tag):
        p = self._student(tag)
        ev, at = self._past_class(self._days_back(7, 9))
        self._book(p, ev)
        self._land(ev, at)
        return p

    def test_a_pack_buyer_counts_as_paying(self):
        p = self._attended_row('packbuyer')
        self._confirmed_order(p, self.pack, 75.0)

        self.assertTrue(
            self._mine(p).is_paying,
            "a student whose only purchase is a pack is not counted as "
            "a paying client")

    def test_a_membership_buyer_counts_as_paying(self):
        p = self._attended_row('memberbuyer')
        self._confirmed_order(p, self.membership, 130.0)

        self.assertTrue(
            self._mine(p).is_paying,
            "a student whose only purchase is a membership is not counted "
            "as a paying client")

    def test_a_free_trial_does_not_make_her_paying(self):
        """The case that makes 'owns a package' the wrong question."""
        p = self._attended_row('trialonly')
        self._confirmed_order(p, self.freebie, 0.0)

        self.assertFalse(
            self._mine(p).is_paying,
            "a student whose only order is a free trial is counted as "
            "paying - the trial is a package on this system, which is why "
            "the test is the amount and not the product")

    def test_a_gift_does_not_make_her_paying(self):
        p = self._attended_row('giftonly')
        self._confirmed_order(p, self.pack, 0.0)

        self.assertFalse(
            self._mine(p).is_paying,
            "a pack given away at zero is being counted as a purchase")

    def test_a_student_who_was_only_ever_given_classes_is_not_paying(self):
        """She has an order - for nothing. That is not a purchase."""
        p = self._attended_row('nothing')

        self.assertFalse(
            self._mine(p).is_paying,
            "a student whose only order is worth 0.00 is counted as paying")

    def test_an_unconfirmed_order_does_not_count(self):
        """A quotation is not a sale."""
        p = self._attended_row('quoteonly')
        order = self.env['sale.order'].sudo().create({'partner_id': p.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 75.0})

        self.assertFalse(
            self._mine(p).is_paying,
            "a draft quotation is being counted as a purchase")


    # -- membership against pack -------------------------------------------

    def test_a_membership_buyer_is_flagged_as_one(self):
        p = self._attended_row('onlymember')
        self._confirmed_order(p, self.membership, 130.0)

        row = self._mine(p)
        self.assertTrue(
            row.paid_membership, "her membership is not recorded as one")
        self.assertFalse(
            row.paid_pack,
            "she has never bought a pack and is counted as a pack buyer")

    def test_a_pack_buyer_is_flagged_as_one(self):
        p = self._attended_row('onlypack')
        self._confirmed_order(p, self.pack, 75.0)

        row = self._mine(p)
        self.assertTrue(row.paid_pack, "her pack is not recorded as one")
        self.assertFalse(
            row.paid_membership,
            "she has never bought a membership and is counted as a member")

    def test_somebody_who_bought_both_is_in_both(self):
        """The case a single payment_kind column gets wrong.

        Forced into one bucket she would be missing from the other, and
        the studio would be told fewer members or fewer pack buyers than
        it has - silently, because the combined figure would still look
        right.
        """
        p = self._attended_row('boughtboth')
        self._confirmed_order(p, self.membership, 130.0)
        self._confirmed_order(p, self.pack, 75.0)

        row = self._mine(p)
        self.assertTrue(
            row.paid_membership,
            "she bought a membership and a pack, and the membership was "
            "lost")
        self.assertTrue(
            row.paid_pack,
            "she bought a membership and a pack, and the pack was lost")
        self.assertTrue(row.is_paying, "she paid for two things and "
                                       "counts as paying for neither")

    def test_the_two_flags_do_not_double_count_the_combined_figure(self):
        """Counted once in the total, in both of the halves.

        Stated as a test because it is the thing somebody reading the
        pivot will query: membership + pack is larger than paying, and
        that is correct, not a bug.
        """
        p = self._attended_row('bothcount')
        self._confirmed_order(p, self.membership, 130.0)
        self._confirmed_order(p, self.pack, 75.0)

        rows = self._mine(p)
        self.assertEqual(
            len(rows), 1,
            "buying two things duplicated her booking in the report")
        self.assertEqual(
            len(rows.filtered('is_paying')), 1,
            "she is counted %d times in the combined figure"
            % len(rows.filtered('is_paying')))

    def test_a_free_trial_flags_neither(self):
        """The negative that keeps the amount doing the work."""
        p = self._attended_row('freeonly')
        self._confirmed_order(p, self.freebie, 0.0)

        row = self._mine(p)
        self.assertFalse(
            row.paid_membership, "a free trial counted as a membership")
        self.assertFalse(
            row.paid_pack,
            "a free trial counted as a pack - the trial IS a package on "
            "this system, so the test has to be the money")

    def test_the_class_name_is_available_to_group_by(self):
        """She asked to see which individual classes are busy when.

        class_type_id is what the pivot groups on, so it has to survive
        onto the row - not just the room.
        """
        p = self._student('named')
        ev, at = self._past_class(self._days_back(7, 9), self.reformer)
        self._book(p, ev)
        self._land(ev, at)

        row = self._mine(p)
        self.assertEqual(
            row.class_type_id, self.reformer,
            "the row lost which class it was, so the per-class breakdown "
            "cannot be built")
        self.assertEqual(row.discipline, 'reformer')

    # ── the split itself ─────────────────────────────────────────────────

    def test_the_two_buckets_add_up_and_split_by_room(self):
        p = self._student('split')
        q = self._student('split2')
        morning, morning_at = self._past_class(
            self._days_back(7, 9), self.barre)
        evening, evening_at = self._past_class(
            self._days_back(7, 19), self.reformer)
        self._book(p, morning)
        self._book(q, morning)
        self._book(p, evening)
        self._land(morning, morning_at)
        self._land(evening, evening_at)

        rows = self._rows([('student_id', 'in', (p | q).ids)])
        self.assertEqual(len(rows), 3, "expected 3 bookings, got %d"
                         % len(rows))
        by_part = {}
        for r in rows:
            by_part.setdefault(r.daypart, []).append(r)
        self.assertEqual(
            len(by_part.get('morning', [])), 2,
            "two 09:00 bookings were not both filed as morning")
        self.assertEqual(
            len(by_part.get('evening', [])), 1,
            "one 19:00 booking was not filed as evening")
        self.assertEqual(
            set(r.discipline for r in by_part['morning']), {'barre'},
            "the morning Barre classes lost their room")
        self.assertEqual(
            by_part['evening'][0].discipline, 'reformer',
            "the evening Reformer class lost its room")
