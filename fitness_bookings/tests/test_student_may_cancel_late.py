# -*- coding: utf-8 -*-
"""A student may cancel until the class starts, and forfeits inside the window.

She used to be refused inside the cancellation window, which contradicted
the studio's own Terms - printed in every booking email and on the
confirmation screen - that say a late cancellation forfeits the credit.
The app said she could not cancel at all, so the seat stayed taken, she
did not come, and nobody else could have it.

NO CANCELLATION RULE CHANGES HERE. Outside the window the credit comes
back; inside it does not; for a pack, an allowance and a make-up credit
alike. The only difference is that she is allowed to do the thing the
Terms already told her the consequence of.

The refusal that remains is the one the window check was also quietly
providing: a class that has already started cannot be cancelled by her.
"""
from datetime import datetime, timedelta

import pytz

from odoo import fields
from odoo.addons.fitness_bookings.exceptions import LateCancellationError
from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
MANAGER = "fitness_core.group_fitness_manager"
TEACHER = "fitness_core.group_fitness_teacher"
STUDENT = "fitness_core.group_fitness_student"


def _utc(local_naive):
    """A Madrid wall clock reading, as the naive UTC the database holds."""
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class LateCancelFixture(TransactionCase):

    longMessage = False
    PINNED = datetime(2026, 11, 4, 10, 0, 0)     # a plain Wednesday

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(_utc(self.PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        self.window = self.env["fitness.booking"].sudo(
            )._cancellation_window_hours()
        self.class_type = self.env["fitness.class.type"].create({
            "name": "LC Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group"})
        self.pack = self.env["product.template"].create({
            "name": "LC Reformer pack 5", "list_price": 100.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 120,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group"})
        self.plan_month = self.env.ref(
            "sale_subscription.subscription_plan_month")
        self.plan = self.env["product.template"].create({
            "name": "LC Reformer 2 a week", "list_price": 90.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "reformer", "fitness_session_type": "group",
            "weekly_class_allowance": 2})

    # -- people and things -------------------------------------------
    def _student(self, tag):
        return self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "LC %s" % tag,
                "login": "lc.%s@example.invalid" % tag,
                "lang": "en_US", "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref(STUDENT).id])]})

    def _manager(self):
        return self.env["res.users"].create({
            "name": "LC Manager", "login": "lc.manager@example.invalid",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref(MANAGER).id])]})

    def _packline(self, user):
        order = self.env["sale.order"].sudo().create({
            "partner_id": user.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
                "fitness_class_type": "reformer"})]})
        order.action_confirm()
        return order.order_line[:1]

    def _membership(self, user):
        order = self.env["sale.order"].sudo().create({
            "partner_id": user.partner_id.id, "plan_id": self.plan_month.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.plan.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 90.0})
        order.action_confirm()
        today = fields.Date.context_today(user.partner_id)
        order.write({"start_date": today,
                     "next_invoice_date": today + timedelta(weeks=8)})
        return order

    def _class(self, hours_from_now, name="LC class"):
        start = fields.Datetime.now() + timedelta(hours=hours_from_now)
        return self.env["calendar.event"].sudo().create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id, "is_fitness_class": True,
            "capacity": 6, "session_type": "group"})

    def _book(self, user, event, **extra):
        vals = {"student_id": user.partner_id.id,
                "calendar_event_id": event.id}
        vals.update(extra)
        return self.env["fitness.booking"].sudo().create(vals)

    @staticmethod
    def _left(line):
        line.invalidate_recordset()
        return line.fitness_remaining_classes


@tagged("post_install", "-at_install")
class TestSheMayCancelLateAndForfeits(LateCancelFixture):

    def test_she_can_now_cancel_inside_the_window(self):
        user = self._student("inside")
        line = self._packline(user)
        event = self._class(self.window - 2)
        booking = self._book(user, event)

        booking.with_user(user).action_cancel()
        self.assertEqual(
            booking.state, "cancelled",
            "she is still refused inside the window, so the seat stays "
            "taken and nobody else can have it")

    def test_and_she_forfeits_her_pack_credit(self):
        user = self._student("forfeitpack")
        line = self._packline(user)
        booking = self._book(user, self._class(self.window - 2))
        # After the booking has spent it: a forfeit leaves this untouched.
        spent = self._left(line)

        booking.with_user(user).action_cancel()
        self.assertFalse(
            booking.credit_returned,
            "a late cancellation says the credit came back")
        self.assertEqual(
            self._left(line), spent,
            "the credit was returned on a late cancellation, which is not "
            "what the Terms say")

    def test_an_allowance_booking_forfeits_too(self):
        user = self._student("forfeitallow")
        order = self._membership(user)
        booking = self._book(user, self._class(self.window - 2))
        self.assertFalse(booking.fitness_used_floating_credit)

        booking.with_user(user).action_cancel()
        order.invalidate_recordset()
        self.assertEqual(
            order.fitness_floating_credits, 0,
            "a late cancellation earned a make-up credit, which it must "
            "not - that is the compensation for cancelling IN time")

    def test_a_makeup_credit_booking_forfeits_too(self):
        user = self._student("forfeitmakeup")
        order = self._membership(user)
        for n, h in enumerate((30, 31)):
            self._book(user, self._class(h, "LC fill %d" % n))
        order.sudo().fitness_floating_credits = 1

        booking = self._book(user, self._class(self.window - 2))
        self.assertTrue(booking.fitness_used_floating_credit)
        order.invalidate_recordset()
        self.assertEqual(order.fitness_floating_credits, 0)

        booking.with_user(user).action_cancel()
        order.invalidate_recordset()
        self.assertEqual(
            order.fitness_floating_credits, 0,
            "the make-up credit came back on a LATE cancellation")

    def test_the_seat_is_released(self):
        user = self._student("seat")
        self._packline(user)
        event = self._class(self.window - 2)
        before = event.booked_seats
        booking = self._book(user, event)
        event.invalidate_recordset()
        self.assertEqual(event.booked_seats, before + 1)

        booking.with_user(user).action_cancel()
        event.invalidate_recordset()
        self.assertEqual(
            event.booked_seats, before,
            "the seat was not released, so she did not come AND nobody "
            "else could book it - the whole reason for this change")

    # == outside the window is untouched =============================
    def test_outside_the_window_the_credit_still_comes_back(self):
        user = self._student("outside")
        line = self._packline(user)
        booking = self._book(user, self._class(self.window + 2))
        spent = self._left(line)

        booking.with_user(user).action_cancel()
        self.assertTrue(booking.credit_returned)
        self.assertEqual(
            self._left(line), spent + 1,
            "cancelling in good time stopped returning the credit")


@tagged("post_install", "-at_install")
class TestTheClassStartedBoundary(LateCancelFixture):
    """The refusal that replaced the window check, to the minute."""

    def _attempt(self, minutes_from_now, tag):
        user = self._student(tag)
        self._packline(user)
        # Booked while it is still in the future, then the clock catches
        # up - a booking cannot be made for a class that has started.
        event = self._class(self.window + 2, "LC boundary %s" % tag)
        booking = self._book(user, event)
        start = fields.Datetime.now() + timedelta(minutes=minutes_from_now)
        event.sudo().write({"start": start,
                            "stop": start + timedelta(minutes=50)})
        booking.invalidate_recordset()
        return user, booking

    def test_one_minute_before_the_start_she_may_cancel(self):
        user, booking = self._attempt(1, "beforeone")
        booking.with_user(user).action_cancel()
        self.assertEqual(
            booking.state, "cancelled",
            "she was refused with a minute still to go")

    def test_at_the_exact_start_time_she_is_refused(self):
        user, booking = self._attempt(0, "exact")
        with self.assertRaises(LateCancellationError):
            booking.with_user(user).action_cancel()
        self.assertEqual(booking.state, "booked")

    def test_one_minute_after_the_start_she_is_refused(self):
        user, booking = self._attempt(-1, "afterone")
        with self.assertRaises(LateCancellationError):
            booking.with_user(user).action_cancel()
        self.assertEqual(
            booking.state, "booked",
            "she cancelled a class that had already begun")

    def test_a_manager_may_still_cancel_a_started_class(self):
        """The refusal is student-side only, as the window one was."""
        user, booking = self._attempt(-1, "mgrstarted")
        manager = self._manager()
        booking.with_user(manager).with_context(
            _admin_cancel_direct=True).action_cancel()
        self.assertEqual(booking.state, "cancelled")


@tagged("post_install", "-at_install")
class TestTheBoundaryAcrossTheClockChange(LateCancelFixture):
    """The same boundary on the far side of the 25 October clock change.

    Europe/Madrid leaves summer time on 25 Oct 2026. A boundary measured
    in elapsed hours must not move with it - "has it started" is a
    comparison of instants, and this is the file that would notice if
    somebody reintroduced a local-time subtraction.
    """
    PINNED = datetime(2026, 10, 27, 10, 0, 0)    # after the change, CET

    def test_the_started_refusal_holds_after_the_clock_change(self):
        user = self._student("dstafter")
        self._packline(user)
        event = self._class(self.window + 2, "LC dst")
        booking = self._book(user, event)
        start = fields.Datetime.now() - timedelta(minutes=1)
        event.sudo().write({"start": start,
                            "stop": start + timedelta(minutes=50)})
        booking.invalidate_recordset()
        with self.assertRaises(LateCancellationError):
            booking.with_user(user).action_cancel()

    def test_she_may_still_cancel_before_the_start_after_the_change(self):
        user = self._student("dstbefore")
        line = self._packline(user)
        booking = self._book(user, self._class(self.window - 2, "LC dst2"))
        spent = self._left(line)
        booking.with_user(user).action_cancel()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            self._left(line), spent,
            "the forfeit stopped applying across the clock change")


@tagged("post_install", "-at_install")
class TestFixedClassMember(LateCancelFixture):
    """A booking the nightly placement made, cancelled late by her.

    She forfeits like anyone else, and the placement must not quietly put
    her back into the class she just cancelled - which would both undo
    her decision and look like the seat never freed.
    """

    def _fixed_member(self, tag):
        user = self._student(tag)
        order = self._membership(user)
        return user, order

    def test_she_forfeits_and_earns_no_makeup_credit(self):
        user, order = self._fixed_member("fixed")
        booking = self._book(user, self._class(self.window - 2, "LC fixed"))
        booking.with_user(user).action_cancel()
        order.invalidate_recordset()
        self.assertFalse(booking.credit_returned)
        self.assertEqual(
            order.fitness_floating_credits, 0,
            "a late cancellation of a placed booking created a make-up "
            "credit, so the weekly slot is spent AND she is compensated")

    def test_the_placement_does_not_put_her_back(self):
        """Re-running placement must not re-book the class she cancelled."""
        user, order = self._fixed_member("fixedplace")
        event = self._class(self.window - 2, "LC fixed place")
        booking = self._book(user, event)
        booking.with_user(user).action_cancel()

        Booking = self.env["fitness.booking"].sudo()
        before = Booking.search_count([
            ("student_id", "=", user.partner_id.id),
            ("calendar_event_id", "=", event.id),
            ("state", "in", ("booked", "attended"))])
        self.assertEqual(before, 0, "the cancellation did not take")

        placer = getattr(order, "_auto_place_clase_fija", None)
        if placer is None:
            self.skipTest("no automatic placement on this build")
        placer()
        after = Booking.search_count([
            ("student_id", "=", user.partner_id.id),
            ("calendar_event_id", "=", event.id),
            ("state", "in", ("booked", "attended"))])
        self.assertEqual(
            after, 0,
            "the nightly placement re-booked the class she had just "
            "cancelled, so her decision is undone overnight")
