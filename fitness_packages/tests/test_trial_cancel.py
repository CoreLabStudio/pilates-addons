# -*- coding: utf-8 -*-
"""Cancelling a trial booking hands the trial back, not a one-room credit.

A trial is claimed by booking a class, and which class decides the
discipline. Cancelling used to undo only half of that: the credit came back,
but it came back tagged to the room the student had just cancelled out of,
and its order stayed confirmed. The schedule then offered that one room only,
while the home page still said the trial was waiting - so the choice the
student had backed out of had been made for them anyway.

These are model-level tests on purpose. The behaviour is entirely in
fitness.booking.action_cancel, and a TransactionCase exercises it without the
HTTP session handling that makes the portal's own suite unreliable.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrialCancelReleasesClaim(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The opening-date rule refuses classes before the studio opens, and
        # the seven-day window refuses ones far ahead. Neither is under test,
        # and together they can leave no bookable date at all.
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.student = cls.env["res.users"].create({
            "name": "Trial Cancel Student",
            "login": "trial.cancel@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.student.partner_id

    def _class_type(self, room, name):
        return self.env["fitness.class.type"].create({
            "name": name,
            "classroom_type": room,
            "duration": 45,
            "level": "all",
            "session_type": "group",
        })

    def _event(self, room, name):
        start = fields.Datetime.now() + timedelta(days=2)
        return self.env["calendar.event"].create({
            "name": name,
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self._class_type(room, name + " type").id,
            "is_fitness_class": True,
        })

    def _confirmed_order(self, product, price):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": price,
            "fitness_class_type": product.fitness_class_type,
        })
        order.action_confirm()
        return order

    def _book_and_cancel(self, order, event):
        booking = self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": order.order_line[:1].id,
        })
        booking.with_user(self.student).action_cancel()
        return booking

    # ── the fix ──────────────────────────────────────────────────────────

    def test_cancelling_a_trial_gives_back_the_entitlement_not_a_credit(self):
        """The student ends up where they started: nothing owned, nothing
        claimed. A restored credit tagged to one room is what narrowed the
        schedule to that room."""
        trial = self.env.ref("fitness_packages.product_reformer_trial")
        order = self._confirmed_order(trial, 0.0)
        booking = self._book_and_cancel(order, self._event("reformer", "Cancel me"))
        line = order.order_line[:1]

        self.assertTrue(booking.credit_returned,
                        "the cancellation did not qualify for a refund at all")
        self.assertEqual(line.fitness_remaining_classes, 0,
                         "a room-specific credit was left behind, which is "
                         "what limited the schedule to that room")
        self.assertEqual(order.state, "cancel",
                         "the trial order stayed confirmed, so the entitlement "
                         "still counted as spent")

    def test_the_other_room_can_then_be_claimed(self):
        """Reopening both rooms is only real if the other one can be booked."""
        reformer = self.env.ref("fitness_packages.product_reformer_trial")
        self._book_and_cancel(self._confirmed_order(reformer, 0.0),
                              self._event("reformer", "Reformer first"))

        barre = self.env.ref("fitness_packages.product_barre_trial")
        order = self._confirmed_order(barre, 0.0)
        booking = self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": self._event("barre", "Barre after").id,
            "package_order_line_id": order.order_line[:1].id,
        })
        self.assertEqual(booking.state, "booked",
                         "after cancelling the Reformer trial the student "
                         "could not claim the Barre one")

    # ── what the fix must not touch ──────────────────────────────────────

    def test_a_grandfathered_second_trial_is_not_taken_away(self):
        """A few students were given two free trials before the one-per-student
        rule existed. Each sits on its own single-line zero-priced order, so
        each looks releasable on its own. Releasing one would quietly cost
        them a free class, so while another trial credit is still theirs the
        restored credit is what they keep."""
        first = self._confirmed_order(
            self.env.ref("fitness_packages.product_reformer_trial"), 0.0)
        second = self._confirmed_order(
            self.env.ref("fitness_packages.product_barre_trial"), 0.0)

        self._book_and_cancel(first, self._event("reformer", "One of two"))

        self.assertEqual(
            first.order_line[:1].fitness_remaining_classes, 1,
            "the cancelled trial was released even though the student still "
            "held a second one - that is a free class taken off them")
        self.assertEqual(first.state, "sale",
                         "the order was cancelled while a second trial stood")
        self.assertEqual(
            second.order_line[:1].fitness_remaining_classes, 1,
            "the untouched second trial lost its credit")

    def test_a_paid_pack_keeps_its_restored_credit(self):
        """The release is only ever for a free trial. A pack somebody paid
        for gets its credit back and keeps its order, as it always did."""
        pack = self.env["product.template"].create({
            "name": "Paid Pack For Cancel Test",
            "list_price": 90.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_count": 5,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })
        order = self._confirmed_order(pack, 90.0)
        line = order.order_line[:1]
        before = line.fitness_remaining_classes

        self._book_and_cancel(order, self._event("barre", "Paid class"))

        self.assertEqual(line.fitness_remaining_classes, before,
                         "a paid pack lost the credit it should have kept")
        self.assertEqual(order.state, "sale",
                         "a paid order was cancelled by the trial release")
