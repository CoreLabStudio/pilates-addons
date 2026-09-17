# -*- coding: utf-8 -*-
"""Cancelling with a reason, and cancelling a day in one pass.

Parts C and G. Both are about the studio being able to say why, and about a
cancellation reaching the student with those words on it - so the assertions
are about what ends up on the booking, not about the wizards' internals.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCancelReasonAndBulk(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.student = cls.env["res.users"].create({
            "name": "Reason Student",
            "login": "reason.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.student.partner_id
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Reason Barre",
            "classroom_type": "barre",
            "duration": 45,
            "level": "all",
            "session_type": "group",
        })
        # A booking needs something to pay with - the model refuses one that
        # no credit covers, which is a rule of its own and not what these
        # tests are about. Same shape as test_reassign_wizard uses.
        cls.pack = cls.env["product.template"].create({
            "name": "Reason pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 20,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })
        order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": cls.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": cls.pack.list_price,
            "fitness_class_type": "barre",
        })
        order.action_confirm()
        cls.line = order.order_line[:1]

    def _event(self, hours=48, name="Reason class"):
        start = fields.Datetime.now() + timedelta(hours=hours)
        return self.env["calendar.event"].create({
            "name": name,
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
            "capacity": 10,
        })

    def _booking(self, event):
        # The credit line is named, and the time window overridden: neither is
        # what these tests are about, and both refuse a booking otherwise.
        return self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": self.line.id,
            "manager_override_timewindow": True,
        })

    # -- PART C ------------------------------------------------------------

    def test_a_cancellation_keeps_the_reason(self):
        booking = self._booking(self._event())
        wizard = self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id,
            "reason": "The instructor is unwell.",
        })
        wizard.action_confirm()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            booking.cancellation_reason, "The instructor is unwell.",
            "a cancelled booking that records no reason leaves nobody able to "
            "say next week why it happened",
        )

    def test_the_reason_is_optional(self):
        booking = self._booking(self._event())
        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id,
        }).action_confirm()
        self.assertEqual(booking.state, "cancelled")
        self.assertFalse(booking.cancellation_reason)

    def test_whitespace_is_not_a_reason(self):
        """A notification whose reason is a space helps nobody."""
        booking = self._booking(self._event())
        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id, "reason": "   ",
        }).action_confirm()
        self.assertFalse(booking.cancellation_reason)

    def test_the_reassign_wizard_records_it_too(self):
        """The bulk path is this wizard, so it needs the same box."""
        booking = self._booking(self._event())
        self.env["fitness.booking.reassign.wizard"].create({
            "booking_ids": [(6, 0, booking.ids)],
            "reason": "Not enough students to run it.",
        }).action_cancel_only()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(booking.cancellation_reason,
                         "Not enough students to run it.")

    # -- PART G ------------------------------------------------------------

    def _wizard_for(self, day):
        # Through the onchange, the way the dialog itself loads: the lines are
        # built there, not by a compute, so creating the record alone leaves
        # an empty list.
        wizard = self.env["fitness.class.bulk.cancel.wizard"].create({"day": day})
        wizard._onchange_day()
        return wizard

    @staticmethod
    def _tick(wizard, events):
        for line in wizard.line_ids:
            line.selected = line.event_id in events

    def test_the_day_lists_its_own_classes(self):
        event = self._event()
        wizard = self._wizard_for(fields.Date.to_date(event.start))
        self.assertIn(
            event, wizard.line_ids.mapped("event_id"),
            "the page exists to show a day's classes; if it cannot find them "
            "there is nothing to tick",
        )

    def test_the_day_is_summarised(self):
        """PART I - the number, so nobody counts a column by hand."""
        event = self._event()
        self._booking(event)
        wizard = self._wizard_for(fields.Date.to_date(event.start))
        self.assertTrue(wizard.day_summary)
        self.assertIn("across", wizard.day_summary)

    def test_cancelling_a_selection_cancels_the_classes_and_the_bookings(self):
        first, second = self._event(48, "Bulk one"), self._event(49, "Bulk two")
        booking = self._booking(first)
        wizard = self._wizard_for(fields.Date.to_date(first.start))
        self._tick(wizard, first | second)
        wizard.reason = "The studio is closed for the storm."
        wizard.action_cancel_selected()
        self.assertEqual(first.class_state, "cancelled")
        self.assertEqual(second.class_state, "cancelled")
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(booking.cancellation_reason,
                         "The studio is closed for the storm.")

    def test_a_cancelled_class_drops_off_the_list(self):
        """So a second pass over the same day cannot double-cancel."""
        event = self._event()
        wizard = self._wizard_for(fields.Date.to_date(event.start))
        self._tick(wizard, event)
        wizard.action_cancel_selected()
        again = self._wizard_for(fields.Date.to_date(event.start))
        self.assertNotIn(event, again.line_ids.mapped("event_id"))

    def test_cancelling_nothing_is_refused(self):
        wizard = self._wizard_for(fields.Date.context_today(self.env.user))
        with self.assertRaises(UserError):
            wizard.action_cancel_selected()

    def test_a_class_cancelled_meanwhile_is_skipped_not_fatal(self):
        """Somebody else may act while this dialog is open.

        Skipping that class is right; failing the whole batch over it, and
        leaving the rest of the day running, is not.
        """
        first, second = self._event(48, "Bulk one"), self._event(49, "Bulk two")
        wizard = self._wizard_for(fields.Date.to_date(first.start))
        self._tick(wizard, first | second)
        first.class_state = "cancelled"
        wizard.action_cancel_selected()
        self.assertEqual(second.class_state, "cancelled",
                         "the rest of the batch should still go through")
