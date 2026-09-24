# -*- coding: utf-8 -*-
"""A student with no email address at all, and nothing breaking because of it.

Some students have no email. Not a wrong one, not a placeholder - none. The
studio has been giving those contacts a fake address so the forms would
accept them, and one of those fakes was a live Gmail account belonging to a
stranger, who duly received a real customer's invoice.

A blank field is the honest state, so the system has to survive it. Two
shapes:

  Case 1 - no digital contact at all. No email, no portal login. The studio
    books her, sells to her and hands her a printed invoice. Nothing should
    ever try to email her.

  Case 2 - she uses the app but has no email. In-app notifications must
    reach her exactly as they reach anyone else, while every email path
    quietly skips her.

What is asserted throughout is that email is *skipped*, not that it fails
politely. A queued mail.mail with no recipient is not a skip - it is a
failure that shows up in the outgoing-mail queue and eventually in somebody's
support inbox.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class BlankEmailFixture:

    @classmethod
    def _build(cls):
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Blank Email Manager",
                "login": "blank.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })

        cls.pack = cls.env["product.template"].create({
            "name": "Blank Email Pack 10", "list_price": 120.0,
            "type": "service", "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

        # This database has no cash journal, and without one the settlement
        # step logs a warning and leaves the invoice unpaid. That would make
        # the assertions below pass or fail for a reason that has nothing to
        # do with email addresses.
        company = cls.env.company
        cls.cash_journal = cls.env["account.journal"].search(
            [("type", "=", "cash"), ("company_id", "=", company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env["account.journal"].create({
                "name": "Blank Email Cash", "type": "cash",
                "code": "BECSH", "company_id": company.id,
            })

    def _mail_count(self):
        return self.env["mail.mail"].sudo().search_count([])

    def _order_for(self, partner):
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "fitness_payment_method": "cash",
        })
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 120.0,
        })
        order.action_confirm()
        return order


@tagged("post_install", "-at_install")
class TestCase1NoDigitalContactAtAll(BlankEmailFixture, TransactionCase):
    """Nuria's shape: on the books, off the network."""

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()
        cls.partner = cls.env["res.partner"].create({
            "name": "Blank Email Walk In",
            "email": False,
            "phone": "600000001",
        })

    def test_she_can_exist_with_no_email(self):
        self.assertFalse(self.partner.email, "a blank email did not stay blank")
        self.assertFalse(self.partner.user_ids, "she should have no login")

    def test_a_cash_sale_to_her_invoices_and_settles_without_emailing(self):
        """The money side has to work in full. Only the mail is skipped."""
        before = self._mail_count()
        order = self._order_for(self.partner)
        invoice = order.fitness_invoice_cash_sale()

        self.assertTrue(invoice, "no invoice was raised for a cash sale")
        self.assertEqual(invoice.state, "posted", "the invoice was not posted")
        self.assertAlmostEqual(
            invoice.amount_residual, 0.0, places=2,
            msg="the cash was never settled against the invoice")
        self.assertEqual(
            self._mail_count(), before,
            "an email was queued for a student with no address - it can only "
            "sit in the outgoing queue and fail")

    def test_emailing_the_invoice_is_a_no_op_not_an_error(self):
        order = self._order_for(self.partner)
        invoice = order.fitness_invoice_cash_sale()
        before = self._mail_count()
        try:
            order.fitness_email_invoice(invoice)
        except Exception as exc:                      # pragma: no cover
            self.fail("emailing a blank-address invoice raised %r" % exc)
        self.assertEqual(self._mail_count(), before,
                         "a second send attempt queued something")

    def test_the_invoice_is_not_marked_sent_when_it_was_not_sent(self):
        """If she gives us an address next month, this invoice must still be
        sendable. Marking it sent when nothing went out closes that door
        quietly."""
        order = self._order_for(self.partner)
        invoice = order.fitness_invoice_cash_sale()
        self.assertFalse(
            invoice.is_move_sent,
            "the invoice is flagged as sent although she has no address")

    def test_she_can_be_booked_into_a_class(self):
        """Being unreachable by email must not make her unbookable."""
        # She has to be able to pay for it first - booking checks for a
        # package or subscription covering the class type, and the pack sold
        # above is what grants it.
        self._order_for(self.partner)
        class_type = self.env["fitness.class.type"].create({
            "name": "Blank Email Class", "classroom_type": "barre",
            "duration": 50, "level": "all", "session_type": "group",
        })
        start = fields.Datetime.now() + timedelta(days=3)
        event = self.env["calendar.event"].create({
            "name": "Blank Email Barre",
            "start": start, "stop": start + timedelta(minutes=50),
            "class_type_id": class_type.id, "is_fitness_class": True,
        })
        before = self._mail_count()
        booking = self.env["fitness.booking"].sudo().create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
        })
        self.assertEqual(booking.state, "booked", "she was not booked")
        self.assertEqual(
            self._mail_count(), before,
            "booking her queued a confirmation email to nobody")


@tagged("post_install", "-at_install")
class TestCase2AppAccessButNoEmail(BlankEmailFixture, TransactionCase):
    """Eli's shape: she uses the app, and the app is how we reach her.

    The login is a username, not an address. That is the whole point - a
    login that looks like an email is one a stranger can aim a password
    reset at.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Blank Email App Student",
                "login": "blank.email.student",       # deliberately not an address
                "email": False,
                "password": "blank-email-pw-1",
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.user.partner_id

    def test_a_username_login_works_with_no_address(self):
        self.assertFalse(self.partner.email, "her email did not stay blank")
        self.assertEqual(self.user.login, "blank.email.student")
        self.assertNotIn("@", self.user.login,
                         "an address-shaped login is resettable by whoever "
                         "owns that inbox")

    def test_in_app_notifications_still_reach_her(self):
        """The half that must keep working."""
        self.env["fitness.notification"].sudo()._create_for_user(
            self.user.id, "purchase_completed", "Your pack is ready")
        found = self.env["fitness.notification"].sudo().search(
            [("user_id", "=", self.user.id)])
        self.assertTrue(found, "she received no in-app notification")
        self.assertEqual(found[:1].title, "Your pack is ready")

    def test_a_purchase_notifies_her_in_app_and_emails_nobody(self):
        before_mail = self._mail_count()
        order = self._order_for(self.partner)
        invoice = order.fitness_invoice_cash_sale()

        self.assertEqual(invoice.state, "posted")
        self.assertEqual(
            self._mail_count(), before_mail,
            "her purchase queued an email she has no address to receive")
        self.assertTrue(
            self.env["fitness.notification"].sudo().search(
                [("user_id", "=", self.user.id)]),
            "she was told nothing at all - in-app is the only channel she "
            "has, so it has to fire")

    def test_a_password_reset_cannot_be_used_against_her(self):
        """No address means no reset mail, which closes the door rather than
        opening a quiet one."""
        with self.assertRaises(UserError):
            self.user.sudo().action_reset_password()


@tagged("post_install", "-at_install")
class TestBlankEmailIsNotSpecialCased(BlankEmailFixture, TransactionCase):
    """A student who does have an address must still get her mail.

    Without this, every assertion above is satisfied by a system that has
    simply stopped sending email to anyone.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Reachable Student",
                "login": "reachable@example.invalid",
                "email": "reachable@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.user.partner_id.write({"email": "reachable@example.invalid"})
        cls.partner = cls.user.partner_id

    def test_a_student_with_an_address_is_still_emailed_her_invoice(self):
        before = self._mail_count()
        order = self._order_for(self.partner)
        order.fitness_invoice_cash_sale()
        self.assertGreater(
            self._mail_count(), before,
            "nobody is being emailed any more - the blank-email handling has "
            "turned into a blanket off switch")
