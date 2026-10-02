# -*- coding: utf-8 -*-
"""A class changing instructor reaches the student both ways, by both routes.

WHAT WENT WRONG
---------------
Production ran nine instructor swaps and sent zero emails. Not one
mail.mail row, not one mail.message, across four swaps where students
were booked and had addresses - while every one of those students got
the in-app notification normally.

Two separate causes, one per route:

  * the teacher-portal route called template.send_mail() without
    sudo(). That route runs as the instructor, who cannot write
    mail.mail, so it raised AccessError - and a bare `except Exception`
    swallowed it. The bell beside it worked because the notification
    model WAS sudoed;
  * the back-office route sent no email at all. It created the
    notifications and the swap record and stopped.

The reschedule path, three hundred lines away in the same file, had
done template.sudo().send_mail() correctly all along, which is how the
difference stayed invisible.

WHAT THESE PIN
--------------
Both routes, both channels, and the sender. They assert on mail.mail
rows that actually exist afterwards - not that a code path was
reached, because the path WAS reached every time and still sent
nothing.

The student with no address is here as a supported state, not an edge
case: she must still get the bell, and nothing may raise.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
STUDENT_GROUP = 'fitness_core.group_fitness_student'
MANAGER_GROUP = 'fitness_core.group_fitness_manager'


@tagged("post_install", "-at_install")
class TestSwapEmailsTheStudent(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        # Pinned so the sender assertion has something definite to compare
        # against: the point of the test is that the mail comes from the
        # studio, not from whichever instructor happened to press the button.
        cls.env.company.sudo().write({'email': 'info@corelabstudio.es'})

        portal = cls.env.ref("base.group_portal").id
        teacher = cls.env.ref(TEACHER_GROUP).id
        student = cls.env.ref(STUDENT_GROUP).id

        cls.teacher_a = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Mail Swap A", "login": "mailswap.a@example.invalid",
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.teacher_b = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Mail Swap B", "login": "mailswap.b@example.invalid",
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Mail Swap Manager",
                "login": "mailswap.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref(MANAGER_GROUP).id])]})

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Mail Swap Room", "classroom_type": "barre",
            "capacity": 8})
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Mail Swap Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id})
        cls.pack = cls.env["product.template"].sudo().create({
            "name": "Mail Swap Credit", "type": "service", "list_price": 0.0,
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 10, "fitness_validity_days": 180,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        cls.student_group_id = student
        cls.portal_group_id = portal

    # ── fixtures ────────────────────────────────────────────────────────

    def _student(self, tag, email='mailswap.%s@example.invalid'):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Mail Swap Student %s" % tag,
                "login": "mailswap.student.%s" % tag,
                "email": (email % tag) if email and '%s' in email else email,
                "group_ids": [(6, 0, [self.portal_group_id,
                                      self.student_group_id])]})
        return user.partner_id

    def _credit_line(self, partner):
        """A free credit, so the booking has something to charge against.

        Left unset, fitness.booking.create() goes looking for a source of
        its own and refuses when it finds none.
        """
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 0.0})]})
        order.action_confirm()
        return order.order_line[:1]

    def _class(self, tag, teacher=None, days=4):
        who = teacher or self.teacher_a
        start = (fields.Datetime.now() + timedelta(days=days)).replace(
            hour=18, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": "Mail swap %s" % tag,
            "start": start, "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id, "is_fitness_class": True,
            "capacity": 8, "user_id": who.id})

    def _book(self, partner, event):
        return self.env["fitness.booking"].sudo().create({
            "student_id": partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": self._credit_line(partner).id})

    def _mails_for(self, booking, since_id=0):
        """Mail actually created for this booking, by the swap template."""
        return self.env["mail.mail"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("res_id", "=", booking.id),
            ("id", ">", since_id)])

    def _bells_for(self, user, since_id=0):
        return self.env["fitness.notification"].sudo().search([
            ("user_id", "=", user.id),
            ("notification_type", "=", "teacher_swap"),
            ("id", ">", since_id)])

    def _mark(self, model):
        last = self.env[model].sudo().search([], order="id desc", limit=1)
        return last.id if last else 0

    # ── 1. the teacher-portal route ─────────────────────────────────────

    def test_the_teacher_route_emails_the_student(self):
        partner = self._student("troute")
        event = self._class("troute")
        booking = self._book(partner, event)
        mark = self._mark("mail.mail")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id, reason="Dentist")

        mails = self._mails_for(booking, mark)
        self.assertTrue(
            mails,
            "the handover sent her nothing. This is the fault exactly: the "
            "send ran as the instructor, who cannot write mail.mail, and "
            "the AccessError was swallowed while the bell went out")
        self.assertEqual(
            len(mails), 1, "she was emailed %d times for one swap" % len(mails))

    def test_the_teacher_route_still_bells_the_student(self):
        partner = self._student("tbell")
        event = self._class("tbell")
        self._book(partner, event)
        mark = self._mark("fitness.notification")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id)

        self.assertTrue(
            self._bells_for(partner.user_ids[:1], mark),
            "the in-app notification stopped working while the email was "
            "being fixed")

    def test_the_teacher_route_tells_the_incoming_instructor(self):
        event = self._class("tteach")
        mark = self._mark("fitness.notification")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id)

        self.assertTrue(
            self._bells_for(self.teacher_b, mark),
            "the person who now has to teach the class was not told")

    # ── 2. the back-office route ────────────────────────────────────────

    def test_the_admin_route_emails_the_student(self):
        """This route sent no email at all until now."""
        partner = self._student("aroute")
        event = self._class("aroute")
        booking = self._book(partner, event)
        mark = self._mark("mail.mail")

        event.with_user(self.manager).write({"user_id": self.teacher_b.id})

        mails = self._mails_for(booking, mark)
        self.assertTrue(
            mails,
            "editing the Organizer told her on the bell and never in her "
            "inbox - the two routes have to do the same thing")
        self.assertEqual(
            len(mails), 1, "she was emailed %d times for one swap" % len(mails))

    def test_the_admin_route_bells_the_student_and_the_instructor(self):
        partner = self._student("abell")
        event = self._class("abell")
        self._book(partner, event)
        mark = self._mark("fitness.notification")

        event.with_user(self.manager).write({"user_id": self.teacher_b.id})

        self.assertTrue(
            self._bells_for(partner.user_ids[:1], mark),
            "the student was not told")
        self.assertTrue(
            self._bells_for(self.teacher_b, mark),
            "the incoming instructor was not told")

    # ── 3. the sender ───────────────────────────────────────────────────

    def test_the_mail_comes_from_the_studio_not_the_teacher(self):
        """It is studio correspondence, whoever pressed the button.

        The template reads user.company_id.email_formatted - "user" being
        whoever triggered the send - so a swap made by an instructor must
        still arrive from the studio address.
        """
        partner = self._student("sender")
        event = self._class("sender")
        booking = self._book(partner, event)
        mark = self._mark("mail.mail")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id)

        mail = self._mails_for(booking, mark)[:1]
        self.assertTrue(mail, "nothing was sent, so there is no sender to check")
        self.assertEqual(
            mail.email_from, self.env.company.email_formatted,
            "the student's mail says it is from %r rather than from the "
            "studio" % mail.email_from)
        self.assertNotIn(
            self.teacher_a.login, mail.email_from or '',
            "the mail is addressed as coming from the instructor who made "
            "the swap")

    # ── 4. the student with no address ──────────────────────────────────

    def test_a_student_with_no_email_gets_the_bell_and_no_mail(self):
        """A supported state, not an edge case.

        She must still be told in the app, and nothing may raise - the
        handover is the important part and must not fail over a missing
        address.
        """
        partner = self._student("noaddr")
        partner.sudo().write({"email": False})
        event = self._class("noaddr")
        booking = self._book(partner, event)
        mark_m = self._mark("mail.mail")
        mark_n = self._mark("fitness.notification")

        try:
            event.with_user(self.teacher_a).fitness_reassign_teacher(
                self.teacher_b.id)
        except Exception as exc:                                # noqa: BLE001
            self.fail("a student with no email address broke the handover: "
                      "%s: %s" % (type(exc).__name__, exc))

        self.assertFalse(
            self._mails_for(booking, mark_m),
            "mail was queued to a student with no address")
        self.assertTrue(
            self._bells_for(partner.user_ids[:1], mark_n),
            "she has no address, so the bell is the ONLY way she learns the "
            "class changed hands - and there is none")

    # ── 5. one swap, one of each ────────────────────────────────────────

    def test_one_swap_sends_one_email_and_one_bell_not_two(self):
        """The portal route writes under skip_fitness_notification.

        Without that, its own notifications and the write() hook's would
        both fire and the student would be told twice about one change.
        Now that both routes share an implementation, a regression here is
        easy to introduce and silent to the person writing it.
        """
        partner = self._student("once")
        event = self._class("once")
        booking = self._book(partner, event)
        mark_m = self._mark("mail.mail")
        mark_n = self._mark("fitness.notification")

        event.with_user(self.teacher_a).fitness_reassign_teacher(
            self.teacher_b.id)

        mails = self._mails_for(booking, mark_m)
        bells = self._bells_for(partner.user_ids[:1], mark_n)
        tbells = self._bells_for(self.teacher_b, mark_n)
        self.assertEqual(len(mails), 1,
                         "one swap produced %d emails" % len(mails))
        self.assertEqual(len(bells), 1,
                         "one swap produced %d bells for the student"
                         % len(bells))
        self.assertEqual(len(tbells), 1,
                         "one swap produced %d bells for the instructor"
                         % len(tbells))

    # ── 6. the negative: nothing to tell ────────────────────────────────

    def test_assigning_the_same_instructor_again_tells_nobody(self):
        """A write that does not change the teacher is not a swap."""
        partner = self._student("same")
        event = self._class("same")
        booking = self._book(partner, event)
        mark_m = self._mark("mail.mail")
        mark_n = self._mark("fitness.notification")

        event.with_user(self.manager).write({"user_id": self.teacher_a.id})

        self.assertFalse(
            self._mails_for(booking, mark_m),
            "re-saving the same instructor emailed the student")
        self.assertFalse(
            self._bells_for(partner.user_ids[:1], mark_n),
            "re-saving the same instructor belled the student")
