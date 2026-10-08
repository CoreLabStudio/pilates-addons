# -*- coding: utf-8 -*-
"""A manager can give back the credit a late cancellation kept.

The policy stands: cancel inside the window and the credit is gone. But
the studio sometimes decides otherwise - she rang the same morning, ill,
with a note - and until now there was no way to act on that decision. The
booking was cancelled, the credit was gone, and the desk's only option
was to hand out a free-class product that has no connection to the class
it was meant to replace.

What these tests hold down is not that it works once, but that it cannot
be made to work twice, cannot be reached by somebody who should not reach
it, cannot be done without a reason, and gives back the SAME KIND of
credit the booking spent - a pack class to a pack, a make-up credit to a
membership. A give-back that quietly invented a credit of the wrong kind
would read as a pass here and cost the studio money in production.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.fitness_bookings.tests.test_student_may_cancel_late import (
    LateCancelFixture,
)


@tagged("post_install", "-at_install")
class TestManagerGivesTheCreditBack(LateCancelFixture):

    def _late_cancelled_pack_booking(self, tag="giveback"):
        """A booking in exactly the state the feature exists for."""
        user = self._student(tag)
        line = self._packline(user)
        booking = self._book(user, self._class(self.window - 2))
        spent = self._left(line)
        booking.with_user(user).action_cancel()
        self.assertFalse(
            booking.credit_returned,
            "the fixture is not the case under test: the credit came back "
            "on its own")
        self.assertEqual(self._left(line), spent)
        return user, line, booking, spent

    # == it returns the credit, once ==================================
    def test_a_manager_gives_a_pack_credit_back(self):
        user, line, booking, spent = self._late_cancelled_pack_booking()
        manager = self._manager()

        booking.with_user(manager)._give_credit_back("She was ill, with a note.")

        self.assertEqual(
            self._left(line), spent + 1,
            "the manager gave the credit back and the pack did not grow, so "
            "she still cannot book the class she paid for")
        self.assertTrue(booking.fitness_credit_given_back)
        self.assertEqual(booking.fitness_credit_given_back_by, manager)
        self.assertTrue(booking.fitness_credit_given_back_on)
        self.assertEqual(
            booking.fitness_credit_given_back_reason,
            "She was ill, with a note.")

    def test_it_does_not_touch_credit_returned(self):
        """The two are different facts and reports read both.

        credit_returned answers "did the policy return it?" - which stays
        no. fitness_credit_given_back answers "did the studio decide to
        anyway?". Collapsing them would make every late cancellation the
        studio forgave disappear from the late-cancellation figures.
        """
        user, line, booking, spent = self._late_cancelled_pack_booking("twofacts")
        booking.with_user(self._manager())._give_credit_back("Goodwill.")
        self.assertFalse(
            booking.credit_returned,
            "the give-back rewrote history: this cancellation now looks as "
            "though it was inside the policy all along")
        self.assertTrue(booking.fitness_credit_given_back)

    def test_it_cannot_be_done_twice(self):
        user, line, booking, spent = self._late_cancelled_pack_booking("twice")
        manager = self._manager()
        booking.with_user(manager)._give_credit_back("First time.")
        after_one = self._left(line)

        with self.assertRaises(UserError):
            booking.with_user(manager)._give_credit_back("Second time.")

        self.assertEqual(
            self._left(line), after_one,
            "a second give-back handed out another credit, so a manager who "
            "clicks twice gives her two classes for one")

    def test_the_button_disappears_once_it_is_done(self):
        """What the form's invisible= reads. Not a permission, but the
        reason a manager never sees the second click."""
        user, line, booking, spent = self._late_cancelled_pack_booking("hide")
        self.assertFalse(booking.credit_returned)
        self.assertFalse(booking.fitness_credit_given_back)
        booking.with_user(self._manager())._give_credit_back("Done.")
        self.assertTrue(booking.fitness_credit_given_back)

    # == who may do it ================================================
    def test_a_student_cannot_give_herself_a_credit_back(self):
        """Over RPC, not through the button she never sees."""
        user, line, booking, spent = self._late_cancelled_pack_booking("student")

        with self.assertRaises(AccessError):
            booking.with_user(user)._give_credit_back("I would like it back.")

        self.assertEqual(
            self._left(line), spent,
            "a student called the method directly and got her credit back")
        self.assertFalse(booking.fitness_credit_given_back)

    def test_a_teacher_cannot_either(self):
        user, line, booking, spent = self._late_cancelled_pack_booking("teacher")
        teacher = self.env["res.users"].create({
            "name": "LC Teacher", "login": "lc.teacher.gb@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_teacher").id])]})

        with self.assertRaises(AccessError):
            booking.with_user(teacher)._give_credit_back("She told me she was ill.")

        self.assertEqual(self._left(line), spent)

    def test_opening_the_dialog_is_guarded_too(self):
        """Not only the confirm: the action that creates the wizard."""
        user, line, booking, spent = self._late_cancelled_pack_booking("dialog")
        with self.assertRaises(AccessError):
            booking.with_user(user).action_give_credit_back()

    # == a reason is not optional ====================================
    def test_a_blank_reason_is_refused(self):
        user, line, booking, spent = self._late_cancelled_pack_booking("noreason")
        manager = self._manager()
        for blank in ("", "   ", None):
            with self.assertRaises(UserError):
                booking.with_user(manager)._give_credit_back(blank)
        self.assertEqual(
            self._left(line), spent,
            "a credit was given back with no reason recorded, so in three "
            "months nobody can say why")
        self.assertFalse(booking.fitness_credit_given_back)

    def test_the_reason_is_kept_on_the_booking(self):
        """In the chatter, where somebody looking at the record will find
        it, not only in a log file nobody reads."""
        user, line, booking, spent = self._late_cancelled_pack_booking("chatter")
        before = len(booking.message_ids)
        booking.with_user(self._manager())._give_credit_back(
            "Family emergency, she called at 07:40.")
        bodies = " ".join(
            booking.message_ids.mapped("body") or [])
        self.assertGreater(len(booking.message_ids), before)
        self.assertIn("Family emergency", bodies)

    # == only on a booking that actually forfeited ====================
    def test_not_on_a_live_booking(self):
        user = self._student("live")
        line = self._packline(user)
        booking = self._book(user, self._class(self.window + 10))
        spent = self._left(line)

        with self.assertRaises(UserError):
            booking.with_user(self._manager())._give_credit_back("Why not.")

        self.assertEqual(
            self._left(line), spent,
            "a credit was handed out on a booking that is still live, so "
            "she now has a seat AND the credit for it")

    def test_not_on_a_cancellation_that_already_refunded(self):
        """Outside the window the policy already returned it. Doing this
        on top would be the second credit for one class."""
        user = self._student("already")
        line = self._packline(user)
        booking = self._book(user, self._class(self.window + 4))
        booking.with_user(user).action_cancel()
        self.assertTrue(booking.credit_returned)
        after_refund = self._left(line)

        with self.assertRaises(UserError):
            booking.with_user(self._manager())._give_credit_back("Again.")

        self.assertEqual(
            self._left(line), after_refund,
            "she was given a second credit for a class she was already "
            "refunded for")

    # == the right KIND of credit ====================================
    def test_a_membership_booking_gets_a_make_up_credit(self):
        """Not a pack class, and not a reset weekly counter.

        The weekly counter is monotonic by design: a cancelled allowance
        booking keeps consuming its slot, and the compensation is a
        make-up credit. That is what a cancellation outside the window
        gives her, so it is what this must give her too.
        """
        user = self._student("memberback")
        order = self._membership(user)
        booking = self._book(user, self._class(self.window - 2))
        booking.with_user(user).action_cancel()
        self.assertFalse(booking.credit_returned)
        order.invalidate_recordset()
        before = order.fitness_floating_credits

        booking.with_user(self._manager())._give_credit_back("Ill.")

        order.invalidate_recordset()
        self.assertEqual(
            order.fitness_floating_credits, before + 1,
            "a membership booking's give-back left her with no make-up "
            "credit, so she lost the class after all")

    def test_a_booking_with_no_source_is_refused_not_silently_ignored(self):
        """A manager-made booking against nothing has no credit to return.

        It must say so. Returning quietly would mark the booking as given
        back, hide the button, and hand her nothing - the worst of the
        three outcomes, because it looks done.
        """
        # A booking with no source cannot be created - the payment
        # source is required and _select_payment_source refuses - so it
        # is built the way it arises in production: a real booking whose
        # source was detached afterwards.
        user, line, booking, spent = self._late_cancelled_pack_booking(
            "nosource")
        booking.sudo().package_order_line_id = False

        with self.assertRaises(UserError):
            booking.with_user(self._manager())._give_credit_back("Nothing here.")

        self.assertFalse(
            booking.fitness_credit_given_back,
            "the booking was marked as given back although nothing was "
            "returned, so the button is gone and she still has nothing")

    # == the dialog is the only way in from the UI ====================
    def test_the_wizard_passes_the_reason_through(self):
        user, line, booking, spent = self._late_cancelled_pack_booking("wizard")
        manager = self._manager()
        action = booking.with_user(manager).action_give_credit_back()
        self.assertEqual(
            action["res_model"], "fitness.booking.credit.back.wizard")
        wizard = self.env["fitness.booking.credit.back.wizard"].with_user(
            manager).browse(action["res_id"])
        self.assertEqual(wizard.booking_id, booking)
        wizard.write({"reason": "Doctor's note, seen at the desk."})
        wizard.action_confirm()
        self.assertEqual(self._left(line), spent + 1)
        self.assertEqual(
            booking.fitness_credit_given_back_reason,
            "Doctor's note, seen at the desk.")

    def test_the_wizard_has_a_form_view_that_confirms(self):
        """Without an explicit form view Odoo renders its own, with a Save
        footer and no call to action_confirm: the dialog would open, look
        right, and return nothing at all."""
        view = self.env.ref(
            "fitness_bookings."
            "view_fitness_booking_credit_back_wizard_form",
            raise_if_not_found=False)
        self.assertTrue(
            view, "the give-back wizard has no form view, so its confirm "
                  "button does not exist")
        self.assertIn(
            'name="action_confirm"', view.arch,
            "the wizard's form view has no button that calls action_confirm")
