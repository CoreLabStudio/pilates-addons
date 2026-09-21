# -*- coding: utf-8 -*-
"""Managing a day of classes, in both directions.

Cancelling was the only thing this screen could do, and a cancelled class
then disappeared from it - so the one place that knew about the day could not
undo what it had just done. Putting a class back meant going somewhere else
entirely, to a list that hid cancelled classes by default.

These cover the round trip: switch a class off, find it still listed and
marked cancelled, switch it back on, find it running again.

The student half is asymmetric on purpose and is asserted as such. Cancelling
returns the credit and tells them. Reopening does NOT re-book anybody - their
credit is theirs and they book again - which is what "Put classes back" on
the Schedule already does, and is said on screen rather than left to be
discovered.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestManageClassesBothWays(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.manager = cls.env["res.users"].create({
            "name": "Manage Classes Manager",
            "login": "manage.classes@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.student = cls.env["res.users"].create({
            "name": "Manage Classes Student",
            "login": "manage.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        cls.partner = cls.student.partner_id
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Manage barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group"})
        pack = cls.env["product.template"].create({
            "name": "Manage pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 20,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group"})
        order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": pack.list_price,
            "fitness_class_type": "barre"})
        order.action_confirm()
        cls.credit = order.order_line[:1]

    def _event(self, hours=48, name="Manage class"):
        start = fields.Datetime.now() + timedelta(hours=hours)
        return self.env["calendar.event"].create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True,
            "capacity": 10})

    def _booking(self, event):
        return self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": self.credit.id,
            "manager_override_timewindow": True})

    def _wizard(self, day):
        wiz = self.env["fitness.class.bulk.cancel.wizard"].with_user(
            self.manager).create({"day": day})
        wiz._onchange_day()
        return wiz

    def _line(self, wizard, event):
        line = wizard.line_ids.filtered(lambda l: l.event_id == event)
        self.assertTrue(line, "the day does not list %r at all" % event.name)
        return line

    # -- direction one: on -> off -----------------------------------------

    def test_switching_a_class_off_cancels_it_and_returns_the_credit(self):
        event = self._event()
        booking = self._booking(event)
        before = self.credit.fitness_remaining_classes

        wizard = self._wizard(fields.Date.to_date(event.start))
        line = self._line(wizard, event)
        self.assertTrue(line.is_on, "a running class should arrive switched on")
        line.is_on = False
        wizard.action_apply()

        self.assertEqual(event.class_state, "cancelled")
        self.assertEqual(booking.state, "cancelled")
        self.assertGreater(
            self.credit.fitness_remaining_classes, before,
            "the student's credit was not returned")

    # -- direction two: off -> on -----------------------------------------

    def test_switching_a_cancelled_class_back_on_reopens_it(self):
        event = self._event()
        event.with_user(self.manager).action_cancel_class()
        self.assertEqual(event.class_state, "cancelled")

        wizard = self._wizard(fields.Date.to_date(event.start))
        line = self._line(wizard, event)
        self.assertFalse(
            line.is_on, "a cancelled class should arrive switched off")
        self.assertEqual(
            line.class_state, "cancelled",
            "the row must say which state the class is actually in")

        line.is_on = True
        wizard.action_apply()
        self.assertEqual(
            event.class_state, "scheduled",
            "switching a cancelled class on did not put it back")

    def test_a_reopened_class_can_be_booked_again(self):
        """Back on the timetable has to mean bookable, not merely visible."""
        event = self._event()
        event.with_user(self.manager).action_cancel_class()
        wizard = self._wizard(fields.Date.to_date(event.start))
        self._line(wizard, event).is_on = True
        wizard.action_apply()

        booking = self._booking(event)
        self.assertEqual(
            booking.state, "booked",
            "a class put back could not take a booking")

    def test_reopening_does_not_re_book_the_students_it_cancelled(self):
        """The asymmetry, asserted rather than assumed."""
        event = self._event()
        booking = self._booking(event)

        wizard = self._wizard(fields.Date.to_date(event.start))
        self._line(wizard, event).is_on = False
        wizard.action_apply()
        self.assertEqual(booking.state, "cancelled")
        credit_after_cancel = self.credit.fitness_remaining_classes

        again = self._wizard(fields.Date.to_date(event.start))
        self._line(again, event).is_on = True
        again.action_apply()

        self.assertEqual(event.class_state, "scheduled")
        self.assertEqual(
            booking.state, "cancelled",
            "reopening the class re-booked a student who was told it was off")
        self.assertEqual(
            self.credit.fitness_remaining_classes, credit_after_cancel,
            "reopening took a credit back off the student")
        self.assertEqual(
            event.booked_seats, 0,
            "the class came back with a seat still counted as taken")

    # -- both at once, and the guard rails ---------------------------------

    def test_one_pass_can_close_one_class_and_open_another(self):
        closing = self._event(48, "Still running")
        opening = self._event(49, "Already off")
        opening.with_user(self.manager).action_cancel_class()

        wizard = self._wizard(fields.Date.to_date(closing.start))
        self._line(wizard, closing).is_on = False
        self._line(wizard, opening).is_on = True
        self.assertEqual(wizard.change_count, 2)
        wizard.action_apply()

        self.assertEqual(closing.class_state, "cancelled")
        self.assertEqual(opening.class_state, "scheduled")

    def test_a_switch_left_alone_changes_nothing(self):
        """Arriving set to the truth means untouched rows are not instructions."""
        running = self._event(48, "Left alone")
        wizard = self._wizard(fields.Date.to_date(running.start))
        self.assertEqual(
            wizard.change_count, 0,
            "the day arrived already asking for changes nobody made")
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(running.class_state, "scheduled")

    def test_the_summary_names_both_directions(self):
        closing = self._event(48, "Closing")
        opening = self._event(49, "Opening")
        opening.with_user(self.manager).action_cancel_class()
        wizard = self._wizard(fields.Date.to_date(closing.start))
        self._line(wizard, closing).is_on = False
        self._line(wizard, opening).is_on = True
        summary = wizard.selection_summary or ""
        self.assertIn("Switching off", summary)
        self.assertIn("Switching this class on", summary)
        self.assertIn(
            "not re-booked", summary,
            "the summary must say reopening does not put the students back")

    def test_the_summary_says_one_class_in_the_singular(self):
        """One class is the ordinary case, so it must not read "1 classes"."""
        event = self._event()
        wizard = self._wizard(fields.Date.to_date(event.start))
        self._line(wizard, event).is_on = False
        summary = wizard.selection_summary or ""
        self.assertIn("Switching off this class", summary)
        self.assertNotIn("1 classes", summary)

        event.with_user(self.manager).action_cancel_class()
        again = self._wizard(fields.Date.to_date(event.start))
        self._line(again, event).is_on = True
        summary = again.selection_summary or ""
        self.assertIn("Switching this class on", summary)
        self.assertNotIn("1 classes", summary)

    def test_the_day_summary_counts_the_cancelled_ones_separately(self):
        running = self._event(48, "Running one")
        off = self._event(49, "Off one")
        off.with_user(self.manager).action_cancel_class()
        wizard = self._wizard(fields.Date.to_date(running.start))
        self.assertIn(
            "already cancelled", wizard.day_summary or "",
            "the day's headline does not mention the cancelled classes it "
            "is now showing: %r" % wizard.day_summary)
