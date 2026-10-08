# -*- coding: utf-8 -*-
"""The studio is told when somebody asks for a trial class.

create() has always had two branches. A request that arrives with a slot
already chosen is booked outright, and that branch emails the student and
emails the studio. A request that arrives without one is the branch where
the studio has to do something - find a slot, and place her in it - and it
emailed the student only. Nobody was told there was anything to do.

It was invisible because the student's own acknowledgement did send, so
every check of "is mail working" came back yes, and the request sat in a
list until somebody happened to open it.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStudioHearsAboutARequest(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The admin notification is addressed to the company's own address
        # and is skipped outright when there is none, so the fixture states
        # it rather than inheriting whatever the deploy left behind.
        cls.env.company.email = "studio.inbox@example.invalid"
        cls.Mail = cls.env["mail.mail"].sudo()
        cls.Request = cls.env["fitness.trial.request"].sudo()
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Studio Notice Barre",
            "classroom_type": "barre",
            "duration": 50,
            "level": "all",
            "session_type": "group",
        })

    def _mail_since(self, marker):
        return self.Mail.search([("id", ">", marker)])

    def _marker(self):
        return self.Mail.search([], order="id desc", limit=1).id or 0

    def _to_the_studio(self, mails):
        return mails.filtered(
            lambda m: self.env.company.email in (m.email_to or ""))

    def _ask(self, **extra):
        vals = {
            "name": "Trial Asker",
            "email": "trial.asker@example.invalid",
            "class_interest": "barre",
        }
        vals.update(extra)
        return self.Request.create(vals)

    # == the branch that was silent ==================================
    def test_a_pending_request_emails_the_studio(self):
        marker = self._marker()
        rec = self._ask()
        self.env.flush_all()

        self.assertEqual(
            rec.status, "pending",
            "fixture is wrong: this request was booked outright, so it is "
            "not exercising the branch that was silent")
        mails = self._mail_since(marker)
        to_studio = self._to_the_studio(mails)
        self.assertTrue(
            to_studio,
            "a trial request arrived and the studio was sent nothing, so it "
            "waits in a list until somebody opens it by chance. Mail to the "
            "student: %s" % mails.mapped("email_to"))

    def test_the_student_is_still_told_we_have_her_request(self):
        """The half that already worked, kept honest."""
        marker = self._marker()
        self._ask()
        self.env.flush_all()
        to_student = self._mail_since(marker).filtered(
            lambda m: "trial.asker@example.invalid" in (m.email_to or ""))
        self.assertTrue(
            to_student,
            "the student's acknowledgement stopped being sent")

    def test_the_subject_does_not_call_a_request_a_booking(self):
        """What the studio reads in a list decides whether it gets answered."""
        marker = self._marker()
        self._ask()
        self.env.flush_all()
        subject = self._to_the_studio(self._mail_since(marker))[:1].subject or ""
        self.assertNotIn(
            "booked", subject.lower(),
            "the studio is told a trial was booked when nothing has been "
            "booked and it is the studio that has to book it: %r" % subject)
        self.assertIn(
            "Trial Asker", subject,
            "the subject does not name who asked: %r" % subject)

    def test_the_studio_is_told_which_day_she_asked_for(self):
        """Without a slot, her preference is the only thing to act on."""
        marker = self._marker()
        day = fields.Date.today()
        self._ask(preferred_date=day, preferred_period="morning")
        self.env.flush_all()
        body = self._to_the_studio(self._mail_since(marker))[:1].body_html or ""
        self.assertIn(
            str(day), body,
            "the day she asked for is not in the email, so the studio has "
            "to open the record to learn anything useful")
        self.assertIn(
            "Morning", body,
            "morning or evening is not in the email")

    # == the branch that already worked ==============================
    def test_a_booked_request_still_tells_the_studio(self):
        start = fields.Datetime.now() + timedelta(days=3)
        slot = self.env["calendar.event"].sudo().create({
            "name": "Studio Notice class",
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
        })
        marker = self._marker()
        self._ask(status="scheduled", occurrence_id=slot.id)
        self.env.flush_all()
        self.assertTrue(
            self._to_the_studio(self._mail_since(marker)),
            "the branch that always notified the studio has stopped")

    def test_no_company_address_is_logged_and_not_fatal(self):
        """The notification is skipped, and asking must still succeed."""
        self.env.company.email = False
        rec = self._ask()
        self.env.flush_all()
        self.assertTrue(
            rec.exists(),
            "a studio with no address on file can no longer take a trial "
            "request at all")
