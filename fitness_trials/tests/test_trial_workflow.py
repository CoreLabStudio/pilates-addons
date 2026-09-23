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
        # The studio's real timetable runs Monday to Friday, so the answer
        # here is only this test's once the test owns the schedule - the same
        # clearing the no-timetable case above does. Rolled back after.
        self.env["fitness.class.schedule"].search([]).active = False
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

    # -- one booking, one truth ---------------------------------------------

    def _approved(self):
        """A request that has been approved, so a booking exists behind it."""
        request = self._request(partner_id=self.partner.id)
        request.occurrence_id = self._event()
        request.action_approve_and_book()
        return request

    def test_approval_remembers_the_booking(self):
        request = self._approved()
        self.assertEqual(request.status, "scheduled")
        self.assertTrue(
            request.booking_id,
            "without the link the request cannot follow its booking",
        )

    def test_cancelling_the_booking_cancels_the_request(self):
        """The studio cancelled one student's place, and the trial list went
        on saying the class was happening until somebody cancelled it a second
        time."""
        request = self._approved()
        booking = request.booking_id
        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id, "reason": "She cannot make it.",
        }).action_confirm()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            request.status, "declined",
            "the request should follow its booking rather than needing a "
            "second cancellation",
        )

    def test_cancelling_the_request_cancels_the_booking(self):
        """And the other way round, which used to be refused outright."""
        request = self._approved()
        booking = request.booking_id
        self._decline(request, "The studio is calling this one off.")
        self.assertEqual(request.status, "declined")
        self.assertEqual(booking.state, "cancelled")
        self.assertTrue(
            booking.credit_returned,
            "cancelling from this side must release the seat and hand the "
            "credit back, which is why it used to send the studio away",
        )

    def test_cancelling_the_whole_class_cancels_the_request(self):
        request = self._approved()
        request.occurrence_id.action_cancel_class()
        self.assertEqual(request.status, "declined")

    def test_a_request_scheduled_before_the_link_existed_still_follows(self):
        """Rows approved before booking_id was added resolve by student and
        class instead, so production history needs no migration."""
        request = self._approved()
        booking = request.booking_id
        request.booking_id = False
        self.assertEqual(request._find_booking(), booking)
        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id,
        }).action_confirm()
        self.assertEqual(request.status, "declined")

    # -- moving ------------------------------------------------------------

    def _move(self, booking, target):
        """Move a booking the way the desk does, through the wizard."""
        wizard = self.env["fitness.booking.reassign.wizard"].create({
            "booking_id": booking.id,
            "target_event_id": target.id,
        })
        return wizard.action_move_student()

    def test_moving_the_booking_moves_the_request(self):
        """Four requests on production named a class the student had been
        moved out of. The seat moved, both rosters were refreshed and the
        student was told - and the request went on naming the old class,
        which is what the confirmation email quotes."""
        request = self._approved()
        origin = request.occurrence_id
        target = self._event(days=9, name="Somewhere else")

        self._move(request.booking_id, target)

        self.assertEqual(
            request.occurrence_id, target,
            "the request must name the class the student is actually in",
        )
        self.assertEqual(
            request.scheduled_datetime, target.start,
            "the time the student is quoted has to follow the slot too",
        )
        self.assertNotEqual(request.occurrence_id, origin)

    def test_moving_by_a_plain_write_moves_the_request(self):
        """Typing a new class into the booking form skips the wizard, so
        nothing fires. One student was moved that way on production and never
        heard about it; the records should agree even on that path."""
        request = self._approved()
        target = self._event(days=11, name="Typed in by hand")

        request.booking_id.write({"calendar_event_id": target.id})

        self.assertEqual(request.occurrence_id, target)
        self.assertEqual(request.scheduled_datetime, target.start)

    def test_a_request_from_before_the_link_existed_follows_a_move(self):
        """The legacy match resolves by student and class, which only works
        against the event the booking is leaving - so it has to be read
        before the write, not after."""
        request = self._approved()
        booking = request.booking_id
        request.booking_id = False
        target = self._event(days=13, name="Legacy move target")

        self._move(booking, target)

        self.assertEqual(
            request.occurrence_id, target,
            "a request approved before booking_id existed still has to follow",
        )

    def test_a_request_that_is_not_scheduled_is_left_alone(self):
        """A finished request is not waiting to be corrected.

        The status is set the way the model allows - writing it directly is
        refused on purpose, so that cancelling always goes through the button
        that tells the student.
        """
        request = self._approved()
        booking = request.booking_id
        origin = request.occurrence_id
        request.with_context(**{request._DECLINE_KEY: True}).write(
            {"status": "declined"})
        target = self._event(days=15, name="Not a trial move")

        booking.write({"calendar_event_id": target.id})

        self.assertEqual(booking.calendar_event_id, target)
        self.assertEqual(
            request.occurrence_id, origin,
            "a request that is no longer scheduled must not be rewritten",
        )

    def test_a_booking_with_no_trial_behind_it_moves_fine(self):
        """Most bookings are not trials at all. The hook must not care.

        The request is removed rather than unlinked from the booking: the
        legacy fallback matches on student and class, so a request with its
        booking_id cleared is still found - which is the point of it.
        """
        request = self._approved()
        booking = request.booking_id
        request.unlink()
        target = self._event(days=21, name="Ordinary move")

        booking.write({"calendar_event_id": target.id})

        self.assertEqual(booking.calendar_event_id, target)

    def test_a_moved_request_can_still_be_cancelled(self):
        """The move hook writes the field the cancel hook reads."""
        request = self._approved()
        target = self._event(days=17, name="Move then cancel")
        self._move(request.booking_id, target)

        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": request.booking_id.id,
            "reason": "She cannot make the new one either.",
        }).action_confirm()

        self.assertEqual(request.status, "declined")

    def test_the_move_is_written_into_the_history(self):
        """Nothing on the record said which side had moved or when, which is
        the whole reason these four took a day to explain."""
        request = self._approved()
        target = self._event(days=19, name="Tracked move")
        # mail.thread suppresses tracking for a record created in the same
        # transaction - _track_discard sets its initial values to None, so
        # nothing is compared against. Running the precommit queue clears that
        # and leaves the request in the state production sees it in: created
        # earlier, moved now. Without this the test would report the feature
        # broken when only the fixture is.
        self.env.flush_all()
        self.env.cr.precommit.run()

        self._move(request.booking_id, target)
        # Tracking is finalised by a precommit callback, not inside write(),
        # and a TransactionCase never commits.
        self.env.flush_all()
        self.env.cr.precommit.run()

        tracked = request.message_ids.tracking_value_ids.filtered(
            lambda t: t.field_id.name == "occurrence_id")
        self.assertTrue(
            tracked,
            "the slot changing has to leave a trace on the request",
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

    def test_a_scheduled_request_with_no_booking_still_cancels(self):
        """Replaces a test that asserted the old refusal.

        Cancelling a scheduled request used to be refused outright, on the
        grounds that the booking was the real subject - which just made the
        studio do it in two places. It cancels the booking itself now.

        This is the odd case that survives: a request marked scheduled with
        nothing behind it, because somebody set the status by hand or the
        booking was deleted. There is nothing to cancel, and refusing to
        cancel the request would strand it as Scheduled for ever.
        """
        request = self._request(partner_id=self.partner.id)
        request.occurrence_id = self._event()
        request.write({"status": "scheduled"})
        self.assertFalse(request._find_booking())
        self._decline(request, "Nothing behind this one.")
        self.assertEqual(request.status, "declined")

    # -- one free trial per student, either discipline ----------------------

    def _claim_free_trial(self, partner, xmlid):
        """A student takes their free trial: a confirmed, zero-cost order."""
        product = self.env.ref(xmlid)
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 0.0,
            })],
        })
        order.action_confirm()
        return order

    def test_a_reformer_trial_spends_the_barre_one_too(self):
        """The whole point: one entitlement, not one of each. The portal has
        always said so - "It is one per student, Barre or Reformer" - and the
        desk used to disagree, handing out a second free trial."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "One Trial Only", "email": "one.trial@example.invalid"})
        barre = self.env.ref("fitness_packages.product_barre_trial")

        self.assertFalse(
            TR._trial_already_claimed(partner, barre),
            "fixture is wrong: she has claimed nothing yet")

        self._claim_free_trial(partner, "fitness_packages.product_reformer_trial")

        self.assertTrue(
            TR._trial_already_claimed(partner, barre),
            "taking the Reformer trial has to spend the Barre one as well")

    def test_a_barre_trial_spends_the_reformer_one_too(self):
        """The same, the other way round - the direction nobody checked."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Other Way", "email": "other.way@example.invalid"})
        reformer = self.env.ref("fitness_packages.product_reformer_trial")

        self._claim_free_trial(partner, "fitness_packages.product_barre_trial")

        self.assertTrue(
            TR._trial_already_claimed(partner, reformer),
            "it has to hold in both directions or it is not one entitlement")

    def test_a_student_who_has_claimed_nothing_is_not_blocked(self):
        """The rule must not refuse everybody - which a too-broad search would."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Never Claimed", "email": "never@example.invalid"})

        for xmlid in ("fitness_packages.product_barre_trial",
                      "fitness_packages.product_reformer_trial"):
            self.assertFalse(
                TR._trial_already_claimed(partner, self.env.ref(xmlid)),
                "a student with no trial behind them is entitled to one")

    def test_a_paid_trial_class_does_not_spend_the_entitlement(self):
        """Somebody who paid for a trial class has not used their free one -
        the rule reads zero-cost orders, not any order of the product."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Paid For It", "email": "paid@example.invalid"})
        product = self.env.ref("fitness_packages.product_barre_trial")
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 12.0,
            })],
        })
        order.action_confirm()

        self.assertFalse(
            TR._trial_already_claimed(partner, product),
            "paying for a class must not burn the free entitlement")

    def test_approval_refuses_a_second_free_trial_in_the_other_discipline(self):
        """End to end, through the button Yoleyva actually presses."""
        from odoo.exceptions import UserError
        partner = self.env["res.partner"].create(
            {"name": "Second Bite", "email": "second.bite@example.invalid"})
        self._claim_free_trial(partner, "fitness_packages.product_reformer_trial")

        request = self._request(partner_id=partner.id, class_interest="barre")
        request.occurrence_id = self._event()

        with self.assertRaises(UserError):
            request.action_approve_and_book()

    # -- the mirror: the request's slot moves the booking -------------------

    def test_changing_the_slot_moves_the_booking(self):
        """The direction that reached a customer. Yoleyva corrected the slot
        on the request and re-sent the confirmation; the booking stayed where
        it was, so the email named a day the student had no place on."""
        request = self._approved()
        booking = request.booking_id
        origin = request.occurrence_id
        target = self._event(days=23, name="Corrected slot")

        request.write({'occurrence_id': target.id})

        booking.invalidate_recordset()
        self.assertEqual(
            booking.calendar_event_id, target,
            "the seat has to move with the slot, or the email lies")
        self.assertNotEqual(booking.calendar_event_id, origin)

    def test_both_seat_counts_follow(self):
        """It goes through fitness.booking.write(), so the rosters recount."""
        request = self._approved()
        origin = request.occurrence_id
        target = self._event(days=25, name="Counted slot")
        origin.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 1, "fixture is wrong")

        request.write({'occurrence_id': target.id})

        origin.invalidate_recordset(); target.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 0)
        self.assertEqual(target.booked_seats, 1)

    def test_the_student_is_told_once(self):
        """Two mechanisms telling her would be two messages about one move -
        which is what she already received, naming different days."""
        request = self._approved()
        booking = request.booking_id
        before = len(booking.message_ids)
        target = self._event(days=27, name="Told once")

        request.write({'occurrence_id': target.id})

        booking.invalidate_recordset()
        moved = [m for m in booking.message_ids
                 if 'cambiado' in (m.subject or '').lower()
                 or 'moved' in (m.subject or '').lower()
                 or 'canviat' in (m.subject or '').lower()]
        self.assertLessEqual(len(moved), 1, "she was told twice about one move")
        self.assertGreater(len(booking.message_ids), before)

    def test_the_two_directions_do_not_chase_each_other(self):
        """The request moves the booking, and the booking syncs the request.
        If neither stopped, this would not return."""
        request = self._approved()
        target = self._event(days=29, name="No loop")

        request.write({'occurrence_id': target.id})

        request.invalidate_recordset()
        request.booking_id.invalidate_recordset()
        self.assertEqual(request.occurrence_id, target)
        self.assertEqual(request.booking_id.calendar_event_id, target)

    def test_a_cancelled_seat_is_not_dragged_along(self):
        """Moving it would put her back in a room she was taken out of."""
        request = self._approved()
        booking = request.booking_id
        self.env["fitness.booking.cancel.wizard"].create({
            "booking_id": booking.id, "reason": "She cannot come."}).action_confirm()
        booking.invalidate_recordset()
        was_on = booking.calendar_event_id
        target = self._event(days=31, name="Not for the cancelled")

        request.write({'occurrence_id': target.id})

        booking.invalidate_recordset()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            booking.calendar_event_id, was_on,
            "a cancelled seat must stay where it was, not follow the slot")

    def test_a_request_that_is_not_scheduled_moves_nothing(self):
        """Choosing a slot before approving is not moving anybody."""
        request = self._request(partner_id=self.partner.id)
        first = self._event(days=33, name="Just considering")
        request.occurrence_id = first.id
        second = self._event(days=35, name="Changed my mind")

        request.write({'occurrence_id': second.id})

        self.assertEqual(request.status, "pending")
        self.assertFalse(request.booking_id)
        first.invalidate_recordset(); second.invalidate_recordset()
        self.assertEqual(first.booked_seats, 0)
        self.assertEqual(second.booked_seats, 0)

    # -- one open request at a time ----------------------------------------

    def test_a_second_request_is_refused_while_one_is_open(self):
        """She asked yesterday and asked again today: the studio then has two
        rows for one person and no way to tell which she meant."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Asked Twice", "email": "asked.twice@example.invalid"})
        self._request(partner_id=partner.id, status="pending")

        self.assertTrue(
            TR._open_request_for(partner),
            "the first request has to count as open")

    def test_a_finished_request_does_not_block_a_new_one(self):
        """Declined and scheduled are finished - somebody whose trial has
        been and gone may ask again."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Asked Before", "email": "asked.before@example.invalid"})
        req = self._request(partner_id=partner.id, status="pending")
        self._decline(req, "No space that week.")

        self.assertFalse(
            TR._open_request_for(partner),
            "a declined request must not block her from asking again")

    def test_the_open_check_is_per_student_not_per_discipline_by_default(self):
        """Home offers one trial, so any open request hides it; the shop asks
        per discipline because its cards are per discipline."""
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "One Discipline", "email": "one.disc@example.invalid"})
        self._request(partner_id=partner.id, status="pending",
                      class_interest="barre")

        self.assertTrue(TR._open_request_for(partner))
        self.assertTrue(TR._open_request_for(partner, "barre"))
        self.assertFalse(
            TR._open_request_for(partner, "reformer"),
            "an open Barre request must not silence the Reformer card")

    def test_nobody_with_no_request_is_blocked(self):
        TR = self.env["fitness.trial.request"]
        partner = self.env["res.partner"].create(
            {"name": "Never Asked", "email": "never.asked@example.invalid"})
        self.assertFalse(TR._open_request_for(partner))
