# -*- coding: utf-8 -*-
"""Choosing the weekly class a Clase Fija membership reserves.

Buying one of these memberships books nothing on its own: it promises the
same class every week without saying which. Until that is answered the member
is paying for an empty schedule, so the question follows her from the checkout
to Home rather than living on a page she has to find.

What these pin, in order of how much they would cost to get wrong:

  * the question survives the app being closed - the prompt is still there on
    the next visit, and the picker still answers
  * picking attaches the right recurring series and books every remaining week
    of the period, which is the whole feature
  * a slot that is full on any week of the period is shown but not offered:
    auto-placement books the period in one go and refuses the lot if one class
    is full, so offering it would hand her an admin's error mid-signup
  * the posted id is re-checked server side, so a slot outside her discipline
    cannot be taken by editing the form
  * the weekday is written in her own language, since the weekday is the
    entire choice
"""
from datetime import timedelta

import pytz

from odoo import fields
from odoo.tests import HttpCase, tagged

STUDIO_TZ = pytz.timezone('Europe/Madrid')


@tagged("post_install", "-at_install")
class TestFixedClassPicker(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "fixed-slot-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Fixed Slot Student",
            "login": "fixed.slot@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Reformer Room (picker test)",
            "classroom_type": "reformer",
            "capacity": 6,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Reformer Sculpt (picker test)",
            "classroom_type": "reformer",
            "session_type": "group",
            "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.teacher = cls.env["res.users"].create({
            "name": "Picker Teacher",
            "login": "picker.teacher@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

        # Two weekly slots so "offered" and "not offered" can be told apart
        # without one of them simply being the only row on the page.
        cls.sched_wed = cls._schedule("wed", 18.0)
        cls.sched_thu = cls._schedule("thu", 18.0)

        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.product = cls.env["product.template"].create({
            "name": "Reformer Fixed Class 1 (picker test)",
            "type": "service",
            "list_price": 70.0,
            "sale_ok": True,
            "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_is_clase_fija": True,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group",
            "weekly_class_allowance": 1,
        })

    @classmethod
    def _schedule(cls, weekday, start_time):
        sched = cls.env["fitness.class.schedule"].create({
            "class_type_id": cls.class_type.id,
            "teacher_user_id": cls.teacher.id,
            "classroom_id": cls.room.id,
            "weekday": weekday,
            "start_time": start_time,
            "duration": 1.0,
            "capacity": 6,
            "date_start": fields.Date.today(),
            "horizon_weeks": 8,
        })
        sched.action_generate()
        return sched

    def _subscribe(self):
        """A confirmed membership with no slot chosen yet."""
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_ids[:1].id,
                "product_uom_qty": 1,
            })],
        })
        order.action_confirm()
        return order

    def _login(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)

    def _get(self, url):
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")
        return res.text

    # ── the question is asked, and survives being ignored ───────────────────

    def test_home_asks_until_it_is_answered(self):
        sub = self._subscribe()
        self._login()

        home = self._get("/my/home")
        self.assertIn("/my/fixed-class", home,
                      "Home does not ask a member with no slot to choose one")

        # She closes the app without answering. A fresh session must still ask:
        # the prompt is derived from the subscription, not from anything held
        # on the session that logging out would take with it.
        self.authenticate(None, None)
        self._login()
        self.assertIn("/my/fixed-class", self._get("/my/home"),
                      "the prompt was lost when the app was closed")

        self._choose(self.sched_wed)
        self.assertTrue(sub.fitness_clase_fija_ids.filtered("active"))
        self.assertNotIn("/my/fixed-class", self._get("/my/home"),
                         "Home still asks after the slot was chosen")

    def _choose(self, sched):
        page = self._get("/my/fixed-class")
        self.assertIn('name="csrf_token"', page)
        token = page.split('name="csrf_token" value="')[1].split('"')[0] \
            if 'name="csrf_token" value="' in page else self.env['ir.http']._get_csrf_token()
        res = self.url_open("/my/fixed-class/choose",
                            data={"csrf_token": token, "schedule_id": sched.id},
                            timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:300])
        return res

    # ── picking books the whole period on the right series ──────────────────

    def test_picking_attaches_the_series_and_books_the_period(self):
        sub = self._subscribe()
        self._login()
        self._choose(self.sched_wed)

        slot = sub.fitness_clase_fija_ids.filtered("active")
        self.assertEqual(len(slot), 1, "exactly one slot should have been created")
        self.assertEqual(slot.calendar_event_id.recurrence_id,
                         self.sched_wed.recurrence_id,
                         "the slot is attached to the wrong recurring series")

        bookings = self.env["fitness.booking"].search([
            ("student_id", "=", self.partner.id),
            ("state", "=", "booked"),
        ])
        self.assertTrue(bookings, "picking a slot booked nothing")

        # Every booking is a Wednesday at 18:00 studio time, and belongs to the
        # series she chose rather than merely landing on the right weekday.
        for bk in bookings:
            local = pytz.utc.localize(bk.class_start).astimezone(STUDIO_TZ)
            self.assertEqual(local.weekday(), 2, "booked a class that is not a Wednesday")
            self.assertEqual(local.hour, 18, "booked a class at the wrong hour")
            self.assertEqual(bk.calendar_event_id.recurrence_id,
                             self.sched_wed.recurrence_id)

        start, end = sub._fitness_billing_period()
        for bk in bookings:
            self.assertGreaterEqual(bk.class_start.date(), start)
            self.assertLess(bk.class_start.date(), end)

    # ── a week that is full takes the slot off the menu ─────────────────────

    def test_a_slot_full_on_one_week_is_shown_but_not_offered(self):
        sub = self._subscribe()
        start, end = sub._fitness_billing_period()
        occurrences = self.env["calendar.event"].search([
            ("recurrence_id", "=", self.sched_thu.recurrence_id.id),
            ("start", ">=", fields.Datetime.to_string(
                fields.Datetime.to_datetime(start))),
        ], order="start asc")
        self.assertTrue(occurrences, "the test schedule generated no classes")

        # Fill a single week of the Thursday series. One is enough: placement
        # books the period in one go, so one full class makes the whole slot
        # unbookable, which is exactly what the page has to reflect.
        victim = occurrences[1] if len(occurrences) > 1 else occurrences[0]
        victim.write({"capacity": 6, "booked_seats": 6})

        self._login()
        page = self._get("/my/fixed-class")

        self.assertIn("Thursday", page,
                      "the full day vanished instead of explaining itself")
        self.assertIn("Wednesday", page, "the free day is not offered")

        # Only Wednesday carries a submit button; Thursday is inert.
        self.assertEqual(page.count('name="schedule_id"'), 1,
                         "a slot that cannot be booked every week was still offered")
        self.assertIn(str(self.sched_wed.id), page)

        # And the refusal holds even if the form is edited to post it anyway.
        self._choose(self.sched_thu)
        self.assertFalse(sub.fitness_clase_fija_ids.filtered("active"),
                         "a full slot was accepted from a posted form")

    # ── the server does not take the form's word for anything ──────────────

    def test_a_slot_outside_her_discipline_is_refused(self):
        barre_room = self.env["fitness.classroom"].create({
            "name": "Barre Room (picker test)", "classroom_type": "barre", "capacity": 8,
        })
        barre_type = self.env["fitness.class.type"].create({
            "name": "Barre Groove (picker test)", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": barre_room.id,
        })
        barre = self.env["fitness.class.schedule"].create({
            "class_type_id": barre_type.id, "teacher_user_id": self.teacher.id,
            "classroom_id": barre_room.id, "weekday": "tue", "start_time": 18.0,
            "duration": 1.0, "capacity": 8,
            "date_start": fields.Date.today(), "horizon_weeks": 8,
        })
        barre.action_generate()

        sub = self._subscribe()
        self._login()

        page = self._get("/my/fixed-class")
        self.assertNotIn("Barre Groove (picker test)", page,
                         "a Reformer member was offered a Barre class")

        self._choose(barre)
        self.assertFalse(sub.fitness_clase_fija_ids.filtered("active"),
                         "a Barre slot was accepted on a Reformer membership")

    # ── the label names the studio's hour, never the reader's ──────────────

    def test_the_slot_label_uses_the_studio_clock(self):
        """A member on another timezone must not stamp her own hour on it.

        name is stored, so whatever timezone is in context when the record is
        written is the hour everybody reads afterwards. Most accounts here
        carry no timezone and a large minority carry Asia/Calcutta, which put
        "21:30" on a class that runs at 18:00.
        """
        self.user.tz = "Asia/Calcutta"
        sub = self._subscribe()
        self._login()
        self._choose(self.sched_wed)

        slot = sub.fitness_clase_fija_ids.filtered("active")
        self.assertTrue(slot, "nothing was booked, so there is no label to check")
        local = pytz.utc.localize(
            slot.calendar_event_id.start).astimezone(STUDIO_TZ)
        self.assertIn(local.strftime("%H:%M"), slot.name,
                      "the label does not name the studio's hour: %s" % slot.name)
        self.assertNotIn("21:30", slot.name,
                         "the label was stamped in the member's timezone")

    # ── the weekday is the choice, so it has to be in her language ──────────

    def test_the_weekday_is_written_in_her_language(self):
        self._subscribe()
        es = self.env["res.lang"]._activate_lang("es_ES")
        if not es:
            self.skipTest("Spanish not installed in this database")
        self.user.lang = "es_ES"
        self._login()
        page = self._get("/es/my/fixed-class")
        self.assertIn("Elige tu clase semanal", page,
                      "the picker heading did not translate")
        self.assertIn("rcoles", page,
                      "the weekday is still in English on a Spanish page")
