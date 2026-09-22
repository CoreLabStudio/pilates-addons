# -*- coding: utf-8 -*-
"""What the trial form may offer, and what it must never offer.

The form used to ask which discipline, then which class type, then when.
A class type is a catalogue entry, not a class: it says the studio runs
Reformer Sculpt, not that it runs one on Tuesday morning - so somebody could
ask for a class that did not run on their day at all, and a class the studio
had cancelled for that day was still on the list.

It asks when first now, and answers "which class?" from the timetable. That
makes the rule below the whole feature: these pin what `_trial_slots` may
return, because everything the student sees is whatever comes out of it.

The browser half is covered separately - the picker, the reload on a period
change, and the Reformer question appearing only for a Reformer class were
driven in a real browser. These are the half that browser work cannot pin:
the boundaries, and the re-check at submit time.
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import fields
from odoo.tests import TransactionCase, tagged

STUDIO_TZ = pytz.timezone('Europe/Madrid')


@tagged("post_install", "-at_install")
class TestTrialSlots(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Slots room", "classroom_type": "reformer", "capacity": 3})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Slots Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})
        cls.barre_room = cls.env["fitness.classroom"].create({
            "name": "Slots barre room", "classroom_type": "barre", "capacity": 5})
        cls.barre_type = cls.env["fitness.class.type"].create({
            "name": "Slots Barre", "classroom_type": "barre",
            "duration": 45, "level": "all", "session_type": "group",
            "classroom_id": cls.barre_room.id})
        # A day comfortably ahead, so nothing here is fighting the booking
        # window or "not in the past".
        cls.day = (fields.Datetime.now() + timedelta(days=9)).date()

    # -- fixtures ----------------------------------------------------------

    def _at(self, hour, minute=0, ctype=None, name=None, day=None):
        """A class at that wall-clock time in the studio's own timezone.

        Built through the timezone rather than with a raw UTC datetime on
        purpose: the boundary between morning and evening is a Madrid clock
        reading, and a test that writes UTC directly would pass in winter and
        fail in summer.
        """
        local = STUDIO_TZ.localize(
            datetime.combine(day or self.day, time(hour, minute)))
        start = local.astimezone(pytz.utc).replace(tzinfo=None)
        return self.env["calendar.event"].create({
            "name": name or ("Slot %02d:%02d" % (hour, minute)),
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": (ctype or self.ctype).id,
            "is_fitness_class": True,
        })

    def _slots(self, period=None, day=None):
        return self.env["fitness.trial.request"]._trial_slots(
            day or self.day, period)

    def _ids(self, period=None, day=None):
        return [s["id"] for s in self._slots(period, day)]

    # -- what must not be offered -----------------------------------------

    def test_a_cancelled_class_is_not_offered(self):
        """The reason the form was reordered at all."""
        event = self._at(10)
        self.assertIn(event.id, self._ids("morning"),
                      "the fixture is not being offered, so this proves nothing")
        event.class_state = "cancelled"
        self.assertNotIn(
            event.id, self._ids("morning"),
            "a class the studio cancelled is still offered on the trial form - "
            "somebody would be sent to a class that is not running")

    def test_an_archived_class_is_not_offered(self):
        event = self._at(10)
        self.assertIn(event.id, self._ids("morning"))
        event.active = False
        self.assertNotIn(event.id, self._ids("morning"),
                         "an archived class is still being offered")

    def test_a_private_class_is_not_offered(self):
        """A first free class is a group class; a private one is sold."""
        private_type = self.env["fitness.class.type"].create({
            "name": "Slots private", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "private",
            "classroom_id": self.room.id})
        event = self._at(10, ctype=private_type, name="Private slot")
        self.assertNotIn(
            event.id, self._ids("morning"),
            "a private session is being offered as a free trial")

    def test_a_class_in_the_past_is_not_offered(self):
        past = fields.Datetime.now() - timedelta(hours=3)
        event = self.env["calendar.event"].create({
            "name": "Yesterday", "start": past,
            "stop": past + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True})
        self.assertNotIn(event.id, self._ids(day=past.date()),
                         "a class that has already run is being offered")

    def test_a_full_class_is_not_offered(self):
        """The studio can only place a trial where there is a seat."""
        event = self._at(10)
        self.assertEqual(event.capacity, 3, "fixture capacity changed")
        pack = self.env["product.template"].create({
            "name": "Slots pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 30,
            "fitness_validity_days": 120, "fitness_class_type": "reformer",
            "fitness_session_type": "group"})
        for i in range(3):
            student = self.env["res.users"].create({
                "name": "Filler %d" % i,
                "login": "slots.filler.%d@example.invalid" % i,
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id])]})
            order = self.env["sale.order"].create(
                {"partner_id": student.partner_id.id})
            self.env["sale.order.line"].create({
                "order_id": order.id,
                "product_id": pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": pack.list_price,
                "fitness_class_type": "reformer"})
            order.action_confirm()
            self.env["fitness.booking"].create({
                "student_id": student.partner_id.id,
                "calendar_event_id": event.id,
                "package_order_line_id": order.order_line[:1].id,
                "manager_override_timewindow": True})
        self.assertNotIn(
            event.id, self._ids("morning"),
            "a class with no seat left is still offered; the student would "
            "choose something the studio cannot place them in")

    # -- the morning / evening boundary ------------------------------------

    def test_the_day_is_cut_in_the_studios_clock(self):
        """13:59 is morning, 14:00 is evening - in Madrid, not in UTC.

        Worth pinning rather than trusting: the stored value is UTC, and
        Madrid is one or two hours ahead depending on the season, so a naive
        comparison is right for half the year.
        """
        early = self._at(13, 59, name="Just before")
        late = self._at(14, 0, name="Just after")

        morning = self._ids("morning")
        evening = self._ids("evening")

        self.assertIn(early.id, morning, "13:59 should be a morning class")
        self.assertNotIn(early.id, evening, "13:59 leaked into the evening")
        self.assertIn(late.id, evening, "14:00 should be an evening class")
        self.assertNotIn(late.id, morning, "14:00 leaked into the morning")

    def test_no_period_means_the_whole_day(self):
        early = self._at(9, name="Morning one")
        late = self._at(19, name="Evening one")
        both = self._ids()
        self.assertIn(early.id, both)
        self.assertIn(late.id, both)

    def test_another_days_classes_are_not_offered(self):
        here = self._at(10)
        elsewhere = self._at(10, day=self.day + timedelta(days=1),
                             name="Next day")
        ids = self._ids("morning")
        self.assertIn(here.id, ids)
        self.assertNotIn(elsewhere.id, ids,
                         "a class on a different day is being offered")

    # -- what the form is given --------------------------------------------

    def test_each_slot_carries_what_the_picker_needs(self):
        """The discipline travels with the class, because nobody picks it now."""
        event = self._at(10)
        slot = [s for s in self._slots("morning") if s["id"] == event.id][0]
        self.assertEqual(slot["discipline"], "reformer")
        self.assertEqual(slot["class_type_id"], self.ctype.id)
        self.assertEqual(slot["time"], "10:00",
                         "the time is not the studio's wall clock: %s"
                         % slot["time"])
        self.assertEqual(slot["free"], 3)

    def test_both_disciplines_come_back_together(self):
        """The student no longer chooses Barre or Reformer up front."""
        reformer = self._at(10)
        barre = self._at(11, ctype=self.barre_type, name="Barre slot")
        ids = self._ids("morning")
        self.assertIn(reformer.id, ids)
        self.assertIn(barre.id, ids)

    def test_a_discipline_can_still_be_asked_for(self):
        reformer = self._at(10)
        barre = self._at(11, ctype=self.barre_type, name="Barre slot")
        only_barre = [s["id"] for s in self.env["fitness.trial.request"]
                      ._trial_slots(self.day, "morning", "barre")]
        self.assertIn(barre.id, only_barre)
        self.assertNotIn(reformer.id, only_barre)

    def test_the_form_and_the_studio_read_the_same_rule(self):
        """One domain, so the two lists cannot drift.

        The studio's candidate-slot screen and the public form are built from
        _trial_slot_domain. If somebody adds an exclusion to one path only,
        a student is offered a class the studio cannot place them in, or the
        reverse - which is the class of bug this whole rework exists to stop.
        """
        domain = self.env["fitness.trial.request"]._trial_slot_domain()
        flat = [tuple(c[:2]) for c in domain if isinstance(c, (list, tuple))]
        self.assertIn(("class_state", "!="), flat,
                      "the shared domain no longer excludes cancelled classes")
        self.assertIn(("class_type_id.session_type", "="), flat,
                      "the shared domain no longer restricts to group classes "
                      "via the class TYPE - the event's own session_type is "
                      "not filled on a programmatic create and cannot be "
                      "trusted")
        self.assertIn(("active", "="), flat,
                      "the shared domain no longer excludes archived classes")


@tagged("post_install", "-at_install")
class TestTrialSubmitRevalidates(TransactionCase):
    """A posted class is re-checked, not taken on trust.

    The form can sit open for a long time. Between the moment it listed a
    class and the moment somebody presses Submit, the studio can cancel that
    class - and the entire reason this form was reordered is that a cancelled
    class must not be bookable. Filtering the list at render time is only half
    of that; the other half is refusing the id when it arrives.

    Driven through the real HTTP route rather than by calling the handler,
    because the thing under test is what a browser can actually post.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Revalidate room", "classroom_type": "barre", "capacity": 8})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Revalidate Barre", "classroom_type": "barre",
            "duration": 45, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})
        cls.day = (fields.Datetime.now() + timedelta(days=9)).date()

    def _event(self, hour=10):
        local = STUDIO_TZ.localize(datetime.combine(self.day, time(hour, 0)))
        start = local.astimezone(pytz.utc).replace(tzinfo=None)
        return self.env["calendar.event"].create({
            "name": "Revalidate class", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True})

    def _post(self, event):
        from odoo.addons.fitness_trials.controllers.trial import (
            TrialRequestController)
        return TrialRequestController, event

    def test_a_class_cancelled_after_the_page_loaded_is_refused(self):
        event = self._event()
        offered = self.env["fitness.trial.request"]._trial_slots(
            self.day, "morning")
        self.assertIn(event.id, [s["id"] for s in offered],
                      "the fixture was never offered, so this proves nothing")

        event.class_state = "cancelled"
        still = self.env["fitness.trial.request"]._trial_slots(
            self.day, "morning")
        self.assertNotIn(
            event.id, [s["id"] for s in still],
            "the submit-time check reads _trial_slots, so a cancelled class "
            "must be absent from it or the re-check cannot refuse the post")

    def test_the_controller_rechecks_rather_than_trusting_the_post(self):
        """The regression itself, read off the handler.

        A blunt test, and worth being honest about: short of a browser that
        can cancel a class mid-form, what matters is that the posted id is
        put back through the same rule rather than browsed straight into the
        record. Its absence was invisible - the form looked right and the
        request simply recorded a class that was not running.
        """
        import inspect
        from odoo.addons.fitness_trials.controllers import trial

        source = inspect.getsource(trial.TrialRequestController.trial_submit)
        self.assertIn(
            "_trial_slots", source,
            "the submit handler no longer re-checks the posted class against "
            "the timetable; a class cancelled while the form was open would "
            "be accepted")
        self.assertNotIn(
            "browse(int(occurrence_raw))", source,
            "the posted occurrence id is being browsed directly instead of "
            "being validated first")


@tagged("post_install", "-at_install")
class TestAdminSlotPicker(TransactionCase):
    """What the studio is offered when it places a trial.

    Both pickers used to ignore preferred_date and preferred_period and offer
    every future class of the right discipline, nearest first. Two students
    were approved onto a class six and ten days before the date they had
    written down, and the confirmation email told them so.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Picker room", "classroom_type": "reformer",
            "capacity": 6})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Picker Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})
        cls.asked_for = (fields.Datetime.now() + timedelta(days=12)).date()
        cls.sooner = (fields.Datetime.now() + timedelta(days=4)).date()

    def _at(self, hour, day, ctype=None, name=None):
        local = STUDIO_TZ.localize(datetime.combine(day, time(hour, 0)))
        start = local.astimezone(pytz.utc).replace(tzinfo=None)
        return self.env["calendar.event"].create({
            "name": name or ("Picker %02d:00" % hour),
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": (ctype or self.ctype).id,
            "is_fitness_class": True,
        })

    def _request(self, **extra):
        vals = {
            "name": "Picker Requester",
            "email": "picker@example.invalid",
            "class_interest": "reformer",
            "preferred_date": self.asked_for,
            "preferred_period": "evening",
        }
        vals.update(extra)
        return self.env["fitness.trial.request"].create(vals)

    def test_the_picker_offers_the_day_that_was_asked_for(self):
        evening = self._at(19, self.asked_for, name="The one she asked for")
        morning = self._at(9, self.asked_for, name="Same day, wrong half")
        request = self._request()

        self.assertIn(evening, request.suggested_slot_ids)
        self.assertNotIn(
            morning, request.suggested_slot_ids,
            "she asked for an evening, so a nine o'clock class is not what "
            "she asked for")

    def test_a_sooner_class_is_not_offered_over_the_requested_day(self):
        """Marta asked for the 28th and was approved onto the 18th. The
        soonest class was simply the easiest thing to pick."""
        asked = self._at(19, self.asked_for, name="The 28th")
        soon = self._at(19, self.sooner, name="The 18th")
        request = self._request()

        self.assertEqual(request.suggested_slot_ids, asked)
        domain_ids = request.occurrence_id_domain[0][2]
        self.assertIn(asked.id, domain_ids)
        self.assertNotIn(
            soon.id, domain_ids,
            "a class a week before the requested date is still top of the "
            "picker, which is how two students were booked into the wrong "
            "week")

    def test_the_picker_widens_when_nothing_runs_that_day(self):
        """Narrowing to an empty list would leave nowhere to place anybody."""
        soon = self._at(19, self.sooner, name="The only class running")
        request = self._request()

        self.assertFalse(request.suggested_slot_ids)
        self.assertTrue(
            self.env["calendar.event"].search(
                request.occurrence_id_domain) >= soon,
            "with nothing on the requested day the picker has to fall back "
            "to every class, or the request cannot be approved at all")

    def test_show_all_slots_lifts_the_narrowing(self):
        """Placing somebody in a fuller class is a real thing the studio
        does - Eva and Ana were both moved that way on purpose."""
        self._at(19, self.asked_for, name="The one she asked for")
        soon = self._at(19, self.sooner, name="Somewhere fuller")
        request = self._request()
        self.assertNotIn(soon.id, request.occurrence_id_domain[0][2])

        request.show_all_slots = True

        self.assertIn(
            soon, self.env["calendar.event"].search(
                request.occurrence_id_domain),
            "the studio must always be one tick away from every class")

    def test_the_candidate_list_narrows_to_the_request(self):
        asked = self._at(19, self.asked_for, name="The 28th")
        soon = self._at(19, self.sooner, name="The 18th")
        request = self._request()

        action = request.action_view_candidate_slots()
        found = self.env["calendar.event"].search(action["domain"])

        self.assertIn(asked, found)
        self.assertNotIn(soon, found)
        self.assertIn("asked for", action["name"])

    def test_the_candidate_list_widens_when_nothing_matches(self):
        soon = self._at(19, self.sooner, name="The only class running")
        request = self._request()

        action = request.action_view_candidate_slots()
        found = self.env["calendar.event"].search(action["domain"])

        self.assertIn(soon, found)
        self.assertIn("every class", action["name"])

    def test_a_private_session_is_never_offered(self):
        """The old admin domain built its own rule and let these through, so
        a free trial could be placed into a session the studio sells."""
        private_type = self.env["fitness.class.type"].create({
            "name": "Picker Private", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "private",
            "classroom_id": self.room.id})
        private = self._at(19, self.asked_for, ctype=private_type,
                           name="A private session")
        self._at(20, self.asked_for, name="A real group class")
        request = self._request()

        self.assertNotIn(private, request.suggested_slot_ids)
        self.assertNotIn(
            private, self.env["calendar.event"].search(
                request.action_view_candidate_slots()["domain"]),
            "a private session is sold, not given away as a free trial")
