# -*- coding: utf-8 -*-
"""Sending a survey to a chosen group, and one answer each.

The two things worth pinning are the audience and the no-duplicate
guarantee. Everything else - the questions, the answering, the results - is
Odoo's and already tested by Odoo.

The duplicate guarantee is the subtle one, and the reason it needs a test
rather than a setting is this, from survey/models/survey_survey.py:

    if (self.access_mode != 'public' or self.users_login_required) \\
            and self.is_attempts_limited:
        return self._get_number_of_attempts_lefts(...) > 0
    return True

On a public survey the attempt limit is ignored completely. Ticking
"Limited number of attempts" in the Surveys app does nothing, silently, and
the symptom is a student answering twice. So the campaign pins the settings
at send time, and these tests check it actually did.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFitnessCampaign(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Campaign Manager",
                "login": "campaign.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        # A deliberately plain survey: public and unlimited, which is what
        # Odoo defaults to and exactly the shape that silently allows a
        # second answer.
        cls.survey = cls.env["survey.survey"].create({
            "title": "How was your class?",
            "access_mode": "public",
            "is_attempts_limited": False,
        })
        cls.env["survey.question"].create({
            "survey_id": cls.survey.id,
            "title": "Did you enjoy it?",
            "question_type": "char_box",
            "sequence": 1,
        })

    def _student(self, suffix, email=True):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Campaign %s" % suffix,
                "login": "campaign.%s@example.invalid" % suffix,
                "email": ("campaign.%s@example.invalid" % suffix) if email
                         else False,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        user.partner_id.write({
            "email": user.login if email else False})
        return user

    def _campaign(self, **vals):
        base = {"name": "Probe campaign", "survey_id": self.survey.id}
        base.update(vals)
        return self.env["fitness.campaign"].with_user(self.manager).create(base)

    # ── audience ────────────────────────────────────────────────────────────

    def test_everyone_means_students_not_every_contact(self):
        student = self._student("everyone")
        plain = self.env["res.partner"].create({"name": "Not A Student"})
        camp = self._campaign(audience="everyone")
        self.assertIn(student.partner_id, camp.recipient_ids)
        self.assertNotIn(
            plain, camp.recipient_ids,
            "a contact who is not a student was going to be surveyed")

    def test_attended_recently_respects_the_window(self):
        recent = self._student("recent")
        old = self._student("old")
        class_type = self.env["fitness.class.type"].create({
            "name": "Campaign Class", "classroom_type": "barre",
            "duration": 50, "level": "all", "session_type": "group",
        })

        # She has to be able to pay for the class before she can be booked
        # into it - booking asks for a package or subscription covering the
        # class type, which is not something this test is about but is
        # something it has to satisfy.
        pack = self.env["product.template"].create({
            "name": "Campaign Pack", "list_price": 100.0, "type": "service",
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 10, "fitness_validity_days": 365,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })

        def _attend(user, days_ago):
            order = self.env["sale.order"].sudo().create(
                {"partner_id": user.partner_id.id})
            self.env["sale.order.line"].sudo().create({
                "order_id": order.id,
                "product_id": pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
            })
            order.action_confirm()

            start = fields.Datetime.now() - timedelta(days=days_ago)
            event = self.env["calendar.event"].create({
                "name": "Campaign %s" % days_ago,
                "start": start, "stop": start + timedelta(minutes=50),
                "class_type_id": class_type.id, "is_fitness_class": True,
            })
            booking = self.env["fitness.booking"].sudo().with_context(
                fitness_record_past_attendance=True).create({
                    "student_id": user.partner_id.id,
                    "calendar_event_id": event.id,
                    "manager_override_timewindow": True,
                })
            booking.write({"state": "attended"})

        _attend(recent, 3)
        _attend(old, 90)

        camp = self._campaign(audience="attended_recently", days=30)
        self.assertIn(recent.partner_id, camp.recipient_ids)
        self.assertNotIn(
            old.partner_id, camp.recipient_ids,
            "a student who last came 90 days ago is inside a 30 day window")

    # ── sending ─────────────────────────────────────────────────────────────

    def test_sending_pins_the_settings_that_actually_enforce_one_answer(self):
        self._student("pin")
        camp = self._campaign()
        self.assertEqual(self.survey.access_mode, "public")
        self.assertFalse(self.survey.is_attempts_limited)

        camp.action_send()
        self.survey.invalidate_recordset()

        self.assertEqual(
            self.survey.access_mode, "token",
            "a public survey ignores the attempt limit entirely")
        self.assertTrue(self.survey.is_attempts_limited)
        self.assertEqual(self.survey.attempts_limit, 1)

    def test_each_student_gets_exactly_one_token(self):
        a, b = self._student("one_a"), self._student("one_b")
        camp = self._campaign()
        camp.action_send()

        for user in (a, b):
            answers = self.env["survey.user_input"].sudo().search([
                ("fitness_campaign_id", "=", camp.id),
                ("partner_id", "=", user.partner_id.id),
            ])
            self.assertEqual(
                len(answers), 1,
                "%s holds %s tokens - two tokens is two submissions however "
                "the attempt limit is set" % (user.name, len(answers)))

    def test_both_channels_carry_the_same_link(self):
        """The app-first and email-first orderings can only differ if the
        two channels hand her different tokens."""
        user = self._student("both")
        camp = self._campaign()
        camp.action_send()

        answer = self.env["survey.user_input"].sudo().search([
            ("fitness_campaign_id", "=", camp.id),
            ("partner_id", "=", user.partner_id.id)])
        self.assertEqual(len(answer), 1)

        notif = self.env["fitness.notification"].sudo().search(
            [("user_id", "=", user.id), ("notification_type", "=", "campaign")])
        self.assertTrue(notif, "she was not told in the app")
        self.assertIn(
            answer.access_token, notif[:1].action_url or "",
            "the bell points at a different token than the email")

    def test_a_student_with_an_email_actually_gets_one(self):
        """The half that was missing, and it cost a red build.

        action_send wraps the send in try/except and logs, so a template
        that cannot render fails every single send and the suite stays
        green. That is exactly what happened: the invite referenced
        survey_id.company_id, survey.survey has no company_id, and every
        campaign email died in the log while 567 tests passed. odoo.sh
        grades on ERROR lines, so it failed there and nowhere else.

        Asserting "no mail for a student with no address" without this is
        satisfied by a campaign that emails nobody at all.
        """
        user = self._student("mailed")
        camp = self._campaign()
        before = self.env["mail.mail"].sudo().search_count([])
        camp.action_send()

        self.assertGreater(
            self.env["mail.mail"].sudo().search_count([]), before,
            "no email was queued for a student who has an address - if the "
            "template cannot render, action_send swallows it and only the "
            "log knows")

        mail = self.env["mail.mail"].sudo().search(
            [], order="id desc", limit=1)
        self.assertTrue(
            mail.email_from,
            "the email has no sender, which the mail server will refuse")
        self.assertIn(
            "corelabstudio.es", mail.email_from,
            "the sender is not the studio - a foreign envelope sender is "
            "refused outright by the mail host")

    def test_a_student_with_no_email_is_still_reached_in_the_app(self):
        user = self._student("silent", email=False)
        camp = self._campaign()
        camp.action_send()

        # Counted against HER, not against the table. A campaign on a real
        # database reaches every other student too, so a global before/after
        # measures the studio's roll rather than this student - it passed on
        # an empty database and failed the moment it met real data.
        hers = self.env["mail.mail"].sudo().search_count(
            [("recipient_ids", "in", user.partner_id.ids)])
        self.assertEqual(
            hers, 0,
            "a mail was queued for a student with no address to send it to")
        self.assertTrue(
            self.env["fitness.notification"].sudo().search(
                [("user_id", "=", user.id),
                 ("notification_type", "=", "campaign")]),
            "in-app is her only channel and it did not fire")

    def test_it_cannot_be_sent_twice(self):
        self._student("twice")
        camp = self._campaign()
        camp.action_send()
        with self.assertRaises(UserError):
            camp.action_send()

    def test_an_empty_audience_is_refused(self):
        camp = self._campaign(audience="attended_recently", days=1)
        camp.invalidate_recordset()
        if camp.recipient_ids:
            self.skipTest("somebody attended in the last day on this database")
        with self.assertRaises(UserError):
            camp.action_send()

    def test_only_a_manager_can_send(self):
        user = self._student("guard")
        camp = self._campaign()
        with self.assertRaises(UserError):
            camp.with_user(user).action_send()

    # ── results ─────────────────────────────────────────────────────────────

    def test_the_response_rate_counts_only_this_campaign(self):
        a, b = self._student("rate_a"), self._student("rate_b")
        camp = self._campaign()
        camp.action_send()

        # Somebody answering the survey outside the campaign must not
        # flatter the rate.
        stranger = self.survey.sudo()._create_answer(
            partner=self.manager.partner_id, check_attempts=False)
        stranger.write({"state": "done"})

        answers = self.env["survey.user_input"].sudo().search(
            [("fitness_campaign_id", "=", camp.id)])
        answers[:1].write({"state": "done"})
        camp.invalidate_recordset()

        # sent_count is whatever the studio's roll is on this database, so
        # the assertions are about the ratio and the exclusion, not a
        # hardcoded 2 - which was only ever true on an empty one.
        self.assertGreaterEqual(
            camp.sent_count, 2, "the two students under test were not sent it")
        self.assertEqual(
            camp.response_count, 1,
            "an answer from outside the campaign was counted in it")
        self.assertAlmostEqual(
            camp.response_rate, 100.0 / camp.sent_count, places=4,
            msg="the rate does not match answered over sent")
