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
    def _switch_off(wizard, events):
        """Move these classes' switches to off, leaving the rest as they are.

        Only a switch that moves means anything now: every line arrives set to
        what its class already is, so setting the others would be asking for
        no change rather than asking to keep them.
        """
        for line in wizard.line_ids:
            if line.event_id in events:
                line.is_on = False

    @staticmethod
    def _switch_on(wizard, events):
        for line in wizard.line_ids:
            if line.event_id in events:
                line.is_on = True

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
        self._switch_off(wizard, first | second)
        wizard.reason = "The studio is closed for the storm."
        wizard.action_apply()
        self.assertEqual(first.class_state, "cancelled")
        self.assertEqual(second.class_state, "cancelled")
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(booking.cancellation_reason,
                         "The studio is closed for the storm.")

    def test_a_cancelled_class_stays_on_the_list_switched_off(self):
        """The reverse of what this used to assert, and the point of the rework.

        A cancelled class used to be filtered out, which made the dialog a
        one-way door: once a day was called off it vanished from the only
        screen that could have put it back. It stays now, showing cancelled,
        with its switch off - which is what makes changing your mind possible
        where the decision was made.
        """
        event = self._event()
        wizard = self._wizard_for(fields.Date.to_date(event.start))
        self._switch_off(wizard, event)
        wizard.action_apply()
        self.assertEqual(event.class_state, "cancelled")

        again = self._wizard_for(fields.Date.to_date(event.start))
        line = again.line_ids.filtered(lambda l: l.event_id == event)
        self.assertTrue(
            line, "a cancelled class fell off the day and cannot be put back")
        self.assertFalse(
            line.is_on, "the switch should arrive off for a cancelled class")
        self.assertEqual(line.class_state, "cancelled",
                         "the row does not say the class is cancelled")

    def test_applying_nothing_is_refused(self):
        wizard = self._wizard_for(fields.Date.context_today(self.env.user))
        with self.assertRaises(UserError):
            wizard.action_apply()

    # -- cancelling and restoring from the Schedule list --------------------

    def test_bulk_cancel_from_the_list(self):
        """The Schedule list offered only Odoo's Archive, which hides a row
        and tells nobody. Cancelling calls the class off properly."""
        first, second = self._event(48, "List one"), self._event(49, "List two")
        booking = self._booking(first)
        (first | second).action_cancel_classes_bulk()
        self.assertEqual(first.class_state, "cancelled")
        self.assertEqual(second.class_state, "cancelled")
        self.assertEqual(booking.state, "cancelled")

    def test_bulk_cancel_skips_what_is_already_off(self):
        first, second = self._event(48, "List one"), self._event(49, "List two")
        first.class_state = "cancelled"
        (first | second).action_cancel_classes_bulk()
        self.assertEqual(second.class_state, "cancelled")

    def test_a_class_can_be_put_back(self):
        """Called off by mistake, and there was no way to undo it."""
        event = self._event()
        event.action_cancel_classes_bulk()
        self.assertEqual(event.class_state, "cancelled")
        event.action_restore_classes()
        self.assertEqual(event.class_state, "scheduled")

    def test_putting_a_class_back_does_not_re_book_anybody(self):
        """The one thing restoring cannot undo.

        Their credits went back and they were told the class was off; some
        will have booked something else. Silently re-booking them would take
        a class off somebody twice.
        """
        event = self._event()
        booking = self._booking(event)
        event.action_cancel_classes_bulk()
        event.action_restore_classes()
        self.assertEqual(
            booking.state, "cancelled",
            "the booking stays cancelled - the message says so out loud",
        )
        self.assertEqual(event.booked_seats, 0)

    def test_a_class_cancelled_meanwhile_is_skipped_not_fatal(self):
        """Somebody else may act while this dialog is open.

        Skipping that class is right; failing the whole batch over it, and
        leaving the rest of the day running, is not.
        """
        first, second = self._event(48, "Bulk one"), self._event(49, "Bulk two")
        wizard = self._wizard_for(fields.Date.to_date(first.start))
        self._switch_off(wizard, first | second)
        first.class_state = "cancelled"
        wizard.action_apply()
        self.assertEqual(second.class_state, "cancelled",
                         "the rest of the batch should still go through")


@tagged("post_install", "-at_install")
class TestBulkCancelSurvivesTheSave(TransactionCase):
    """The dialog has to survive the client's save, not just the onchange.

    Cancelling a day was completely broken on screen - every attempt ended in
    "Missing required value for the field 'Event' (event_id)" and nothing was
    ever cancelled - while the tests above passed. They passed because they
    call _onchange_day() in Python, which fills the server-side cache with
    event_id already on it. The browser never does that.

    What the browser does is: open the dialog, receive lines from the
    onchange, let somebody tick one, then SAVE - and a wizard record that has
    never been stored saves its lines as creates. Each create has to carry
    event_id, which is required. The client can only send a field if the view
    names it AND it is allowed to send it: Odoo drops readonly fields from the
    payload unless they are marked force_save. event_id is readonly on the
    model, so naming it in the view was not enough on its own - that was tried
    first and the dialog failed in exactly the same way.

    These assert the round trip rather than the plumbing, so they keep their
    meaning if the dialog is rebuilt around them.
    """

    longMessage = False

    WIZARD = 'fitness.class.bulk.cancel.wizard'
    LINE = 'fitness.class.bulk.cancel.line'

    def _sub_list(self):
        """The line sub-view exactly as the client is handed it."""
        from lxml import etree
        view = self.env.ref(
            'fitness_bookings.view_fitness_bulk_cancel_wizard_form')
        arch = self.env[self.WIZARD].get_view(view.id, 'form')['arch']
        lists = etree.fromstring(arch).xpath('//field[@name="line_ids"]//list')
        self.assertTrue(lists, "the wizard no longer embeds a list of lines")
        return {f.get('name'): f for f in lists[0].xpath('./field')}

    def test_the_view_hands_the_client_every_field_it_must_send_back(self):
        """The root cause, stated as the rule it broke."""
        given = self._sub_list()
        Line = self.env[self.LINE]
        for name, field in Line._fields.items():
            if name == 'wizard_id':
                continue            # the one2many itself supplies this
            if not field.required or field.compute or field.related:
                continue
            self.assertIn(
                name, given,
                "%r is required on a wizard line but the view never gives it "
                "to the client, so the client cannot send it back and the "
                "save fails on a mandatory field" % name)
            if field.readonly:
                self.assertEqual(
                    given[name].get('force_save'), '1',
                    "%r is readonly, and Odoo drops readonly fields from the "
                    "save payload - it needs force_save=\"1\" or naming it in "
                    "the view achieves nothing" % name)

    def test_a_save_carrying_only_what_the_client_sends_still_works(self):
        """Save the wizard the way the browser does and cancel for real."""
        given = self._sub_list()
        Line = self.env[self.LINE]
        start = fields.Datetime.now() + timedelta(hours=30)
        ctype = self.env["fitness.class.type"].create({
            "name": "Save cycle barre", "classroom_type": "barre",
            "duration": 45, "level": "all", "session_type": "group"})
        event = self.env["calendar.event"].create({
            "name": "Save cycle class", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": ctype.id, "is_fitness_class": True,
            "capacity": 10})

        day = fields.Date.to_date(start)
        draft = self.env[self.WIZARD].new({'day': day})
        draft._onchange_day()
        line = draft.line_ids.filtered(lambda l: l.event_id == event)
        self.assertTrue(line, "the day did not list the class under test")

        # Only what the browser would put in the payload: a field the view
        # names, and either writable or force_save'd. Everything else the
        # client silently leaves out - which is the whole bug.
        sendable = {}
        for name, node in given.items():
            field = Line._fields[name]
            if field.readonly and node.get('force_save') != '1':
                continue
            value = line[name]
            sendable[name] = value.id if field.type == 'many2one' else value
        sendable['is_on'] = False          # the studio switches it off

        wizard = self.env[self.WIZARD].create({
            'day': day, 'line_ids': [(0, 0, sendable)]})
        self.assertEqual(
            wizard.line_ids.event_id, event,
            "the saved line lost the class it stood for")
        wizard.action_apply()
        self.assertEqual(
            event.class_state, "cancelled",
            "the class was not cancelled by a save the browser would make")
