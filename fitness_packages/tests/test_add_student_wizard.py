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
class TestCourtesyProductsStillExist(TransactionCase):
    """The free option moved off this screen to the gift wizard.

    TestCourtesyBooking went with it: giving a class away is now tested in
    fitness_portal/tests/test_gift.py, against the wizard that actually does
    it, for classes, packs and memberships alike. What is still worth
    asserting here is the products themselves - the gift wizard books a given
    class against them, and a zero-price one-class package must never reach
    the shop, where it would read as an invitation rather than a gift.
    """

    longMessage = False

    def test_courtesy_products_are_not_in_the_shop(self):
        shop = self.env["product.template"].search([
            ("fitness_is_package", "=", True),
            ("fitness_class_count", "<=", 1),
            ("fitness_is_courtesy", "=", False)])
        courtesy = self.env.ref("fitness_packages.product_courtesy_barre")

        self.assertTrue(courtesy.fitness_is_courtesy)
        self.assertNotIn(courtesy, shop)

    def test_both_disciplines_still_have_one_to_give(self):
        """The gift wizard resolves these by xmlid; a missing one would make
        gifting a class in that discipline impossible."""
        for xmlid in ("fitness_packages.product_courtesy_barre",
                      "fitness_packages.product_courtesy_reformer"):
            product = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(product, "%s is gone" % xmlid)
            self.assertEqual(product.list_price, 0.0,
                             "%s is not free any more" % xmlid)
