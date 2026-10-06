# -*- coding: utf-8 -*-
"""A class the nightly job booked for her is a class she can see.

The placement job books fixed-class members into the weeks of the
timetable that did not exist when they bought. Nothing about that is
worth anything if the student cannot see the result: a class she holds
a seat in, cannot see, and therefore does not come to is worse than no
booking at all - the seat is gone and nobody turns up for it.

So this asks the question from her side of the glass. Not "did a
fitness.booking row appear" - the placement tests already pin that -
but "does /my/schedule show it, with the same badge and the same Cancel
button as a class she chose herself".

Tested against the nightly job specifically. Placement at purchase runs
inside action_confirm with the buyer's own context; the job runs later,
unattended, from a cron. They are different callers and the second one
is the one nobody is watching.
"""

import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

#: index order matches date.weekday(), Monday first
WEEKDAY_CODES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def _text(html):
    """Visible text, so a failure names its own cause instead of dumping."""
    html = re.sub(r'(?s)<(script|style).*?</\1>', ' ', html)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


@tagged("post_install", "-at_install")
class TestNightlyPlacementsShowOnMySchedule(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        # fitness.trial_offer_end is deliberately NOT set here.
        #
        # Three other test classes close the trial offer that way and none
        # of them put it back. get_param is ormcache'd: the write
        # invalidates the cache, the rollback at class teardown restores
        # the row but does NOT invalidate it again, so '2000-01-01'
        # survives into whatever class runs next. Adding a fourth writer
        # tipped test_shop_trial_pending into failing its own fixture
        # guard - "Home is not offering the trial at all".
        #
        # Nothing here needs it. These assert on cancel-form URLs,
        # data-date and card counts; the trial banner adds no cards.

        cls.password = "nightly-schedule-pw-1"
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Nightly Schedule Student",
                "login": "nightly.schedule@example.invalid",
                "password": cls.password,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.user.partner_id

        cls.room = cls.env["fitness.classroom"].sudo().create({
            "name": "Nightly Room", "classroom_type": "reformer",
            "capacity": 6})
        cls.class_type = cls.env["fitness.class.type"].sudo().create({
            "name": "Nightly Reformer", "classroom_type": "reformer",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id})
        cls.plan = cls.env["sale.subscription.plan"].sudo().create({
            "name": "Nightly Trimestral",
            "billing_period_value": 3, "billing_period_unit": "month"})
        cls.product = cls.env["product.template"].sudo().create({
            "name": "Nightly Fixed Class 1", "type": "service",
            "list_price": 195.0, "sale_ok": True,
            "fitness_is_subscription_plan": True,
            "recurring_invoice": True,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group",
            "weekly_class_allowance": 1})
        cls.teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Nightly Teacher",
                "login": "nightly.teacher@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })

    # -- fixtures ----------------------------------------------------------

    def _schedule(self, horizon_weeks):
        """A real weekly schedule - the only thing that makes a recurrence.

        Placement finds a slot's other occurrences through recurrence_id.
        A hand-made calendar.event has none, so the job would place
        exactly one class and this test would pass having proved nothing.
        """
        anchor_day = fields.Date.context_today(self.env.user) + timedelta(
            days=2)
        sched = self.env["fitness.class.schedule"].sudo().create({
            "name": "Nightly weekly",
            "class_type_id": self.class_type.id,
            "classroom_id": self.room.id,
            # The weekday and the start date are DERIVED from today,
            # never written in. This used to say "tue" with date_start =
            # today. On a Tuesday the first occurrence was therefore today
            # at 08:00 studio time - 06:00 UTC - and My Schedule lists
            # only class_start > now, so from 06:00 UTC onward the booking
            # made at purchase dropped off the page and the cancel test
            # failed on its own fixture guard. Pinned at 01:00 UTC it
            # passed; at 12:00 and 23:30 it failed. It looked like a
            # regression on both shapes only because both runs fell
            # minutes the wrong side of 06:00, and it had passed the day
            # before because that day was a Monday.
            #
            # Two clear days ahead, so no hour of any day can put the
            # first occurrence behind now.
            "weekday": WEEKDAY_CODES[anchor_day.weekday()],
            "start_time": 8.0,
            "duration": 1.0,
            "date_start": anchor_day,
            "horizon_weeks": horizon_weeks,
            # teacher_user_id is NOT NULL on fitness.class.schedule. A
            # fixture without one does not fail an assertion, it fails the
            # INSERT, and every test in the class errors on setup.
            "teacher_user_id": self.teacher.id,
        })
        sched.action_generate()
        return sched

    def _occurrences(self, sched):
        return self.env["calendar.event"].sudo().search(
            [("recurrence_id", "=", sched.recurrence_id.id)], order="start")

    def _subscription(self, anchor):
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id, "plan_id": self.plan.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.product.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 195.0})
        order.action_confirm()
        self.env["fitness.clase.fija"].sudo().create({
            "subscription_id": order.id,
            "calendar_event_id": anchor.id})
        return order

    def _bookings(self, order):
        return self.env["fitness.booking"].sudo().search(
            [("subscription_id", "=", order.id)])

    def _schedule_html(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/studio?view=schedule")
        self.assertEqual(
            res.status_code, 200,
            "My Schedule did not load: %s" % _text(res.text)[:700])
        return res.text

    def _place_overnight(self):
        """Buy on a short timetable, extend it, then run the job.

        Split in two on purpose. The bookings that exist before the
        extension were made by action_confirm; everything that appears
        after it is the job's work, and only those are what this file is
        about.
        """
        sched = self._schedule(2)
        order = self._subscription(self._occurrences(sched)[0])
        order._fitness_place_slots()
        at_purchase = self._bookings(order)
        self.assertTrue(
            at_purchase, "nothing was placed at purchase; fixture wrong")

        sched.sudo().write({"horizon_weeks": 10})
        sched.sudo()._extend()
        self.env["sale.order"]._cron_place_fixed_classes()

        overnight = self._bookings(order) - at_purchase
        self.assertTrue(
            overnight,
            "the timetable grew by eight weeks and the nightly job placed "
            "nothing, so there is no overnight booking to look for on her "
            "schedule")
        return order, at_purchase, overnight

    # -- the question ------------------------------------------------------

    def test_a_class_booked_overnight_is_on_her_schedule(self):
        _order, _at_purchase, overnight = self._place_overnight()
        html = self._schedule_html()

        missing = [b for b in overnight
                   if "/my/classes/%d/cancel" % b.id not in html]
        self.assertFalse(
            missing,
            "%d of %d classes the nightly job booked for her are not on her "
            "own schedule page. She holds the seats and cannot see them."
            % (len(missing), len(overnight)))

    def test_an_overnight_class_offers_cancel_like_any_other(self):
        """Same badge, same button. Not a second-class booking."""
        _order, at_purchase, overnight = self._place_overnight()
        html = self._schedule_html()

        hers = "/my/classes/%d/cancel" % at_purchase[0].id
        overnight_one = "/my/classes/%d/cancel" % overnight[0].id
        self.assertIn(
            hers, html, "the booking made at purchase is missing too; this "
            "test would pass for the wrong reason")
        self.assertIn(
            overnight_one, html,
            "a class booked overnight has no Cancel form, so she cannot "
            "give it up the way she can give up any other class")

    def test_the_day_it_falls_on_is_shown(self):
        """A booking with no date on the page is a booking she cannot plan
        around - the card carries data-date, and the grouping reads it."""
        _order, _at_purchase, overnight = self._place_overnight()
        html = self._schedule_html()

        for booking in overnight:
            stamp = booking.calendar_event_id.start.strftime('%Y-%m-%d')
            self.assertIn(
                'data-date="%s"' % stamp, html,
                "the class on %s was booked overnight and her schedule "
                "shows no card for that day" % stamp)

    def test_every_class_she_holds_is_listed_once(self):
        """Not twice. The job runs nightly and must not duplicate a card."""
        order, _at_purchase, _overnight = self._place_overnight()
        self.env["sale.order"]._cron_place_fixed_classes()
        html = self._schedule_html()

        now = fields.Datetime.now()
        # The page lists future bookings only, so the count it is compared
        # against has to be the same set. An occurrence that has already
        # run is correctly absent from both.
        live = self._bookings(order).filtered(
            lambda b: b.state == "booked"
            and b.calendar_event_id.start > now)
        cards = html.count('class="mv-upcoming-card"')
        self.assertEqual(
            cards, len(live),
            "she holds %d classes and her schedule shows %d cards; a second "
            "run of the job changed what she sees" % (len(live), cards))
