# -*- coding: utf-8 -*-
"""Adding a student to a class from the class itself.

The case this exists for is the one that used to be impossible: a student
with no private credit. Creating a booking by hand for them was refused by
_select_payment_source - "No active subscription or package covers this
class type" - because the credit was the thing agreed in conversation and
never recorded anywhere.

So these do not test the wizard's arithmetic. They test that the booking and
the paid line both really come into existence, through
fitness.booking.create() with every rule still running, for a student who
had nothing beforehand. That is the whole feature; anything less would pass
while the thing it exists for still failed.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAddStudentWizard(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.manager = cls.env["res.users"].create({
            "name": "Add Student Manager",
            "login": "add.student.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Add student room", "classroom_type": "reformer",
            "capacity": 6})
        cls.private_type = cls.env["fitness.class.type"].create({
            "name": "Add student private", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "private",
            "classroom_id": cls.room.id})
        cls.group_type = cls.env["fitness.class.type"].create({
            "name": "Add student group", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})
        # Somebody who has never bought anything. The point of the feature.
        cls.student = cls.env["res.partner"].create({
            "name": "Private Student", "email": "private.student@example.invalid"})

    def _event(self, days=21, ctype=None, name="Private class"):
        """Three weeks out on purpose: past the seven-day booking window.

        A private class is agreed weeks ahead as a matter of course, so if
        the wizard did not deal with the window it would fail on the ordinary
        case rather than on an edge one.
        """
        start = fields.Datetime.now() + timedelta(days=days)
        event = self.env["calendar.event"].create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": (ctype or self.private_type).id,
            "is_fitness_class": True,
            "session_type": (ctype or self.private_type).session_type,
        })
        return event

    def _wizard(self, event, student=None, price=None):
        Wiz = self.env["fitness.add.student.wizard"].with_user(self.manager)
        vals = Wiz.with_context(
            default_event_id=event.id, active_id=event.id,
            active_model="calendar.event").default_get(
                ["event_id", "product_id", "price"])
        vals["student_id"] = (student or self.student).id
        if price is not None:
            vals["price"] = price
        return Wiz.create(vals)

    # -- the case it exists for -------------------------------------------

    def test_a_student_with_no_credit_can_be_added(self):
        """Booking and paid line both created, in one action."""
        event = self._event()
        before = self.env["fitness.booking"].search_count(
            [("student_id", "=", self.student.id)])
        self.assertEqual(before, 0, "the fixture student already had bookings")

        wizard = self._wizard(event, price=55.0)
        wizard.action_add()

        booking = self.env["fitness.booking"].search(
            [("student_id", "=", self.student.id),
             ("calendar_event_id", "=", event.id)])
        self.assertEqual(
            len(booking), 1,
            "no booking was created for a student with no private credit - "
            "which is the one case this wizard exists for")
        self.assertEqual(booking.state, "booked")
        self.assertTrue(
            booking.package_order_line_id,
            "the booking has no payment source, so nothing was actually paid")
        self.assertAlmostEqual(
            booking.package_order_line_id.price_unit, 55.0, 2,
            "the agreed price was not what got charged")
        self.assertEqual(
            booking.package_order_line_id.order_id.state, "sale",
            "the order was left as a draft, so the credit does not exist")

    def test_without_the_wizard_that_same_booking_is_still_refused(self):
        """The problem is real, and the wizard is not masking a non-problem.

        Creating the booking directly - which is what Student Bookings does -
        must still fail for a student with no private credit. If this ever
        stops raising, the test above has stopped proving anything, because
        it would pass with the wizard doing nothing at all.
        """
        event = self._event()
        with self.assertRaises(UserError) as caught:
            self.env["fitness.booking"].create({
                "student_id": self.student.id,
                "calendar_event_id": event.id,
                "manager_override_timewindow": True,
            })
        self.assertIn(
            "covers this class", str(caught.exception).lower(),
            "the refusal changed shape - it now reads %r. Check the wizard "
            "still side-steps it by supplying a source rather than by "
            "bypassing validation." % str(caught.exception))

    def test_the_default_price_is_the_products_price(self):
        event = self._event()
        wizard = self._wizard(event)
        self.assertGreater(
            wizard.price, 0,
            "the wizard opened with no price, so the studio would charge zero "
            "by accident")
        self.assertEqual(wizard.product_id.fitness_session_type, "private")

    def test_the_agreed_price_overrides_the_list_price(self):
        """The price is what the conversation landed on, not the list."""
        event = self._event()
        wizard = self._wizard(event, price=42.5)
        wizard.action_add()
        line = self.env["fitness.booking"].search(
            [("student_id", "=", self.student.id)]).package_order_line_id
        self.assertAlmostEqual(line.price_unit, 42.5, 2)

    def test_the_student_appears_on_the_roster(self):
        event = self._event()
        self._wizard(event).action_add()
        event.invalidate_recordset()
        self.assertIn(
            self.student, event.booking_ids.mapped("student_id"),
            "the student was booked but does not appear on the class roster")

    def test_the_seat_is_counted(self):
        event = self._event()
        before = event.booked_seats
        self._wizard(event).action_add()
        event.invalidate_recordset()
        self.assertEqual(
            event.booked_seats, before + 1,
            "the class does not know it has somebody in it")

    # -- the rules it must not bypass --------------------------------------

    def test_a_full_class_is_refused(self):
        """Pre-checked, so the message names the class rather than the rule."""
        event = self._event()
        event.capacity = 1
        self._wizard(event).action_add()
        other = self.env["res.partner"].create({"name": "Second student"})
        event.invalidate_recordset()
        with self.assertRaises(UserError):
            self._wizard(event, student=other).action_add()

    def test_a_cancelled_class_is_refused(self):
        event = self._event()
        event.class_state = "cancelled"
        with self.assertRaises(UserError):
            self._wizard(event).action_add()

    def test_the_same_student_cannot_be_added_twice(self):
        """fitness.booking.create() still runs; this does not go around it."""
        event = self._event()
        self._wizard(event).action_add()
        event.invalidate_recordset()
        with self.assertRaises(Exception):
            self._wizard(event).action_add()

    def test_a_non_manager_is_refused(self):
        event = self._event()
        plain = self.env["res.users"].create({
            "name": "Not a manager",
            "login": "add.student.plain@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        wizard = self._wizard(event)
        with self.assertRaises(UserError):
            wizard.with_user(plain).action_add()

    # -- it must not disturb the ordinary flow -----------------------------

    def test_an_ordinary_group_booking_still_picks_its_own_source(self):
        """The normal path is untouched: no source given, helper still runs.

        The wizard works by handing create() an explicit source, which is why
        _select_payment_source never fires for it. This pins that the helper
        is still doing its job for everybody else - if the wizard had changed
        that behaviour globally, ordinary bookings would stop choosing the
        credit that expires soonest.
        """
        event = self._event(days=3, ctype=self.group_type, name="Group class")
        buyer = self.env["res.users"].create({
            "name": "Ordinary Student",
            "login": "add.student.ordinary@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id])]})
        pack = self.env["product.template"].create({
            "name": "Ordinary pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "reformer",
            "fitness_session_type": "group"})
        order = self.env["sale.order"].create(
            {"partner_id": buyer.partner_id.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": pack.list_price,
            "fitness_class_type": "reformer"})
        order.action_confirm()

        booking = self.env["fitness.booking"].create({
            "student_id": buyer.partner_id.id,
            "calendar_event_id": event.id,
        })
        self.assertEqual(
            booking.package_order_line_id, order.order_line[:1],
            "an ordinary booking no longer chooses its own payment source")

    def test_a_private_class_still_holds_one_person(self):
        """Capacity is the model's, not the wizard's."""
        event = self._event()
        self.assertEqual(
            event.capacity, 1,
            "a private class should hold one person; capacity is %s"
            % event.capacity)


@tagged("post_install", "-at_install")
class TestCourtesyBooking(TransactionCase):
    """Giving a class away on an ordinary group class.

    The wizard was built for private classes agreed in conversation. This is
    the other case: a student past their trial, or anyone the studio wants to
    treat, put into a normal group class for nothing. It still writes a real
    confirmed order - at zero - because a booking with no payment source is
    the shape behind every records-disagree fault in this codebase.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Courtesy Manager",
            "login": "courtesy.mgr@example.invalid",
            "email": "courtesy.mgr@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.student = cls.env["res.partner"].create({
            "name": "Courtesy Student", "email": "courtesy@example.invalid"})
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Courtesy room", "classroom_type": "barre", "capacity": 6})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Courtesy Barre", "classroom_type": "barre",
            "duration": 45, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})

    def _group_class(self):
        start = fields.Datetime.now() + timedelta(days=3)
        return self.env["calendar.event"].create({
            "name": "Ordinary group class", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True})

    def _wizard(self, event, **extra):
        vals = {"event_id": event.id, "student_id": self.student.id,
                "mode": "courtesy", "reason": "A treat, she has had her trial."}
        vals.update(extra)
        return self.env["fitness.add.student.wizard"].with_user(
            self.manager).create(vals)

    def test_a_free_booking_on_an_ordinary_group_class(self):
        """Not a private class - the case the wizard could not do before."""
        event = self._group_class()
        self.assertEqual(event.class_type_id.session_type, "group")

        self._wizard(event).action_add()

        booking = self.env["fitness.booking"].search([
            ("student_id", "=", self.student.id),
            ("calendar_event_id", "=", event.id)])
        self.assertEqual(len(booking), 1, "the student has to end up booked")
        self.assertEqual(booking.state, "booked")

    def test_the_order_behind_it_costs_nothing(self):
        event = self._group_class()
        self._wizard(event).action_add()

        order = self.env["sale.order"].search(
            [("partner_id", "=", self.student.id)], order="id desc", limit=1)
        self.assertEqual(order.state, "sale")
        self.assertEqual(order.amount_total, 0.0,
                         "a given class must not show as money taken")
        self.assertTrue(order.order_line[:1].product_id.product_tmpl_id
                        .fitness_is_courtesy,
                        "it has to be charged against a courtesy product")

    def test_the_seat_count_updates(self):
        event = self._group_class()
        before = event.booked_seats or 0

        self._wizard(event).action_add()
        event.invalidate_recordset()

        self.assertEqual(event.booked_seats, before + 1,
                         "the roster has to know somebody is coming")

    def test_a_free_class_demands_a_reason(self):
        event = self._group_class()
        with self.assertRaises(UserError):
            self._wizard(event, reason="").action_add()

    def test_a_reason_of_spaces_is_not_a_reason(self):
        event = self._group_class()
        with self.assertRaises(UserError):
            self._wizard(event, reason="   ").action_add()

    def test_the_price_box_cannot_charge_a_donated_class(self):
        """Zero whatever is typed - the studio cannot bill for a gift by
        leaving an old number in the field."""
        event = self._group_class()
        self._wizard(event, price=35.0).action_add()

        order = self.env["sale.order"].search(
            [("partner_id", "=", self.student.id)], order="id desc", limit=1)
        self.assertEqual(order.amount_total, 0.0)

    def test_the_confirmation_does_not_claim_a_gift_was_charged(self):
        """The order said 0.00 and the dialog said 25.00.

        The test above pins the order; nothing pinned the sentence the studio
        actually reads, and it was built from the price box rather than from
        the line. So giving a class away reported "charged 35.00" on an order
        that reads nothing, and only somebody who opened the order would have
        known which to believe.
        """
        event = self._group_class()
        res = self._wizard(event, price=35.0).action_add()
        message = res["params"]["message"]

        self.assertNotIn(
            "35", message,
            "the confirmation still reports the price box for a free class")
        order = self.env["sale.order"].search(
            [("partner_id", "=", self.student.id)], order="id desc", limit=1)
        self.assertIn(order.name, message, "the order is not named")

    def test_courtesy_products_are_not_in_the_shop(self):
        """A one-class package at zero euros would otherwise sit on the
        Classes tab, which is an invitation rather than a gift."""
        shop = self.env["product.template"].search([
            ("fitness_is_package", "=", True),
            ("fitness_class_count", "<=", 1),
            ("fitness_is_courtesy", "=", False)])
        courtesy = self.env.ref("fitness_packages.product_courtesy_barre")

        self.assertTrue(courtesy.fitness_is_courtesy)
        self.assertNotIn(courtesy, shop)

    def test_charging_a_group_class_is_refused_in_words(self):
        """There is no group single-class product to charge against - the
        booking validator would refuse it anyway, with a sentence about
        packages and sessions that says nothing about what to do."""
        event = self._group_class()
        wiz = self._wizard(event, mode="charge", price=30.0, reason="")

        with self.assertRaises(UserError) as caught:
            wiz.action_add()
        self.assertIn("group class", str(caught.exception))

    def test_a_group_class_opens_on_the_mode_that_works(self):
        """Defaulting to charge would put her one save away from an error."""
        event = self._group_class()
        wiz = self.env["fitness.add.student.wizard"].with_user(
            self.manager).with_context(
                default_event_id=event.id, active_id=event.id,
                active_model="calendar.event").create(
                    {"student_id": self.student.id})

        self.assertEqual(wiz.mode, "courtesy")
