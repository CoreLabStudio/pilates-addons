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

    # -- what the form offers ----------------------------------------------

    def _schedule_row(self, class_type, weekday="mon"):
        # teacher_user_id is required on a schedule row: a slot with nobody
        # teaching it is not a slot.
        if not getattr(self, "_teacher", None):
            self._teacher = self.env["res.users"].create({
                "name": "Workflow Teacher",
                "login": "workflow.teacher@example.invalid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })
        return self.env["fitness.class.schedule"].create({
            "name": "%s %s" % (class_type.name, weekday),
            "class_type_id": class_type.id,
            "teacher_user_id": self._teacher.id,
            "weekday": weekday,
            "start_time": 10.0,
            "session_type": "group",
        })

    def test_only_scheduled_classes_are_offered(self):
        """The catalogue is not the timetable.

        Every class type with a Barre or Reformer room used to be offered,
        including ones the studio has never scheduled or has stopped running.
        Somebody asking for their first visit was shown classes they could not
        have, and the studio had to explain why.
        """
        unscheduled = self.env["fitness.class.type"].create({
            "name": "Never Scheduled",
            "classroom_type": "reformer",
            "duration": 50,
            "level": "all",
            "session_type": "group",
        })
        self._schedule_row(self.class_type)
        offered = self.env["fitness.trial.request"]._offered_class_types()
        names = [c["name"] for c in offered["reformer"]]
        self.assertIn(self.class_type.name, names)
        self.assertNotIn(
            unscheduled.name, names,
            "a class nobody has put on the timetable must not be offered",
        )

    def test_a_retired_class_drops_off_the_form(self):
        """Archiving is how the studio retires a class.

        mapped() browses by id, so an archived class type still comes back
        through its schedule row unless it is filtered out.
        """
        self._schedule_row(self.class_type)
        trials = self.env["fitness.trial.request"]
        self.assertIn(
            self.class_type.name,
            [c["name"] for c in trials._offered_class_types()["reformer"]])
        self.class_type.active = False
        self.env.flush_all()
        self.assertNotIn(
            self.class_type.name,
            [c["name"] for c in trials._offered_class_types()["reformer"]],
            "a retired class must not still be offered as somebody's first one",
        )

    def test_closed_slots_drop_off_the_form(self):
        """Closing a slot archives its schedule row; the form follows.

        A second slot for a different class is left standing on purpose. With
        only one row on the whole timetable, archiving it empties the
        timetable entirely and the deliberate fallback below takes over - so
        without this the test would be measuring the fallback, not the
        closure.
        """
        other = self.env["fitness.class.type"].create({
            "name": "Still Running", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
        })
        self._schedule_row(other)
        row = self._schedule_row(self.class_type)
        trials = self.env["fitness.trial.request"]
        self.assertIn(
            self.class_type.name,
            [c["name"] for c in trials._offered_class_types()["reformer"]])
        row.active = False
        self.assertNotIn(
            self.class_type.name,
            [c["name"] for c in trials._offered_class_types()["reformer"]],
            "closing a slot should take its class off the form",
        )
        self.assertIn(
            other.name,
            [c["name"] for c in trials._offered_class_types()["reformer"]],
            "and leave the slots that are still running alone",
        )

    def test_an_empty_timetable_falls_back_to_the_catalogue(self):
        """The one case where the catalogue is still used.

        A database that has not been seeded, or a studio between schedules,
        would otherwise show a discipline with no classes under it and a form
        nobody can complete. Showing the catalogue is the lesser wrong, and it
        is deliberate rather than an oversight - hence a test saying so.
        """
        self.env["fitness.class.schedule"].search([]).active = False
        trials = self.env["fitness.trial.request"]
        offered = trials._offered_class_types()
        self.assertTrue(
            offered["reformer"] or offered["barre"],
            "with no timetable at all the form should still offer something",
        )

    def test_open_days_come_from_the_timetable(self):
        """Not a hard-coded Monday-to-Friday.

        If the studio opens a Saturday, the form should follow without anyone
        editing it.
        """
        trials = self.env["fitness.trial.request"]
        self._schedule_row(self.class_type, "mon")
        self._schedule_row(self.class_type, "wed")
        self.assertEqual(trials._open_weekdays(), ["mon", "wed"])
        self._schedule_row(self.class_type, "sat")
        self.assertEqual(trials._open_weekdays(), ["mon", "wed", "sat"])

    def test_the_day_hint_reads_as_a_range_only_when_it_is_one(self):
        """"Monday to Friday" would be a lie if Wednesday were closed."""
        trials = self.env["fitness.trial.request"]
        self.assertEqual(
            trials._weekday_hint(["mon", "tue", "wed", "thu", "fri"], "en_US"),
            "Monday to Friday")
        self.assertEqual(
            trials._weekday_hint(["mon", "tue", "thu"], "en_US"),
            "Monday, Tuesday, Thursday")

    # -- who the request is for ---------------------------------------------

    def test_choosing_a_student_fills_their_details(self):
        """The link already worked the other way; this is the desk's way round.

        An admin taking a request over the phone picks the student first, and
        was then retyping a name, address and number the contact already has.
        """
        self.partner.write({
            "email": "laura.probe@example.invalid",
            "phone": "+34 600 111 222",
            "lang": "es_ES",
        })
        request = self.env["fitness.trial.request"].new({
            "partner_id": self.partner.id,
            "class_interest": "reformer",
            "lang": "en_US",
        })
        request._onchange_partner_id()
        self.assertEqual(request.email, "laura.probe@example.invalid")
        self.assertEqual(request.phone, "+34 600 111 222")
        self.assertEqual(request.name, self.partner.name)
        self.assertEqual(
            request.lang, "es_ES",
            "the confirmation email should go out in the language the contact "
            "reads, not whatever the form happened to default to",
        )

    def test_a_contact_without_a_phone_does_not_blank_one(self):
        """Only ever writes something.

        A contact with no number must not wipe one somebody has just typed in.
        """
        self.partner.write({"phone": False, "email": "nophone@example.invalid"})
        request = self.env["fitness.trial.request"].new({
            "partner_id": self.partner.id,
            "class_interest": "reformer",
            "phone": "+34 600 999 000",
        })
        request._onchange_partner_id()
        self.assertEqual(request.phone, "+34 600 999 000")

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
        self._decline(second)
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

    def test_the_reason_is_optional(self):
        """Sometimes there is nothing useful to say.

        A box that insists on a sentence just collects full stops, and both
        the email and the notification read properly without one.
        """
        request = self._request()
        self._decline(request, "   ")
        self.assertEqual(request.status, "declined")
        self.assertFalse(
            request.decline_reason,
            "whitespace is the same as nothing, and a notification whose body "
            "is a space helps nobody",
        )

    def test_cancelling_from_the_status_field_is_refused(self):
        """One way to cancel, and it is the one that tells the student.

        The Status field was a second route to the same state that sent
        nothing. Enforced on the model rather than by hiding the field: an
        import or a plain RPC write reaches here too.
        """
        request = self._request()
        with self.assertRaises(UserError):
            request.write({"status": "declined"})
        self.assertEqual(
            request.status, "pending",
            "a refused cancellation must leave the request alone",
        )

    def test_an_already_cancelled_request_can_still_be_written_to(self):
        """The guard is about the transition, not about the state.

        Editing something else on a request that is already cancelled - or a
        write that happens to carry the status it already has - must not be
        mistaken for a second cancellation.
        """
        request = self._request()
        self._decline(request)
        request.write({"status": "declined", "name": "Renamed afterwards"})
        self.assertEqual(request.name, "Renamed afterwards")

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
