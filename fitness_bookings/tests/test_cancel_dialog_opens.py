# -*- coding: utf-8 -*-
"""The desk has one way to cancel a booking, and it works.

Two defects in one place:

1. The booking form carried BOTH "Cancel Student's Booking" and "Cancel
   or Move". They did the same job and the plain one was the weaker:
   no choice about the credit, no option to move the student instead.
   It is deleted, not hidden - a button behind groups is still reachable
   and still has to be reasoned about.

2. `fitness_packages` and `fitness_notifications` both called
   `super().action_cancel()` and threw the result away. The base returns
   the "Cancel Booking (Late)" dialog's action BEFORE cancelling, so the
   dialog never opened AND the post-cancellation work still ran: the
   student was emailed "your booking has been cancelled" about a class
   she still had a place in. Live on production since the first import.

NO RULE CHANGES. Outside the window the credit comes back; inside it
does not, unless the manager says otherwise in the dialog. This batch
makes the dialog reachable and stops an untrue email; it decides nothing
about credits.
"""
import re
from datetime import datetime, timedelta

import pytz

from odoo import fields
from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
MANAGER = "fitness_core.group_fitness_manager"
STUDENT = "fitness_core.group_fitness_student"


def _utc(local_naive):
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class CancelDialogFixture(TransactionCase):

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
            "name": "CD Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group"})
        self.pack = self.env["product.template"].create({
            "name": "CD Reformer pack 5", "list_price": 100.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 120,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group"})
        self.plan_month = self.env.ref(
            "sale_subscription.subscription_plan_month")
        self.plan = self.env["product.template"].create({
            "name": "CD Reformer 2 a week", "list_price": 90.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "reformer", "fitness_session_type": "group",
            "weekly_class_allowance": 2})

    # -- people and things -------------------------------------------
    def _student(self, tag):
        return self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "CD %s" % tag,
                "login": "cd.%s@example.invalid" % tag,
                "email": "cd.%s@example.invalid" % tag,
                "lang": "en_US", "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref(STUDENT).id])]})

    def _manager(self):
        return self.env["res.users"].create({
            "name": "CD Manager", "login": "cd.manager@example.invalid",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref(MANAGER).id])]})

    def _packline(self, usr):
        order = self.env["sale.order"].sudo().create({
            "partner_id": usr.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
                "fitness_class_type": "reformer"})]})
        order.action_confirm()
        return order.order_line[:1]

    def _membership(self, usr):
        order = self.env["sale.order"].sudo().create({
            "partner_id": usr.partner_id.id, "plan_id": self.plan_month.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.plan.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 90.0})
        order.action_confirm()
        today = fields.Date.context_today(usr.partner_id)
        order.write({"start_date": today,
                     "next_invoice_date": today + timedelta(weeks=8)})
        return order

    def _class(self, hours_from_now, name="CD class"):
        start = fields.Datetime.now() + timedelta(hours=hours_from_now)
        return self.env["calendar.event"].sudo().create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id, "is_fitness_class": True,
            "capacity": 6, "session_type": "group"})

    def _book(self, usr, event):
        return self.env["fitness.booking"].sudo().create({
            "student_id": usr.partner_id.id,
            "calendar_event_id": event.id})

    @staticmethod
    def _left(line):
        line.invalidate_recordset()
        return line.fitness_remaining_classes

    # -- counting, because a flag can be right while nothing was sent --
    def _mail_count(self):
        return self.env['mail.mail'].sudo().with_context(
            active_test=False).search_count([])

    def _notif_count(self, usr):
        model = self.env.get('fitness.notification')
        if model is None:
            return 0
        return model.sudo().search_count(
            [('user_id', '=', usr.id)])


@tagged("post_install", "-at_install")
class TestTheLateDialogOpens(CancelDialogFixture):

    ACTION_TYPES = {
        'ir.actions.act_window', 'ir.actions.act_window_close',
        'ir.actions.act_url', 'ir.actions.server', 'ir.actions.report',
        'ir.actions.client',
    }

    # == the dialog reaches the manager ==============================
    def test_an_in_window_cancel_returns_the_late_wizard(self):
        usr = self._student("dialog")
        self._packline(usr)
        booking = self._book(usr, self._class(self.window - 2))

        action = booking.with_user(self._manager()).action_cancel()

        self.assertIsInstance(
            action, dict,
            "the button returned %r instead of an action, so no dialog "
            "opens and the desk sees nothing happen" % type(action))
        self.assertIn(action.get('type'), self.ACTION_TYPES)
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(
            action.get('res_model'), 'fitness.booking.cancel.wizard',
            "the action does not open the Cancel Booking (Late) wizard")
        self.assertTrue(
            action.get('res_id'), "the action names no record to open")

    def test_nothing_is_cancelled_while_the_dialog_is_open(self):
        """The base returns the action BEFORE cancelling. The overrides
        used to carry on regardless."""
        usr = self._student("notyet")
        line = self._packline(usr)
        booking = self._book(usr, self._class(self.window - 2))
        spent = self._left(line)

        booking.with_user(self._manager()).action_cancel()

        self.assertEqual(
            booking.state, 'booked',
            "the booking was cancelled before the manager answered the "
            "dialog she never saw")
        self.assertFalse(booking.credit_returned)
        self.assertEqual(
            self._left(line), spent,
            "a pack credit moved while the dialog was still open")

    def test_no_email_bell_or_push_while_the_dialog_is_open(self):
        """The defect that reached students.

        Counted, not read off a flag: a flag can be right while a mail
        row was still written, and it was the row that reached her.
        """
        usr = self._student("noemail")
        self._packline(usr)
        booking = self._book(usr, self._class(self.window - 2))
        mails = self._mail_count()
        bells = self._notif_count(usr)

        booking.with_user(self._manager()).action_cancel()

        self.assertEqual(
            self._mail_count(), mails,
            "a cancellation email was queued for a booking that is still "
            "booked - the student is told her class is off when it is not")
        self.assertEqual(
            self._notif_count(usr), bells,
            "an in-app notification was raised for a cancellation that "
            "did not happen")

    def test_the_wizard_then_cancels_it_and_sends_exactly_one_email(self):
        usr = self._student("confirm")
        line = self._packline(usr)
        booking = self._book(usr, self._class(self.window - 2))
        spent = self._left(line)
        manager = self._manager()

        action = booking.with_user(manager).action_cancel()
        wizard = self.env['fitness.booking.cancel.wizard'].with_user(
            manager).browse(action['res_id'])
        self.assertEqual(wizard.booking_id, booking)
        mails = self._mail_count()

        closed = wizard.action_confirm()

        self.assertEqual(
            (closed or {}).get('type'), 'ir.actions.act_window_close')
        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(
            self._mail_count(), mails + 1,
            "the confirmed cancellation sent %d emails, not exactly one"
            % (self._mail_count() - mails))
        # Untouched tick: inside the window the credit is NOT returned.
        self.assertFalse(booking.credit_returned)
        self.assertEqual(self._left(line), spent)

    def test_the_tick_in_that_dialog_returns_the_credit(self):
        """The whole reason the dialog matters."""
        usr = self._student("tick")
        line = self._packline(usr)
        booking = self._book(usr, self._class(self.window - 2))
        spent = self._left(line)
        manager = self._manager()

        action = booking.with_user(manager).action_cancel()
        wizard = self.env['fitness.booking.cancel.wizard'].with_user(
            manager).browse(action['res_id'])
        wizard.write({'restore_credit': True})
        wizard.action_confirm()

        self.assertEqual(booking.state, 'cancelled')
        self.assertTrue(booking.credit_returned)
        self.assertEqual(
            self._left(line), spent + 1,
            "Restore Credit was ticked and the pack did not go up")

    # == nothing else changed ========================================
    def test_an_outside_window_cancel_behaves_exactly_as_before(self):
        usr = self._student("outside")
        line = self._packline(usr)
        booking = self._book(usr, self._class(self.window + 6))
        spent = self._left(line)

        returned = booking.with_user(self._manager()).action_cancel()

        self.assertNotIsInstance(
            returned, dict,
            "an ordinary cancellation now opens a dialog it never used to")
        self.assertEqual(booking.state, 'cancelled')
        self.assertTrue(booking.credit_returned)
        self.assertEqual(self._left(line), spent + 1)

    def test_the_student_still_cancels_from_the_portal(self):
        """action_cancel stays on the model: only the button went."""
        usr = self._student("portal")
        line = self._packline(usr)
        booking = self._book(usr, self._class(self.window + 6))
        spent = self._left(line)

        booking.with_user(usr).action_cancel()

        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(self._left(line), spent + 1)

    def test_an_allowance_booking_still_follows_its_own_route(self):
        usr = self._student("allow")
        order = self._membership(usr)
        booking = self._book(usr, self._class(self.window + 6))
        order.invalidate_recordset()
        before = order.fitness_floating_credits

        booking.with_user(self._manager()).action_cancel()

        order.invalidate_recordset()
        self.assertEqual(
            order.fitness_floating_credits, before + 1,
            "an allowance cancellation in good time stopped earning its "
            "make-up credit")

    def test_a_make_up_booking_still_follows_its_own_route(self):
        usr = self._student("makeup")
        order = self._membership(usr)
        for hours in (30, 31):
            self._book(usr, self._class(hours, "CD fill %d" % hours))
        order.sudo().fitness_floating_credits = 1
        order.invalidate_recordset()
        booking = self._book(usr, self._class(self.window + 6))
        self.assertTrue(
            booking.fitness_used_floating_credit,
            "the fixture did not spend the make-up credit, so this tests "
            "the allowance route again")

        booking.with_user(self._manager()).action_cancel()

        self.assertEqual(booking.state, 'cancelled')
        self.assertTrue(booking.credit_returned)

    def test_the_other_two_overrides_still_propagate(self):
        """subscriptions and trials were already right. A change to the
        two broken ones must not have broken the two good ones."""
        usr = self._student("propagate")
        self._membership(usr)
        booking = self._book(usr, self._class(self.window - 2))

        action = booking.with_user(self._manager()).action_cancel()

        self.assertIsInstance(
            action, dict,
            "the action no longer survives the subscriptions override")
        self.assertEqual(
            action.get('res_model'), 'fitness.booking.cancel.wizard')


@tagged("post_install", "-at_install")
class TestTheBookingFormHasOneCancelButton(CancelDialogFixture):

    def _form(self):
        return self.env.ref("fitness_bookings.view_fitness_booking_form")

    def test_the_plain_cancel_button_is_gone(self):
        self.assertNotIn(
            'name="action_cancel"', self._form().arch,
            "the booking form still carries Cancel Student's Booking, so "
            "the desk still has two buttons for one job and the weaker of "
            "the two offers no choice about the credit")

    def test_cancel_or_move_is_still_there(self):
        self.assertIn(
            'name="action_open_reassign_wizard"', self._form().arch,
            "Cancel or Move has gone too, so the desk cannot cancel a "
            "booking from the form at all")

    def test_it_is_removed_and_not_merely_hidden(self):
        """groups= or invisible= leaves it reachable and leaves the next
        person reasoning about it.

        Asserted on the BUTTON, not on the words. The comment that
        replaced it says "Cancel Student's Booking" while explaining why
        it went, so a bare phrase search fails on the explanation - which
        is what it did.
        """
        arch = self._form().arch
        for tag in re.findall(r'<button\b[^>]*>', arch):
            self.assertNotIn(
                'name="action_cancel"', tag,
                "a button in the booking form still calls action_cancel, "
                "so the desk still has two ways to cancel: %s" % tag)
            self.assertNotIn(
                "Cancel Student's Booking", tag,
                "a button in the booking form is still labelled Cancel "
                "Student's Booking: %s" % tag)

    def test_the_method_is_still_on_the_model(self):
        """Only the button went. The portal posts to action_cancel, both
        wizards call it, and action_cancel_class calls it per student."""
        self.assertTrue(
            hasattr(self.env['fitness.booking'], 'action_cancel'),
            "action_cancel has been removed from the model, which breaks "
            "the student's own Cancel in the portal")

    def test_no_view_on_our_model_calls_it_any_more(self):
        """The Roster and the list were checked by hand once; this keeps
        them checked.

        Scoped to fitness.booking. sale.order, account.payment,
        gamification.goal and mail.activity all have their own
        action_cancel buttons, and counting those made the first version
        of this fail on a tree that was entirely correct.
        """
        views = self.env['ir.ui.view'].sudo().search(
            [('arch_db', 'like', 'action_cancel'),
             ('model', '=', 'fitness.booking')])
        offenders = [
            v.xml_id or v.name for v in views
            if 'name="action_cancel"' in (v.arch or '')]
        self.assertEqual(
            offenders, [],
            "these fitness.booking views still have a button calling "
            "action_cancel: %s" % offenders)
