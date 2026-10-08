# -*- coding: utf-8 -*-
"""A make-up credit comes back when she cancels in good time.

Paula Masip cancelled her Wednesday class two days ahead and correctly
earned a make-up (floating) credit. The same minute she spent it on the
Monday evening class, and 36 seconds later cancelled that one too -
eight hours and ten minutes before it started, well outside the studio's
six-hour window, from her own login. She got nothing back, and her week
then refused her every class.

Every booking screen and confirmation email in the studio says you keep
your credit if you cancel in time. That was false for a make-up credit,
and false for exactly the students who had already been inconvenienced
once.

The rule it collided with exists to stop one credit being recycled for
ever. That worry is the reason for the cycle tests below: the weekly
counter is monotonic and this change does not touch it, so a cancelled
booking still holds its slot and the student comes back to where she
started, never past it.

The clock is pinned throughout. The fixtures build their own students,
products and classes and set an explicit language, so nothing here
depends on the day it is run or on what the database happens to hold.
"""
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.tests import TransactionCase, common, tagged

# A Wednesday, well clear of any month or DST boundary.
PINNED = datetime(2026, 11, 4, 8, 0, 0)
WINDOW_PARAM = 'fitness.cancellation_window_hours'


class MakeUpCreditFixture(TransactionCase):
    """A Reformer member with a two-a-week allowance, like Paula's."""

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        self.plan_month = self.env.ref(
            "sale_subscription.subscription_plan_month")
        self.reformer_type = self.env["fitness.class.type"].create({
            "name": "MU Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
        })
        self.plan = self.env["product.template"].create({
            "name": "MU Reformer 2 a week", "list_price": 90.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "reformer", "fitness_session_type": "group",
            "weekly_class_allowance": 2,
        })
        self.pack = self.env["product.template"].create({
            "name": "MU Reformer pack 5", "list_price": 100.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 120,
            "fitness_class_type": "reformer", "fitness_session_type": "group",
        })
        self.window = self.env["fitness.booking"].sudo(
            )._cancellation_window_hours()

    # -- fixtures ----------------------------------------------------
    def _student(self, tag):
        return self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "MU %s" % tag,
                "login": "mu.%s@example.invalid" % tag,
                "email": "mu.%s@example.invalid" % tag,
                "lang": "en_US",
                "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })

    def _membership(self, partner):
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id, "plan_id": self.plan_month.id})
        # The line is created separately: writing plan_id and order_line in
        # one go discards the explicit price.
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.plan.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": self.plan.list_price})
        order.action_confirm()
        today = fields.Date.context_today(partner)
        order.write({"start_date": today,
                     "next_invoice_date": today + timedelta(weeks=8)})
        return order

    def _packline(self, partner):
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
                "fitness_class_type": "reformer"})]})
        order.action_confirm()
        return order.order_line[:1]

    def _class(self, hours_from_now, name="MU class"):
        start = fields.Datetime.now() + timedelta(hours=hours_from_now)
        return self.env["calendar.event"].sudo().create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.reformer_type.id,
            "is_fitness_class": True, "capacity": 6, "session_type": "group",
        })

    def _book(self, partner, event, **extra):
        vals = {"student_id": partner.id, "calendar_event_id": event.id}
        vals.update(extra)
        return self.env["fitness.booking"].sudo().create(vals)

    def _spend_her_week(self, partner):
        """Two allowance bookings, so the next one must use a credit."""
        for n, h in enumerate((30, 31)):
            self._book(partner, self._class(h, "MU week %d" % n))

    @staticmethod
    def _floating(order):
        order.invalidate_recordset()
        return order.fitness_floating_credits


@tagged("post_install", "-at_install")
class TestPaulasCase(MakeUpCreditFixture):
    """Her exact sequence, reproduced."""

    def test_a_makeup_credit_cancelled_in_good_time_comes_back(self):
        user = self._student("paula")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1

        klass = self._class(8.17, "MU Reformer Sculpt")   # 8 h 10 min ahead
        booking = self._book(partner, klass)
        self.assertTrue(
            booking.fitness_used_floating_credit,
            "fixture is wrong: her week is not full, so this booking did "
            "not use the make-up credit and proves nothing")
        self.assertEqual(self._floating(order), 0, "the credit was not spent")

        booking.with_user(user).action_cancel()

        self.assertTrue(
            booking.credit_returned,
            "she cancelled outside the window, so the booking itself "
            "should say a credit was due")
        self.assertEqual(
            self._floating(order), 1,
            "she cancelled %0.2f h before the class, well outside the %s h "
            "window, and her make-up credit did not come back - which is "
            "the promise every booking email in the studio makes"
            % (8.17, self.window))

    def test_and_she_can_book_again_afterwards(self):
        """The credit is worth nothing if the engine still refuses her."""
        user = self._student("paulabook")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1

        klass = self._class(8.17)
        booking = self._book(partner, klass)
        booking.with_user(user).action_cancel()

        later = self._class(40, "MU later class")
        source = self.env["fitness.booking"].sudo()._select_payment_source(
            partner.id, later)
        self.assertEqual(
            source, {"subscription_id": order.id},
            "her membership still will not pay for a class, so returning "
            "the credit changed nothing she can feel")

    def test_the_36_second_booking_is_not_treated_as_gaming(self):
        """What actually bit her: a booking that lived half a minute."""
        user = self._student("misclick")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1

        booking = self._book(partner, self._class(8.17))
        booking.with_user(user).action_cancel()
        self.assertEqual(
            self._floating(order), 1,
            "a booking cancelled 36 seconds after it was made is a "
            "misclick, and it cost her a credit")


@tagged("post_install", "-at_install")
class TestWhatMustNotChange(MakeUpCreditFixture):
    """The negatives. Each one is a way this change could have gone wrong."""

    def test_inside_the_window_a_student_is_refused_outright(self):
        user = self._student("late")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1

        klass = self._class(self.window - 1)
        booking = self._book(partner, klass,
                             manager_override_timewindow=True)
        with self.assertRaises(Exception) as caught:
            booking.with_user(user).action_cancel()
        self.assertNotIsInstance(
            caught.exception, AccessError,
            "she was refused for the wrong reason")
        self.assertEqual(
            self._floating(order), 0,
            "a late cancellation handed back a credit")

    def test_an_allowance_booking_behaves_exactly_as_before(self):
        """Cancelled in good time: one credit, as compensation."""
        user = self._student("allowance")
        partner = user.partner_id
        order = self._membership(partner)
        klass = self._class(30)
        booking = self._book(partner, klass)
        self.assertFalse(booking.fitness_used_floating_credit)

        booking.with_user(user).action_cancel()
        self.assertEqual(
            self._floating(order), 1,
            "the allowance path changed, and it was not meant to")

    def test_a_package_booking_behaves_exactly_as_before(self):
        user = self._student("pack")
        partner = user.partner_id
        line = self._packline(partner)
        before = line.fitness_remaining_classes

        klass = self._class(30)
        booking = self._book(partner, klass)
        line.invalidate_recordset()
        self.assertEqual(line.fitness_remaining_classes, before - 1)

        booking.with_user(user).action_cancel()
        line.invalidate_recordset()
        self.assertEqual(
            line.fitness_remaining_classes, before,
            "the package path changed, and it was not meant to")

    def test_a_studio_cancellation_now_returns_the_credit(self):
        """This assertion used to say the opposite, and was wrong to.

        Until the studio commit, a class the studio called off returned
        NOTHING for a booking paid with a make-up credit, and this test
        pinned that as deliberate. The owner has since decided it: a
        student must not lose a credit because the studio cancelled, and
        a PACK booking has always been refunded in exactly this case.
        So the behaviour and this test both flip.
        """
        user = self._student("studio")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1

        # 50 h, not 30: _spend_her_week already holds 30 and 31, and an
        # overlapping booking is refused outright. Still the same week,
        # so the make-up credit is still what pays for it.
        klass = self._class(50)
        booking = self._book(partner, klass)
        self.assertTrue(
            booking.fitness_used_floating_credit,
            "fixture is wrong: this did not use the make-up credit, so "
            "the studio path is not being tested against one")
        self.assertEqual(self._floating(order), 0)

        manager = self.env["res.users"].create({
            "name": "MU Manager", "login": "mu.manager@example.invalid",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_manager").id])]})
        klass.with_user(manager).action_cancel_class()

        booking.invalidate_recordset()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            self._floating(order), 1,
            "the studio called the class off and she lost the make-up "
            "credit she had paid with - through no choice of her own, and "
            "when a pack booking would have been refunded")

    def test_a_student_cannot_cancel_somebody_else_s_booking(self):
        mine = self._student("mine")
        hers = self._student("hers")
        order = self._membership(mine.partner_id)
        booking = self._book(mine.partner_id, self._class(30))

        # assertRaises with a TUPLE raises TypeError inside Odoo's own
        # override, which calls issubclass() on the argument. Caught by
        # hand so the assertion is about the refusal, not the harness.
        raised = None
        try:
            booking.with_user(hers).action_cancel()
        except Exception as exc:
            raised = exc
        self.assertIsNotNone(
            raised,
            "one student cancelled another student's booking")
        self.assertIsInstance(
            raised, (AccessError, UserError, ValidationError),
            "refused, but with %r - not a refusal a caller can handle"
            % type(raised).__name__)
        self.assertEqual(
            self._floating(order), 0,
            "another student's cancellation moved her credits")

    def test_the_weekly_counter_still_counts_the_cancelled_slot(self):
        """The monotonic rule is untouched - that is what stops recycling."""
        user = self._student("weekly")
        partner = user.partner_id
        order = self._membership(partner)
        klass = self._class(30)
        booking = self._book(partner, klass)
        before = order.fitness_weekly_used_count(
            klass.start, discipline="reformer")

        booking.with_user(user).action_cancel()
        after = order.fitness_weekly_used_count(
            klass.start, discipline="reformer")
        self.assertEqual(
            before, after,
            "cancelling freed the weekly slot. The counter is meant to be "
            "monotonic, and if it is not, the cycle tests below are "
            "meaningless and credits CAN be manufactured.")


@tagged("post_install", "-at_install")
class TestNoRecycling(MakeUpCreditFixture):
    """Prove the thing the old rule was protecting against."""

    def _ready(self, tag):
        user = self._student(tag)
        partner = user.partner_id
        order = self._membership(partner)
        for n, h in enumerate((30, 31)):
            self._book(partner, self._class(h, "MU fill %d" % n))
        order.sudo().fitness_floating_credits = 1
        return user, partner, order

    def test_ten_cycles_leave_the_balance_exactly_where_it_started(self):
        user, partner, order = self._ready("cycle")
        start = self._floating(order)
        self.assertEqual(start, 1)

        for n in range(10):
            klass = self._class(20 + n, "MU cycle %d" % n)
            booking = self._book(partner, klass)
            self.assertTrue(
                booking.fitness_used_floating_credit,
                "cycle %d did not spend a make-up credit, so this loop is "
                "not testing recycling at all" % n)
            booking.with_user(user).action_cancel()

        self.assertEqual(
            self._floating(order), start,
            "ten book-and-cancel cycles changed the balance from %s to %s. "
            "Credits can be manufactured and this change must not ship."
            % (start, self._floating(order)))

    def test_a_second_cancel_adds_nothing(self):
        user, partner, order = self._ready("double")
        booking = self._book(partner, self._class(20))
        booking.with_user(user).action_cancel()
        after_first = self._floating(order)
        self.assertEqual(after_first, 1)

        with self.assertRaises(UserError):
            booking.with_user(user).action_cancel()
        self.assertEqual(
            self._floating(order), after_first,
            "cancelling an already-cancelled booking handed out a second "
            "credit")

    def test_she_never_ends_up_with_more_than_she_was_given(self):
        """The plain statement of the worry, asserted directly."""
        user, partner, order = self._ready("never")
        for n in range(5):
            klass = self._class(20 + n, "MU never %d" % n)
            self._book(partner, klass).with_user(user).action_cancel()
            self.assertLessEqual(
                self._floating(order), 1,
                "after %d cycle(s) she holds more credits than she was "
                "ever given" % (n + 1))
