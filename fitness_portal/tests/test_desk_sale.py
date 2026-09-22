# -*- coding: utf-8 -*-
"""Selling a pack at the desk, for cash and for nothing.

The point of both paths is that a real, confirmed order sits underneath, so
credits behave exactly as they do after an online purchase. These assert that
rather than assuming it: the expiry, the credit count and the ability to book
are all read back from the order the wizard produced.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDeskSale(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Desk Manager",
            "login": "desk.manager@example.invalid",
            "email": "desk.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.student = cls.env["res.users"].create({
            "name": "Desk Student",
            "login": "desk.student@example.invalid",
            "email": "desk.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Desk pack of 5",
            "list_price": 75.0,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_count": 5,
            "fitness_validity_days": 60,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

    def _wizard(self, **extra):
        vals = {
            "partner_id": self.student.partner_id.id,
            "product_id": self.pack.id,
            "payment_method": "cash",
            "amount_paid": 75.0,
        }
        vals.update(extra)
        return self.env["fitness.desk.sale.wizard"].with_user(
            self.manager).create(vals)

    def _order_from(self, action, partner=None):
        """The order the wizard just made, however it chose to end.

        A manager who can read sale.order is sent to it; one who cannot gets
        a notification instead, because landing them on an access error after
        a sale that went through perfectly is worse than not showing it. The
        test manager here is the second kind, which is the common one.
        """
        if action.get("res_model") == "sale.order":
            return self.env["sale.order"].browse(action["res_id"])
        self.assertEqual(action.get("tag"), "display_notification",
                         "the wizard ended in neither of its two ways")
        partner = partner or self.student.partner_id
        order = self.env["sale.order"].sudo().search(
            [("partner_id", "=", partner.id)], order="id desc", limit=1)
        self.assertTrue(order, "the wizard reported success but made no order")
        return order

    # -- the cash path -----------------------------------------------------

    def test_cash_sale_creates_a_confirmed_order_at_the_amount_taken(self):
        order = self._order_from(self._wizard().action_create_sale())

        self.assertEqual(order.partner_id, self.student.partner_id)
        self.assertEqual(
            order.state, "sale",
            "a desk sale has to be confirmed, or no credits exist at all")
        self.assertEqual(order.amount_total, 75.0)
        self.assertEqual(order.fitness_payment_method, "cash")

    def test_cash_sale_grants_the_credits_the_pack_promises(self):
        order = self._order_from(self._wizard().action_create_sale())
        line = order.order_line[:1]

        self.assertEqual(line.fitness_original_class_count, 5)
        self.assertEqual(
            line.fitness_remaining_classes, 5,
            "the whole point of a real order underneath is that credits "
            "arrive the ordinary way")

    def test_a_discount_is_recorded_at_what_was_actually_taken(self):
        """The order says what happened, not what the price list says."""
        order = self._order_from(
            self._wizard(amount_paid=60.0).action_create_sale())

        self.assertEqual(order.amount_total, 60.0)
        self.assertEqual(order.order_line[:1].fitness_original_class_count, 5,
                         "a discount changes the price, not the classes")

    def test_cash_with_no_amount_is_refused(self):
        """Otherwise a sale and a gift look identical on the record."""
        with self.assertRaises(UserError):
            self._wizard(amount_paid=0.0).action_create_sale()

    # -- the free path -----------------------------------------------------

    def test_free_credit_records_no_revenue(self):
        order = self._order_from(self._wizard(
            payment_method="free", reason="Her sister, opening week.",
        ).action_create_sale())

        self.assertEqual(
            order.amount_total, 0.0,
            "a gift must not show up as money the studio took")
        self.assertEqual(order.fitness_payment_method, "free")
        self.assertEqual(order.state, "sale")

    def test_free_credit_still_grants_real_credits(self):
        order = self._order_from(self._wizard(
            payment_method="free", reason="Compensation for a cancelled class.",
        ).action_create_sale())

        self.assertEqual(order.order_line[:1].fitness_remaining_classes, 5)

    def test_free_credit_demands_a_reason(self):
        """It is the only record anyone will have of why classes were given."""
        with self.assertRaises(UserError):
            self._wizard(payment_method="free", reason="").action_create_sale()

    def test_a_reason_of_spaces_is_not_a_reason(self):
        with self.assertRaises(UserError):
            self._wizard(payment_method="free", reason="   ").action_create_sale()

    # -- what makes both paths worth having --------------------------------

    def test_both_paths_leave_a_note_saying_who_and_why(self):
        order = self._order_from(self._wizard(
            payment_method="free", reason="Family.").action_create_sale())
        bodies = " ".join(order.message_ids.mapped("body"))

        self.assertIn("Desk Manager", bodies)
        self.assertIn("Family.", bodies)

    def test_the_credits_can_actually_be_spent(self):
        """A credit that cannot be booked against is not a credit."""
        order = self._order_from(self._wizard().action_create_sale())
        room = self.env["fitness.classroom"].create({
            "name": "Desk room", "classroom_type": "barre", "capacity": 6})
        ctype = self.env["fitness.class.type"].create({
            "name": "Desk Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group", "classroom_id": room.id})
        start = fields.Datetime.now() + timedelta(days=3)
        event = self.env["calendar.event"].create({
            "name": "Desk class", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": ctype.id, "is_fitness_class": True})

        booking = self.env["fitness.booking"].create({
            "student_id": self.student.partner_id.id,
            "calendar_event_id": event.id,
            "manager_override_timewindow": True,
        })
        order.order_line[:1].invalidate_recordset()

        self.assertEqual(booking.state, "booked")
        self.assertEqual(
            order.order_line[:1].fitness_remaining_classes, 4,
            "the booking has to draw on the desk sale like any other pack")

    def test_a_manager_without_sales_rights_is_not_dropped_on_an_error(self):
        """The sale goes through and then the redirect fails - the worst
        shape of bug, because the money is taken and the screen says error.
        Only the studio owner has Sales rights on the real database; anybody
        she adds to the desk will not."""
        self.assertFalse(
            self.manager.has_group("sales_team.group_sale_salesman"),
            "fixture is wrong: this manager can read sale.order, so this "
            "proves nothing")

        action = self._wizard().action_create_sale()

        self.assertEqual(action.get("tag"), "display_notification")
        self.assertNotEqual(
            action.get("res_model"), "sale.order",
            "sending them to a form they cannot open ends a good sale badly")

    # -- invoicing -------------------------------------------------------

    def test_a_cash_sale_produces_a_posted_invoice(self):
        """Every paying order on production is invoiced. A cash sale would
        otherwise have been the first paying customer without one."""
        order = self._order_from(self._wizard().action_create_sale())

        self.assertTrue(order.invoice_ids, "a cash sale must raise an invoice")
        inv = order.invoice_ids[:1]
        self.assertEqual(inv.move_type, "out_invoice")
        self.assertEqual(inv.state, "posted",
                         "a draft invoice is not sent and not counted")
        self.assertAlmostEqual(inv.amount_total, order.amount_total, places=2)

    def test_a_free_grant_raises_no_invoice(self):
        """It is a gift at zero, like the free trials - 78 of which carry no
        invoice and correctly so."""
        order = self._order_from(self._wizard(
            payment_method="free", reason="Her sister.").action_create_sale())

        self.assertFalse(
            order.invoice_ids,
            "invoicing a gift would put revenue in the books that nobody paid")

    def test_the_invoice_bills_what_was_taken(self):
        order = self._order_from(
            self._wizard(amount_paid=60.0).action_create_sale())

        self.assertAlmostEqual(
            order.invoice_ids[:1].amount_total, 60.0, places=2,
            msg="the invoice has to say what the student actually handed over")

    def test_the_sale_survives_a_failure_to_register_payment(self):
        """Without a cash journal the money cannot be booked, but the invoice
        must still stand - an unpaid invoice can be settled, a missing one
        has to be discovered first."""
        self.env["account.journal"].search([("type", "=", "cash")]).write(
            {"active": False})

        order = self._order_from(self._wizard().action_create_sale())

        self.assertEqual(order.state, "sale")
        self.assertTrue(order.invoice_ids)
        self.assertEqual(order.invoice_ids[:1].state, "posted")

    def test_only_a_manager_can_sell_from_the_desk(self):
        """Blocked by the access rule before the method's own guard is even
        reached - a student cannot so much as open the wizard."""
        with self.assertRaises(AccessError):
            self.env["fitness.desk.sale.wizard"].with_user(
                self.student).create({
                    "partner_id": self.student.partner_id.id,
                    "product_id": self.pack.id,
                    "payment_method": "cash",
                    "amount_paid": 75.0,
                })

    def test_the_order_totals_what_was_actually_taken(self):
        """Prices here are quoted tax-included, but the customer tax is
        configured tax-exclusive. Writing the figure straight onto the line
        added tax a second time and a 75.00 sale became an 86.25 order, so
        the books would not have matched the till."""
        tax = self.env["account.tax"].create({
            "name": "Desk IVA 21", "amount": 21.0, "amount_type": "percent",
            "type_tax_use": "sale", "price_include": False,
        })
        self.pack.taxes_id = [(6, 0, tax.ids)]

        order = self._order_from(self._wizard(amount_paid=75.0).action_create_sale())

        self.assertAlmostEqual(
            order.amount_total, 75.0, places=2,
            msg="the order total has to equal the cash that was taken")
        self.assertLess(
            order.order_line[:1].price_unit, 75.0,
            "under a tax-exclusive product the line carries the base")

    def test_the_total_is_right_under_a_price_included_tax_too(self):
        """The other tax configuration, which real data turned out to use.

        Reversing the tax on a price that already contains it is just as
        wrong in the other direction: 95.00 taken produced a 78.51 order
        until the price_unit was asked for rather than assumed.
        """
        tax = self.env["account.tax"].create({
            "name": "Desk IVA 21 incl", "amount": 21.0,
            "amount_type": "percent", "type_tax_use": "sale",
            "price_include": True,
        })
        self.pack.taxes_id = [(6, 0, tax.ids)]

        order = self._order_from(self._wizard(amount_paid=95.0).action_create_sale())

        self.assertAlmostEqual(
            order.amount_total, 95.0, places=2,
            msg="the order total has to equal the cash taken whichever way "
                "the product's tax is configured")

    def test_a_combined_pack_grants_both_pools(self):
        """One price, two pools - the reason line building is shared with
        checkout rather than written a second time here."""
        combo = self.env["product.template"].create({
            "name": "Desk combo", "list_price": 120.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 4,
            "fitness_validity_days": 60,
            "fitness_class_type": "barre",
            "fitness_secondary_class_type": "reformer",
            "fitness_session_type": "group",
        })
        order = self._order_from(self._wizard(
            product_id=combo.id, amount_paid=120.0).action_create_sale())

        self.assertEqual(len(order.order_line), 2,
                         "a combined pack is two pools, so two lines")
        self.assertEqual(order.amount_total, 120.0,
                         "the second pool must not be charged for again")
        self.assertEqual(
            set(order.order_line.mapped("fitness_class_type")),
            {"barre", "reformer"})
