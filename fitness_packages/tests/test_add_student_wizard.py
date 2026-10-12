# -*- coding: utf-8 -*-
"""Adding a student to a class from the class itself, on her own credit.

It used to sell the class every time: a new confirmed order at the typed
price, without looking at what she held. A student with a private class
left on her pack was charged again, and her paid class sat unused
(defect A6, reproduced: orders 1 -> 2, charged 45.00, her credit still 1).

Owner decision Q2: use her existing credit, never charge; with none, say
so and offer the desk. These test that the booking is made on what she
already has, through fitness.booking.create() with every rule running,
and that no order is ever created.

Clock pinned.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
PRIVATE_REFORMER = 'fitness_packages.product_private_single'


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
            "lang": "en_US",
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
        cls.private_single = cls.env.ref(PRIVATE_REFORMER)
        cls.group_pack = cls.env["product.template"].create({
            "name": "Add student group pack", "list_price": 100.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 10, "fitness_validity_days": 90,
            "fitness_class_type": "reformer", "fitness_session_type": "group"})

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.student = self.env["res.partner"].create({
            "name": "Private Student", "lang": "en_US",
            "email": "private.student@example.invalid"})

    # -- fixtures ------------------------------------------------------------

    def _event(self, days=21, ctype=None, name="Private class"):
        """Three weeks out on purpose: past the seven-day booking window.

        A private class is agreed weeks ahead as a matter of course, so if
        the wizard did not deal with the window it would fail on the ordinary
        case rather than on an edge one.
        """
        ctype = ctype or self.private_type
        start = PINNED + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": ctype.id, "is_fitness_class": True,
            "session_type": ctype.session_type,
        })

    def _credit(self, product=None, student=None):
        product = product or self.private_single
        order = self.env["sale.order"].sudo().create(
            {"partner_id": (student or self.student).id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 45.0,
            "fitness_class_type": "reformer"})
        order.action_confirm()
        return order.order_line[:1]

    def _wizard(self, event, student=None):
        Wiz = self.env["fitness.add.student.wizard"].with_user(self.manager)
        vals = Wiz.with_context(
            default_event_id=event.id, active_id=event.id,
            active_model="calendar.event").default_get(["event_id"])
        vals["student_id"] = (student or self.student).id
        return Wiz.create(vals)

    def _orders(self, student=None):
        return self.env["sale.order"].sudo().search_count(
            [("partner_id", "=", (student or self.student).id)])

    def _bookings(self, event):
        return self.env["fitness.booking"].search(
            [("student_id", "=", self.student.id),
             ("calendar_event_id", "=", event.id)])

    # -- A6: her own credit, never a second charge ----------------------------

    def test_she_is_booked_on_the_credit_she_already_has(self):
        """The reproduced case: a private credit, then Add a student."""
        line = self._credit()
        self.assertEqual(line.fitness_remaining_classes, 1)
        event = self._event()
        self.assertEqual(self._orders(), 1)

        self._wizard(event).action_add()

        booking = self._bookings(event)
        self.assertEqual(len(booking), 1)
        self.assertEqual(booking.package_order_line_id, line,
                         "she was not booked on the class she had paid for")
        self.assertEqual(line.fitness_remaining_classes, 0)
        self.assertEqual(self._orders(), 1, "she was charged a second time")

    def test_nothing_here_ever_creates_an_order(self):
        self._credit()
        before = self.env["sale.order"].sudo().search_count([])
        self._wizard(self._event()).action_add()
        self.assertEqual(self.env["sale.order"].sudo().search_count([]),
                         before)

    def test_the_dialog_names_the_credit_it_will_use(self):
        line = self._credit()
        wizard = self._wizard(self._event())
        self.assertTrue(wizard.has_credit)
        self.assertIn(line.order_id.name, wizard.credit_label)

    def test_the_soonest_expiring_credit_is_spent_first(self):
        later = self._credit()
        sooner = self._credit()
        later.fitness_validity_end_date = date(2026, 12, 30)
        sooner.fitness_validity_end_date = date(2026, 11, 20)
        event = self._event(days=10)
        self._wizard(event).action_add()
        self.assertEqual(self._bookings(event).package_order_line_id, sooner)

    def test_a_cancelled_orders_credit_is_not_used(self):
        line = self._credit()
        line.order_id._action_cancel()
        event = self._event()
        with self.assertRaises(UserError):
            self._wizard(event).action_add()
        self.assertFalse(self._bookings(event))
        self.assertEqual(line.fitness_remaining_classes, 1)

    def test_a_group_class_is_booked_on_her_pack(self):
        """Refused outright before - there was nothing to charge it as."""
        line = self._credit(self.group_pack)
        event = self._event(days=3, ctype=self.group_type, name="Group")
        self._wizard(event).action_add()
        self.assertEqual(self._bookings(event).package_order_line_id, line)
        self.assertEqual(line.fitness_remaining_classes, 9)

    # -- no credit: say so, offer the desk ------------------------------------

    def test_with_no_credit_nothing_is_booked_and_nothing_charged(self):
        event = self._event()
        with self.assertRaises(UserError) as caught:
            self._wizard(event).action_add()
        self.assertIn("desk", str(caught.exception))
        self.assertFalse(self._bookings(event))
        self.assertEqual(self._orders(), 0)

    def test_with_no_credit_the_dialog_says_so_and_offers_the_desk(self):
        wizard = self._wizard(self._event())
        self.assertFalse(wizard.has_credit)
        self.assertEqual(wizard.credit_label,
                         "Nothing she holds covers this class.")
        action = wizard.action_open_desk()
        self.assertEqual(action["res_model"], "fitness.desk.sale.wizard")
        self.assertEqual(action["context"]["default_partner_id"],
                         self.student.id)

    def test_the_form_shows_the_desk_only_without_credit(self):
        arch = self.env["fitness.add.student.wizard"].with_user(
            self.manager).get_view(view_type="form")["arch"]
        self.assertIn("action_open_desk", arch)
        self.assertIn("has_credit", arch)
        self.assertNotIn('name="price"', arch)

    def test_without_the_wizard_that_same_booking_is_still_refused(self):
        """A student with no credit is refused by create() as before."""
        event = self._event()
        with self.assertRaises(UserError) as caught:
            self.env["fitness.booking"].create({
                "student_id": self.student.id,
                "calendar_event_id": event.id,
                "manager_override_timewindow": True,
            })
        self.assertIn("covers this class", str(caught.exception).lower())

    # -- the rules it must not bypass ----------------------------------------

    def test_the_student_appears_on_the_roster_and_the_seat_is_counted(self):
        self._credit()
        event = self._event()
        before = event.booked_seats
        self._wizard(event).action_add()
        event.invalidate_recordset()
        self.assertIn(self.student, event.booking_ids.mapped("student_id"))
        self.assertEqual(event.booked_seats, before + 1)

    def test_a_full_class_is_refused(self):
        """Pre-checked, so the message names the class rather than the rule."""
        self._credit()
        event = self._event()
        event.capacity = 1
        self._wizard(event).action_add()
        other = self.env["res.partner"].create({"name": "Second student"})
        self._credit(student=other)
        event.invalidate_recordset()
        with self.assertRaises(UserError):
            self._wizard(event, student=other).action_add()

    def test_a_cancelled_class_is_refused(self):
        self._credit()
        event = self._event()
        event.class_state = "cancelled"
        with self.assertRaises(UserError):
            self._wizard(event).action_add()

    def test_the_same_student_cannot_be_added_twice(self):
        """fitness.booking.create() still runs; this does not go around it."""
        self._credit()
        self._credit()
        event = self._event()
        event.capacity = 2
        self._wizard(event).action_add()
        event.invalidate_recordset()
        with self.assertRaises(Exception):
            self._wizard(event).action_add()

    def test_a_non_manager_is_refused(self):
        self._credit()
        event = self._event()
        plain = self.env["res.users"].create({
            "name": "Not a manager",
            "login": "add.student.plain@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        wizard = self._wizard(event)
        with self.assertRaises(UserError):
            wizard.with_user(plain).action_add()
        with self.assertRaises(UserError):
            wizard.with_user(plain).action_open_desk()

    # -- it must not disturb the ordinary flow --------------------------------

    def test_an_ordinary_group_booking_still_picks_its_own_source(self):
        event = self._event(days=3, ctype=self.group_type, name="Group class")
        buyer = self.env["res.users"].create({
            "name": "Ordinary Student",
            "login": "add.student.ordinary@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id])]})
        line = self._credit(self.group_pack, student=buyer.partner_id)
        booking = self.env["fitness.booking"].create({
            "student_id": buyer.partner_id.id,
            "calendar_event_id": event.id,
        })
        self.assertEqual(booking.package_order_line_id, line)

    def test_a_private_class_still_holds_one_person(self):
        """Capacity is the model's, not the wizard's."""
        self.assertEqual(self._event().capacity, 1)


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
