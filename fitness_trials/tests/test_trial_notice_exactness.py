# -*- coding: utf-8 -*-
"""How many emails a trial request sends, to whom, and what they contain.

"The studio is told" is not enough on its own. Told twice is a studio that
stops reading them, and the notice is added to the same branch that already
sends the student her acknowledgement - so the count on both sides is what
says the two did not become entangled.

The second half is about what must survive: a studio inbox that is not
configured, a mail server that is down, a neutralised restore. The student
pressing Send is the one part of this nobody else can retry for her.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.tests import TransactionCase, tagged

TRIAL_LOGGER = "odoo.addons.fitness_trials.models.trial_request"


@tagged("post_install", "-at_install")
class TestExactlyWhatIsSent(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.email = "studio.inbox@example.invalid"
        cls.Mail = cls.env["mail.mail"].sudo()
        cls.Request = cls.env["fitness.trial.request"].sudo()
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Exactly Barre",
            "classroom_type": "barre",
            "duration": 50,
            "level": "all",
            "session_type": "group",
        })

    # -- helpers -----------------------------------------------------
    def _marker(self):
        return self.Mail.search([], order="id desc", limit=1).id or 0

    def _since(self, marker):
        self.env.flush_all()
        return self.Mail.search([("id", ">", marker)])

    def _studio(self, mails):
        return mails.filtered(
            lambda m: self.env.company.email in (m.email_to or ""))

    def _student(self, mails, address):
        return mails.filtered(lambda m: address in (m.email_to or ""))

    def _ask(self, address="exact.asker@example.invalid", **extra):
        vals = {"name": "Exact Asker", "email": address,
                "class_interest": "barre"}
        vals.update(extra)
        return self.Request.create(vals)

    # == counts ======================================================
    def test_a_pending_request_sends_exactly_one_each(self):
        marker = self._marker()
        self._ask()
        mails = self._since(marker)
        studio = self._studio(mails)
        student = self._student(mails, "exact.asker@example.invalid")
        self.assertEqual(
            len(studio), 1,
            "the studio got %d emails for one request, not 1: %s"
            % (len(studio), studio.mapped("subject")))
        self.assertEqual(
            len(student), 1,
            "the student got %d acknowledgements for one request, not 1"
            % len(student))
        self.assertEqual(
            len(mails), 2,
            "one request produced %d emails in total: %s"
            % (len(mails), mails.mapped("email_to")))

    def test_two_requests_from_two_people_do_not_cross(self):
        marker = self._marker()
        self._ask("first.asker@example.invalid")
        self._ask("second.asker@example.invalid")
        mails = self._since(marker)
        self.assertEqual(
            len(self._studio(mails)), 2,
            "two requests did not produce two notices to the studio")
        self.assertEqual(
            len(self._student(mails, "first.asker@example.invalid")), 1)
        self.assertEqual(
            len(self._student(mails, "second.asker@example.invalid")), 1)

    def test_a_scheduled_request_sends_exactly_what_it_did_before(self):
        """The branch that already worked: one student, one studio."""
        start = fields.Datetime.now() + timedelta(days=4)
        slot = self.env["calendar.event"].sudo().create({
            "name": "Exactly class",
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
        })
        marker = self._marker()
        self._ask("sched.asker@example.invalid",
                  status="scheduled", occurrence_id=slot.id)
        mails = self._since(marker)
        self.assertEqual(
            len(self._studio(mails)), 1,
            "the booked branch now notifies the studio %d times"
            % len(self._studio(mails)))
        self.assertEqual(
            len(self._student(mails, "sched.asker@example.invalid")), 1,
            "the booked branch's confirmation to the student changed")

    def test_asking_again_after_a_decline_notifies_the_studio_again(self):
        """A second request is a second thing to do, not a duplicate."""
        first = self._ask("again.asker@example.invalid")
        self.env["fitness.trial.decline.wizard"].create({
            "request_id": first.id, "reason": "No space that week.",
        }).action_confirm()

        marker = self._marker()
        self._ask("again.asker@example.invalid")
        self.assertEqual(
            len(self._studio(self._since(marker))), 1,
            "asking again after a decline does not reach the studio")

    def test_editing_a_request_does_not_notify_again(self):
        """Only creating a request is news. A write is not."""
        rec = self._ask("edited.asker@example.invalid")
        marker = self._marker()
        rec.write({"preferred_time_notes": "Actually any morning is fine."})
        self.assertFalse(
            self._studio(self._since(marker)),
            "editing a request emails the studio all over again")

    # == content =====================================================
    def _studio_body(self, **extra):
        marker = self._marker()
        self._ask(**extra)
        mail = self._studio(self._since(marker))[:1]
        self.assertTrue(mail, "no notice reached the studio")
        return mail.subject or "", mail.body_html or ""

    def test_the_preferred_date_is_the_day_she_asked_for(self):
        """A Date must not be shifted by anybody's timezone on the way out.

        preferred_date carries no time, so rendering it through anything
        that localises a datetime would move it a day for a reader east or
        west of Madrid - and the studio would then offer her the wrong day.
        """
        day = fields.Date.to_date("2026-11-12")
        for tz in ("Europe/Madrid", "Asia/Calcutta", "America/Lima"):
            self.env.user.tz = tz
            _subject, body = self._studio_body(
                address="tz.%s@example.invalid" % tz.split("/")[1].lower(),
                preferred_date=day, preferred_period="morning")
            self.assertIn(
                "2026-11-12", body,
                "the studio is shown a different day from the one she asked "
                "for when the reader is in %s" % tz)

    def test_the_period_is_a_word_not_a_database_value(self):
        _subject, body = self._studio_body(
            address="period.asker@example.invalid",
            preferred_date=fields.Date.today(), preferred_period="evening")
        self.assertIn(
            "Evening", body,
            "the studio is shown the stored value rather than the label")

    def test_a_blank_date_and_period_still_read_correctly(self):
        """She may send the form with neither filled in."""
        subject, body = self._studio_body(
            address="blank.asker@example.invalid")
        self.assertIn(
            "Exact Asker", body + subject,
            "her name is missing from a request with no date")
        self.assertNotIn(
            "False", body,
            "an empty date is printed as False in the studio's email")
        self.assertNotIn("None", body)

    def test_a_long_message_does_not_break_the_email(self):
        note = ("I can usually only come after I drop the children at "
                "school, so anything from half past nine onwards works, "
                "except Wednesdays when I work from the office in Sabadell "
                "and cannot get back in time. ") * 4
        _subject, body = self._studio_body(
            address="long.asker@example.invalid",
            preferred_date=fields.Date.today(), preferred_time_notes=note)
        self.assertIn(
            "Sabadell", body,
            "a long message is not carried to the studio at all")
        self.assertNotIn(
            "<script", body.lower(),
            "the message is not being escaped into the email")

    def test_the_subject_names_the_discipline(self):
        subject, _body = self._studio_body(
            address="disc.asker@example.invalid")
        self.assertIn(
            "Barre", subject,
            "the studio cannot tell which room is being asked for: %r"
            % subject)


@tagged("post_install", "-at_install")
class TestTheNoticeNeverCostsTheRequest(TransactionCase):
    """Asking for a trial must survive anything the notification does.

    None of these may turn her request into an error page, and none of them
    may raise an ERROR line, because the odoo.sh build is graded on those.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["fitness.trial.request"].sudo()
        cls.Mail = cls.env["mail.mail"].sudo()

    def _ask(self, address="resilient@example.invalid"):
        return self.Request.create({
            "name": "Resilient Asker", "email": address,
            "class_interest": "barre"})

    def test_a_studio_with_no_address_still_takes_the_request(self):
        self.env.company.email = False
        with self.assertLogs(TRIAL_LOGGER, level="WARNING") as captured:
            rec = self._ask("noaddress@example.invalid")
        self.assertTrue(rec.exists(), "the request was lost")
        joined = "\n".join(captured.output)
        self.assertIn("skipping admin notification", joined)
        self.assertNotIn(
            "ERROR:", joined,
            "a studio with no address on file raises an ERROR line, which "
            "fails the build on odoo.sh")

    def test_a_failing_send_warns_and_keeps_the_request(self):
        """A dead mail server is a WARNING, never an ERROR, never a loss.

        Three things at once, because they fail independently:

          - the request survives. She pressed Send; nobody else can retry
            that for her.
          - it is logged, with the traceback, so the studio can be told
            that somebody asked and the email did not go.
          - it is logged at WARNING. _logger.exception emits at ERROR,
            and odoo.sh grades a build on ERROR-level lines - so an SMTP
            outage during a deploy would turn the build red. This test
            was written because the two handlers behind it did exactly
            that, and the gate caught it.
        """
        self.env.company.email = "studio.inbox@example.invalid"

        def boom(*_a, **_kw):
            raise RuntimeError("smtp is down")

        with patch.object(MailTemplate, "send_mail", boom):
            with self.assertLogs(TRIAL_LOGGER, level="WARNING") as captured:
                rec = self._ask("sendfails@example.invalid")

        self.assertTrue(
            rec.exists(),
            "a mail failure rolled back the student's trial request")

        levels = [r.levelname for r in captured.records]
        self.assertIn(
            "WARNING", levels,
            "a failing send was not logged at all, so a lost email is "
            "invisible: %s" % levels)
        self.assertNotIn(
            "ERROR", levels,
            "a failing send logs at ERROR level. odoo.sh counts those and "
            "fails the build, so a studio whose SMTP blipped would turn a "
            "deploy red: %s" % levels)
        self.assertNotIn("CRITICAL", levels)

        # The traceback has to survive the change from exception() to
        # warning(), or the log says a send failed and not why.
        self.assertTrue(
            any(r.exc_info for r in captured.records),
            "the traceback was dropped, so the log cannot say why the "
            "email failed")
        self.assertTrue(
            any("pending email failed" in r.getMessage()
                or "admin notification failed" in r.getMessage()
                for r in captured.records),
            "neither mail handler reported anything: %s"
            % [r.getMessage() for r in captured.records])

    def test_a_neutralised_database_sends_nothing_real(self):
        """A restore must not email the studio about last month's requests."""
        self.env["ir.config_parameter"].sudo().set_param(
            "database.is_neutralized", "True")
        self.assertTrue(
            self.env["ir.config_parameter"].sudo().get_param(
                "database.is_neutralized"),
            "the neutralisation flag did not take, so this proves nothing")
        marker = self.Mail.search([], order="id desc", limit=1).id or 0
        rec = self._ask("neutralised@example.invalid")
        self.env.flush_all()
        self.assertTrue(rec.exists())
        for mail in self.Mail.search([("id", ">", marker)]):
            self.assertNotEqual(
                mail.state, "sent",
                "a neutralised database actually sent mail to %s"
                % mail.email_to)
