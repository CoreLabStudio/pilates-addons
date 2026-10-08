# -*- coding: utf-8 -*-
"""A class the studio calls off gives the make-up credit back.

She did not choose this. A booking paid from a pack has always been
refunded when the studio cancels, and a membership booking paid with a
make-up credit was the one shape that came away with nothing - so the
student who had already been inconvenienced once lost a credit for it.

The owner decided it: a student must not lose a credit because the
studio called off the class, whatever the timing.

Two things are deliberately NOT changed here, and both are pinned by a
test so they cannot drift without somebody choosing to:

  * a class MOVED to another time, which never cancels anything;
  * a manager cancelling ONE booking through the late-cancel wizard,
    which still returns nothing for a make-up booking even with the
    "restore credit" tick on.
"""
from odoo.tests import tagged

from odoo.addons.fitness_subscriptions.tests.test_makeup_credit_returned import (
    MakeUpCreditFixture,
)


@tagged("post_install", "-at_install")
class TestStudioCancelledClass(MakeUpCreditFixture):

    def _manager(self):
        return self.env["res.users"].create({
            "name": "MU SC Manager",
            "login": "mu.sc.manager@example.invalid", "lang": "en_US",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_manager").id])]})

    def _on_a_makeup_credit(self, tag, hours=50):
        """A student whose week is full, booked with a make-up credit."""
        user = self._student(tag)
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1
        klass = self._class(hours, "MU SC %s" % tag)
        booking = self._book(partner, klass)
        self.assertTrue(
            booking.fitness_used_floating_credit,
            "fixture is wrong: %s did not pay with a make-up credit, so "
            "nothing below is testing one" % tag)
        self.assertEqual(self._floating(order), 0)
        return user, order, klass, booking

    # == the change ==================================================
    def test_the_credit_comes_back_once(self):
        _user, order, klass, booking = self._on_a_makeup_credit("once")
        klass.with_user(self._manager()).action_cancel_class()
        booking.invalidate_recordset()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            self._floating(order), 1,
            "the studio called the class off and she lost the make-up "
            "credit she had paid with")

    def test_it_comes_back_even_inside_the_six_hour_window(self):
        """Timing is the studio's doing here, not hers."""
        _user, order, klass, _b = self._on_a_makeup_credit(
            "late", hours=max(self.window - 2, 1))
        klass.with_user(self._manager()).action_cancel_class()
        self.assertEqual(
            self._floating(order), 1,
            "a class called off at short notice cost her the credit, which "
            "punishes her for the studio's timing")

    def test_cancelling_the_class_twice_adds_nothing(self):
        _user, order, klass, _b = self._on_a_makeup_credit("twice")
        manager = self._manager()
        klass.with_user(manager).action_cancel_class()
        after_first = self._floating(order)
        self.assertEqual(after_first, 1)

        klass.with_user(manager).action_cancel_class()
        self.assertEqual(
            self._floating(order), after_first,
            "calling the class off a second time handed out another credit")

    # == the negatives ===============================================
    def test_a_pack_booking_is_unchanged(self):
        user = self._student("scpack")
        line = self._packline(user.partner_id)
        before = line.fitness_remaining_classes
        klass = self._class(30, "MU SC pack")
        self._book(user.partner_id, klass)
        line.invalidate_recordset()
        self.assertEqual(line.fitness_remaining_classes, before - 1)

        klass.with_user(self._manager()).action_cancel_class()
        line.invalidate_recordset()
        self.assertEqual(
            line.fitness_remaining_classes, before,
            "the package path changed, and it was not meant to")

    def test_an_allowance_booking_is_unchanged(self):
        user = self._student("scallow")
        order = self._membership(user.partner_id)
        klass = self._class(30, "MU SC allowance")
        booking = self._book(user.partner_id, klass)
        self.assertFalse(booking.fitness_used_floating_credit)

        klass.with_user(self._manager()).action_cancel_class()
        self.assertEqual(
            self._floating(order), 1,
            "an allowance booking on a cancelled class no longer earns its "
            "one compensating credit")

    def test_a_moved_class_mints_nothing(self):
        """A move is not a cancellation.

        The reassign wizard rewrites calendar_event_id and never calls
        action_cancel, so this asserts the path stays out of reach - if
        a move ever started cancelling, a studio reshuffle would hand
        every affected student a credit.
        """
        _user, order, _klass, booking = self._on_a_makeup_credit("moved")
        target = self._class(60, "MU SC target")
        booking.sudo().write({"calendar_event_id": target.id})
        booking.invalidate_recordset()
        self.assertEqual(
            booking.state, "booked", "moving the booking cancelled it")
        self.assertEqual(
            self._floating(order), 0,
            "moving a class to another time handed back a credit")

    def test_her_other_bookings_are_untouched(self):
        user, _order, klass, _b = self._on_a_makeup_credit("others")
        # NEXT week, not this one: her current week is already full and
        # the make-up credit has been spent, so a second booking inside
        # it is refused on the cap and never reaches the point of this
        # test. A fresh week pays for it from the ordinary allowance.
        other = self._class(24 * 8, "MU SC other")
        kept = self._book(user.partner_id, other,
                          manager_override_timewindow=True)

        klass.with_user(self._manager()).action_cancel_class()
        kept.invalidate_recordset()
        self.assertEqual(
            kept.state, "booked",
            "calling off one class cancelled her booking on another")

    def test_the_weekly_counter_is_untouched(self):
        _user, order, klass, _b = self._on_a_makeup_credit("sccount")
        before = order.fitness_weekly_used_count(
            klass.start, discipline="reformer")
        klass.with_user(self._manager()).action_cancel_class()
        after = order.fitness_weekly_used_count(
            klass.start, discipline="reformer")
        self.assertEqual(
            before, after,
            "a studio cancellation moved the weekly counter, and the "
            "monotonic rule is what makes recycling impossible")

    def test_ten_studio_cancellations_never_leave_her_ahead(self):
        user = self._student("sccycle")
        partner = user.partner_id
        order = self._membership(partner)
        self._spend_her_week(partner)
        order.sudo().fitness_floating_credits = 1
        manager = self._manager()

        for n in range(10):
            klass = self._class(20 + n, "MU SC cycle %d" % n)
            booking = self._book(partner, klass)
            self.assertTrue(
                booking.fitness_used_floating_credit,
                "cycle %d did not spend a make-up credit" % n)
            klass.with_user(manager).action_cancel_class()
            self.assertLessEqual(
                self._floating(order), 1,
                "after %d studio cancellation(s) she holds more credits "
                "than she was ever given" % (n + 1))
        self.assertEqual(self._floating(order), 1)

    # == what is deliberately NOT changed ============================
    def test_the_manager_wizard_on_one_booking_is_unchanged(self):
        """Reported, not changed, by instruction.

        A manager cancelling ONE booking through the late-cancel wizard
        and ticking "restore credit" still returns nothing for a booking
        paid with a make-up credit. That is today's behaviour and it is
        a gap - pinned here so it cannot move either way by accident.
        """
        _user, order, _klass, booking = self._on_a_makeup_credit("wizard")
        wizard = self.env["fitness.booking.cancel.wizard"].sudo().create({
            "booking_id": booking.id, "restore_credit": True})
        wizard.with_user(self._manager()).action_confirm()

        booking.invalidate_recordset()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            self._floating(order), 0,
            "the manager's one-booking wizard now returns the make-up "
            "credit. That is probably right, but it is OUT OF SCOPE here "
            "and changing it silently is how a release stops being "
            "reviewable.")
