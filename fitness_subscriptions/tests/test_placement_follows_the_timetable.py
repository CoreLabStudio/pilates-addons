# -*- coding: utf-8 -*-
"""A member's slot keeps getting booked as the timetable extends.

Placement only ever booked the classes that already existed the moment
she bought. The timetable is generated about eight weeks ahead, so a
quarterly membership got roughly five weeks of its thirteen and nothing
ever came back for the rest.

Measured on production on 2026-10-01: Laura Bucur, 195.00 for three
months from 5 October, five classes placed against twelve. Nobody was
told - not her, not the studio. She would simply have stopped having
classes in November.

The nightly job closes that. What these pin is the behaviour nobody
would notice the absence of:

  * it places classes that did not exist at purchase;
  * it does not rebook a week the student cancelled;
  * it does not book into the past, which matters because placement
    deliberately bypasses the "class has already started" guard;
  * one full class does not stop every member after it, which is why
    the job cannot use the raising wrapper;
  * and running it twice changes nothing.
"""

import datetime

from odoo import fields
from odoo.tests import TransactionCase, tagged

WEEKS_AHEAD_AT_PURCHASE = 2
WEEKS_LATER = 10


@tagged("post_install", "-at_install")
class TestPlacementFollowsTheTimetable(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        cls.room = cls.env['fitness.classroom'].sudo().create({
            'name': 'Horizon Room', 'classroom_type': 'reformer',
            'capacity': 6})
        cls.class_type = cls.env['fitness.class.type'].sudo().create({
            'name': 'Horizon Reformer', 'classroom_type': 'reformer',
            'session_type': 'group', 'level': 'all',
            'classroom_id': cls.room.id})
        cls.plan = cls.env['sale.subscription.plan'].sudo().create({
            'name': 'Horizon Trimestral',
            'billing_period_value': 3, 'billing_period_unit': 'month'})
        cls.product = cls.env['product.template'].sudo().create({
            'name': 'Horizon Fixed Class 1', 'type': 'service',
            'list_price': 195.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True,
            'recurring_invoice': True,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
            'weekly_class_allowance': 1})
        cls.student = cls.env['res.partner'].sudo().create(
            {'name': 'Horizon Student'})
        cls.teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Horizon Teacher",
                "login": "horizon.teacher@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })

    # -- helpers ----------------------------------------------------------

    def _schedule(self, horizon_weeks, start_date=None, weekday='tue'):
        """A real weekly schedule, generated the way the studio's is.

        Hand-made calendar.event records do NOT work here, and the first
        version of these tests was written with them. Placement finds a
        slot's other occurrences through recurrence_id, not by weekday:
        with no recurrence the domain falls back to the anchor event
        alone, so the nightly job placed exactly one class and reported
        nothing to do. The fixture has to be a schedule, because that is
        what makes classes on production.
        """
        sched = self.env['fitness.class.schedule'].sudo().create({
            'name': 'Horizon weekly',
            'class_type_id': self.class_type.id,
            'classroom_id': self.room.id,
            'weekday': weekday,
            'start_time': 8.0,
            'duration': 1.0,
            'date_start': start_date or fields.Date.context_today(self.env.user),
            'horizon_weeks': horizon_weeks,
            # teacher_user_id is NOT NULL on fitness.class.schedule. A
            # fixture without one does not fail an assertion, it fails the
            # INSERT, and every test in the class errors on setup.
            "teacher_user_id": self.teacher.id,
        })
        sched.action_generate()
        return sched

    def _occurrences(self, sched):
        return self.env['calendar.event'].sudo().search(
            [('recurrence_id', '=', sched.recurrence_id.id)], order='start')

    def _extend_to(self, sched, horizon_weeks):
        """What fitness_core's nightly schedule job does."""
        sched.sudo().write({'horizon_weeks': horizon_weeks})
        sched.sudo()._extend()
        return self._occurrences(sched)

    def _subscription(self, anchor_event):
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student.id, 'plan_id': self.plan.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 195.0})
        order.action_confirm()
        self.env['fitness.clase.fija'].sudo().create({
            'subscription_id': order.id,
            'calendar_event_id': anchor_event.id})
        return order

    def _bookings(self, order):
        return self.env['fitness.booking'].sudo().search(
            [('subscription_id', '=', order.id)])

    # -- the fault ---------------------------------------------------------

    def test_classes_made_after_she_bought_are_placed(self):
        """The whole point: the timetable moves, and she moves with it."""
        sched = self._schedule(WEEKS_AHEAD_AT_PURCHASE)
        made = self._occurrences(sched)
        self.assertTrue(made, "the schedule generated nothing; fixture wrong")
        order = self._subscription(made[0])
        order._fitness_place_slots()
        at_purchase = len(self._bookings(order))
        self.assertTrue(
            at_purchase, "nothing was placed at all; fixture wrong")

        # What fitness_core's nightly job does: push the horizon out.
        self._extend_to(sched, WEEKS_AHEAD_AT_PURCHASE + WEEKS_LATER)
        self.env['sale.order']._cron_place_fixed_classes()

        after = len(self._bookings(order))
        self.assertGreater(
            after, at_purchase,
            "the timetable grew by %d weeks and she was placed into none "
            "of them. She holds %d classes of a three-month membership "
            "and nothing will ever come back for the rest."
            % (WEEKS_LATER, after))

    def test_running_it_twice_changes_nothing(self):
        sched = self._schedule(4)
        order = self._subscription(self._occurrences(sched)[0])
        self.env['sale.order']._cron_place_fixed_classes()
        once = len(self._bookings(order))

        self.env['sale.order']._cron_place_fixed_classes()

        self.assertEqual(
            len(self._bookings(order)), once,
            "a second run booked her in again; the job is not idempotent "
            "and it runs every night")

    def test_a_week_she_cancelled_is_not_rebooked(self):
        """Otherwise the job undoes her own decision, nightly."""
        sched = self._schedule(4)
        events = self._occurrences(sched)
        order = self._subscription(events[0])
        self.env['sale.order']._cron_place_fixed_classes()

        dropped = self._bookings(order).filtered(
            lambda b: b.calendar_event_id == events[2])
        self.assertTrue(dropped, "fixture wrong: that week was not booked")
        dropped.write({'state': 'cancelled'})

        self.env['sale.order']._cron_place_fixed_classes()

        again = self._bookings(order).filtered(
            lambda b: b.calendar_event_id == events[2]
            and b.state != 'cancelled')
        self.assertFalse(
            again, "the week she called off was booked again overnight")

    def test_it_does_not_book_into_the_past(self):
        """Placement bypasses the 'already started' guard on purpose.

        Right when a quarter is set up in one go; wrong for a job that
        runs every night and would book yesterday.
        """
        # A schedule that started three weeks ago, so its first
        # occurrences are behind us and its later ones are not.
        started = fields.Date.context_today(self.env.user) \
            - datetime.timedelta(weeks=3)
        sched = self._schedule(8, start_date=started)
        events = self._occurrences(sched)
        now = fields.Datetime.now()
        gone = events.filtered(lambda e: e.start < now)
        coming = events.filtered(lambda e: e.start >= now)
        self.assertTrue(
            gone and coming,
            "fixture wrong: need occurrences on both sides of now")

        order = self._subscription(coming[0])
        self.env['sale.order']._cron_place_fixed_classes()

        booked_past = self._bookings(order).filtered(
            lambda b: b.calendar_event_id in gone)
        self.assertFalse(
            booked_past,
            "the nightly job booked her into %d class(es) that have "
            "already happened" % len(booked_past))
        self.assertTrue(
            self._bookings(order),
            "it booked nothing at all; the future occurrences were "
            "skipped too")

    # -- one bad member must not stop the rest -----------------------------

    def test_a_full_class_does_not_stop_everybody_else(self):
        """The reason the job cannot use the raising wrapper."""
        sched = self._schedule(3)
        events = self._occurrences(sched)

        blocked_student = self.env['res.partner'].sudo().create(
            {'name': 'Horizon Blocked'})
        other = self.env['sale.order'].sudo().create({
            'partner_id': blocked_student.id, 'plan_id': self.plan.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': other.id,
            'product_id': self.product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 195.0})
        other.action_confirm()
        self.env['fitness.clase.fija'].sudo().create({
            'subscription_id': other.id,
            'calendar_event_id': events[0].id})
        # Fill her first class so placing her must fail somewhere.
        events[0].sudo().write({'capacity': 0})

        order = self._subscription(events[0])

        self.env['sale.order']._cron_place_fixed_classes()

        self.assertTrue(
            self._bookings(order),
            "a class that was full for one member left another member "
            "with nothing placed. The job must carry on past a failure - "
            "that is why it does not use the raising wrapper.")
