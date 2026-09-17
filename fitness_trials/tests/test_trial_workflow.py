# -*- coding: utf-8 -*-
"""The trial request as the studio works it, from four reports off production.

This model had no tests at all, which is how the four behaviours below reached
a live studio. Written model-level: every one of them is a model decision, and
a TransactionCase exercises them without the HTTP session handling that makes
the portal's own suite flaky.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrialWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Neither the opening date nor the booking window is under test here,
        # and together they can leave no usable class at all.
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.student = cls.env["res.users"].create({
            "name": "Trial Workflow Student",
            "login": "trial.workflow@example.invalid",
            "email": "trial.workflow@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.student.partner_id
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Workflow Reformer",
            "classroom_type": "reformer",
            "duration": 50,
            "level": "all",
            "session_type": "group",
        })

    def _event(self, days=3, name="Workflow class"):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": name,
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
        })

    def _request(self, **extra):
        vals = {
            "name": "Workflow Requester",
            "email": "trial.workflow@example.invalid",
            "class_interest": "reformer",
            "class_type_id": self.class_type.id,
            "status": "pending",
        }
        vals.update(extra)
        return self.env["fitness.trial.request"].create(vals)

    # -- the candidate-slot list -------------------------------------------

    def test_candidate_slots_are_not_grouped(self):
        """Slots for <name> must not ask for a default grouping.

        calendar.event._read_group ANDs the personal-calendar privacy domain
        onto any grouped read whose fields are not all "public", and __count
        never is - so grouping by anything applies it and the studio's own
        classes vanish. Measured on a copy of production: 53 classes flat,
        one group counting 1.
        """
        self._event()
        action = self._request().action_view_candidate_slots()
        self.assertFalse(
            action["context"].get("search_default_group_by_start"),
            "grouping calendar.event applies the privacy domain and empties "
            "the list the studio needs in order to approve a trial",
        )
        self.assertTrue(
            self.env["calendar.event"].search_count(action["domain"]),
            "the action should open on classes, not an empty list",
        )

    def test_grouping_really_does_hide_them(self):
        """The reason the grouping is gone, asserted rather than asserted about.

        Read as a real staff user, not as the superuser a TransactionCase
        runs as: calendar.event only applies the privacy domain when env.su
        is False, which is the studio's situation and not the test runner's.
        Running this as the default user passes for the wrong reason.

        If a future Odoo stops applying that domain to grouped reads, this is
        the test that will say so, and the default grouping could come back.
        """
        self._event()
        staff = self.env["res.users"].create({
            "name": "Workflow Manager",
            "login": "trial.workflow.manager@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_manager").id,
            ])],
        })
        domain = self._request().action_view_candidate_slots()["domain"]
        events = self.env["calendar.event"].with_user(staff)
        self.assertFalse(events.env.su, "the point of the test is a non-su read")
        flat = events.search_count(domain)
        if not flat:
            self.skipTest("this user cannot read classes at all; nothing to compare")
        grouped = events._read_group(
            domain, groupby=["start:month"], aggregates=["__count"])
        self.assertLess(
            sum(row[-1] for row in grouped), flat,
            "grouping no longer hides classes from a staff user - the default "
            "grouping this action dropped could be revisited",
        )

    # -- the scheduled time ------------------------------------------------

    def test_scheduled_time_comes_from_the_slot(self):
        request = self._request()
        self.assertFalse(request.scheduled_datetime)
        event = self._event()
        request.occurrence_id = event
        self.assertEqual(
            request.scheduled_datetime, event.start,
            "the slot already carries the date and time; the request should "
            "not ask anybody to retype it",
        )

    def test_choosing_a_slot_does_not_schedule_the_request(self):
        """Picking a candidate to consider is not approving it.

        write() used to advance to 'scheduled' whenever a datetime was saved,
        which was about a time typed by hand. Now that the time arrives with
        the slot, that would mark a request scheduled with nothing booked.
        """
        request = self._request()
        request.occurrence_id = self._event()
        self.assertEqual(request.status, "pending")

    def test_an_existing_scheduled_time_is_never_blanked(self):
        """Deliberately not a computed field.

        A request scheduled before this screen had slots carries a time that
        nothing else records. A stored compute would clear it to keep the
        model tidy, and that is the only copy the studio has.
        """
        when = fields.Datetime.now() + timedelta(days=5)
        request = self._request()
        request.write({"status": "scheduled"})
        self.env.cr.execute(
            "UPDATE fitness_trial_request SET scheduled_datetime = %s WHERE id = %s",
            (when, request.id))
        request.invalidate_recordset(["scheduled_datetime"])
        request.write({"name": "Renamed, nothing to do with the time"})
        self.assertTrue(
            request.scheduled_datetime,
            "an old scheduled time must survive an unrelated write",
        )

    # -- duplicates --------------------------------------------------------

    def test_a_lone_request_is_not_flagged(self):
        self.assertEqual(self._request().other_open_count, 0)

    def test_two_open_requests_from_one_person_are_flagged(self):
        first = self._request()
        second = self._request(email="TRIAL.WORKFLOW@EXAMPLE.INVALID")
        self.assertEqual(first.other_open_count, 1)
        self.assertEqual(second.other_open_count, 1)
        self.assertIn(second, first.other_open_ids)
        self.assertTrue(first.duplicate_warning)

    def test_a_finished_request_stops_counting(self):
        first = self._request()
        second = self._request()
        self.assertEqual(first.other_open_count, 1)
        second.write({"status": "declined"})
        first.invalidate_recordset()
        self.assertEqual(
            first.other_open_count, 0,
            "a declined request is somebody else's decision already made",
        )

    # -- cancelling --------------------------------------------------------

    def _decline(self, request, reason="No space that week."):
        wizard = self.env["fitness.trial.decline.wizard"].create({
            "request_id": request.id, "reason": reason})
        return wizard.action_confirm()

    def test_cancelling_records_the_reason(self):
        request = self._request()
        self._decline(request, "No Reformer space that week.")
        self.assertEqual(request.status, "declined")
        self.assertEqual(request.decline_reason, "No Reformer space that week.")

    def test_cancelling_will_not_proceed_without_a_reason(self):
        request = self._request()
        with self.assertRaises(UserError):
            self._decline(request, "   ")
        self.assertEqual(
            request.status, "pending",
            "a refused cancellation must leave the request alone",
        )

    def test_cancelling_notifies_the_student_in_the_app(self):
        request = self._request(partner_id=self.partner.id)
        before = self.env["fitness.notification"].search_count(
            [("user_id", "=", self.student.id)])
        self._decline(request, "No Reformer space that week.")
        notifs = self.env["fitness.notification"].search(
            [("user_id", "=", self.student.id),
             ("notification_type", "=", "trial_declined")], order="id desc")
        self.assertTrue(notifs, "the student should hear about it in the app")
        self.assertEqual(
            self.env["fitness.notification"].search_count(
                [("user_id", "=", self.student.id)]), before + 1)
        self.assertIn("No Reformer space that week.", notifs[0].body or "")
        self.assertEqual(
            notifs[0].action_url, "/my/trial",
            "asking again is the thing to do next, so that is where it points",
        )

    def test_cancelling_without_a_portal_user_does_not_blow_up(self):
        """Somebody who asked from the public site has no app to be told in.

        The declined email is their copy; the cancellation must still go
        through rather than failing on a notification nobody can receive.
        """
        request = self._request(email="stranger@example.invalid")
        self._decline(request)
        self.assertEqual(request.status, "declined")

    def test_cancelling_spends_nothing(self):
        """A declined request leaves the trial where it was.

        Approval is what mints the order, so nothing has been claimed - which
        is why the student can ask again, and why the notification says so.
        """
        request = self._request(partner_id=self.partner.id)
        self._decline(request)
        self.assertFalse(
            self.env["sale.order"].search_count(
                [("partner_id", "=", self.partner.id)]),
            "declining must not leave an order behind",
        )
        self.assertFalse(
            self.env["fitness.trial.request"].search_count([
                ("partner_id", "=", self.partner.id),
                ("status", "in", list(
                    self.env["fitness.trial.request"].OPEN_STATES)),
            ]),
            "nothing should be left blocking a fresh request",
        )

    def test_a_scheduled_request_is_not_cancelled_from_here(self):
        """The class is booked; the seat and the credit are the real subject.

        Declining the request would leave the booking standing and the student
        holding a class nobody meant them to have.
        """
        request = self._request(partner_id=self.partner.id)
        request.occurrence_id = self._event()
        request.write({"status": "scheduled"})
        with self.assertRaises(UserError):
            self._decline(request)
