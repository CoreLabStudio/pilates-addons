# -*- coding: utf-8 -*-
"""Auto-placement, and the two allowance pools on a combined plan.

The highest-value untested mechanism in the system. It runs on every
membership confirmation and every renewal, it creates real bookings against
real seats, and until now the only evidence it worked was a rehearsal
against a restore - which is not verification.

Both halves here would FAIL against the code as it stood before d9f1fe9:

  the combined-plan guard compared every active slot against one number, so
  one Barre slot plus one Reformer slot read as two against an allowance of
  one and the second was refused - a member could not have the two fixed
  classes she had just bought;

  and nothing anywhere asserted that a week of Barre bookings leaves the
  Reformer pool untouched.
"""

import datetime

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class ClaseFijaFixture(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.plan_month = cls.env.ref(
            "sale_subscription.subscription_plan_month")

        cls.barre_type = cls.env["fitness.class.type"].create({
            "name": "Fija Barre", "classroom_type": "barre",
            "duration": 50, "level": "all", "session_type": "group",
        })
        cls.reformer_type = cls.env["fitness.class.type"].create({
            "name": "Fija Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
        })

    def _student(self, suffix):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Fija %s" % suffix,
                "login": "fija.%s@example.invalid" % suffix,
                "email": "fija.%s@example.invalid" % suffix,
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        user.partner_id.write({"email": user.login})
        return user.partner_id

    def _weekly_series(self, class_type, weeks=8, hour=17, weekday_offset=1,
                       capacity=8, name=None):
        """One class a week at the same time, the shape a fixed slot books.

        Built as plain events sharing a recurrence so placement's
        recurrence_id branch is the one exercised - that is the branch a real
        timetable uses, and the id-only branch would book exactly one class
        and quietly look like it worked.
        """
        # rrule_type=False deliberately. It defaults to 'weekly', and
        # flushing then computes rrule, which raises "You have to choose at
        # least one day in the week" on a recurrence with no weekday set -
        # not where these tests are, and nowhere near what they are about.
        # The events are written directly; the recurrence exists only so
        # placement's recurrence_id branch is the one exercised, because the
        # id-only branch books a single class and looks like success.
        recurrence = self.env["calendar.recurrence"].create(
            {"rrule_type": False})
        start = (fields.Datetime.now() + datetime.timedelta(
            days=weekday_offset)).replace(
                hour=hour, minute=0, second=0, microsecond=0)
        events = self.env["calendar.event"]
        for n in range(weeks):
            when = start + datetime.timedelta(weeks=n)
            events |= self.env["calendar.event"].create({
                "name": name or ("%s w%s" % (class_type.name, n)),
                "start": when,
                "stop": when + datetime.timedelta(minutes=50),
                "class_type_id": class_type.id,
                "is_fitness_class": True,
                "capacity": capacity,
                "recurrence_id": recurrence.id,
            })
        return events

    def _membership(self, partner, product, months=2):
        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id,
            "plan_id": self.plan_month.id,
        })
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": product.list_price,
        })
        order.action_confirm()
        # A period long enough that "the whole period" means more than one
        # week - otherwise every assertion below passes on a single booking.
        today = fields.Date.context_today(partner)
        order.write({
            "start_date": today,
            "next_invoice_date": today + datetime.timedelta(weeks=8),
        })
        return order

    def _slot(self, order, anchor):
        return self.env["fitness.clase.fija"].sudo().create({
            "subscription_id": order.id,
            "calendar_event_id": anchor.id,
        })


@tagged("post_install", "-at_install")
class TestAutoPlacementCoversThePeriod(ClaseFijaFixture):
    """3.3 - a fixed slot books every week she paid for, not just the first."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.single = cls.env["product.template"].create({
            "name": "Fija Barre Weekly", "list_price": 65.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "barre", "fitness_session_type": "group",
            "weekly_class_allowance": 1,
        })

    def test_every_week_in_the_period_is_booked(self):
        partner = self._student("period")
        events = self._weekly_series(self.barre_type, weeks=8)
        order = self._membership(partner, self.single)
        self._slot(order, events[0])

        placed = order._auto_place_clase_fija()

        booked = self.env["fitness.booking"].sudo().search([
            ("student_id", "=", partner.id),
            ("state", "=", "booked"),
        ])
        self.assertEqual(
            placed, len(booked),
            "the count it reported does not match what it created")
        self.assertGreater(
            len(booked), 1,
            "only one class was booked - a membership pays for a period, not "
            "a single week, and booking the anchor alone looks like success")
        self.assertEqual(
            len(booked), len(events),
            "she paid for %s weeks and holds %s booking(s)"
            % (len(events), len(booked)))

    def test_it_books_that_slot_and_not_some_other_class(self):
        """A second series at a different time must not be swept in."""
        partner = self._student("targeted")
        mine = self._weekly_series(self.barre_type, weeks=4, hour=17)
        other = self._weekly_series(self.barre_type, weeks=4, hour=9)
        order = self._membership(partner, self.single)
        self._slot(order, mine[0])

        order._auto_place_clase_fija()

        booked_events = self.env["fitness.booking"].sudo().search(
            [("student_id", "=", partner.id)]).mapped("calendar_event_id")
        self.assertTrue(
            all(e in mine for e in booked_events),
            "placement booked a class outside the slot she chose")
        self.assertFalse(
            any(e in other for e in booked_events),
            "the 9am series was booked as well - the student would arrive "
            "at a class she never asked for")

    def test_running_it_twice_does_not_double_book(self):
        """Idempotent, because it runs again on every renewal."""
        partner = self._student("twice")
        self._weekly_series(self.barre_type, weeks=4)
        order = self._membership(partner, self.single)
        self._slot(order, order.fitness_clase_fija_ids[:1].calendar_event_id
                   if order.fitness_clase_fija_ids
                   else self.env["calendar.event"].search(
                       [("class_type_id", "=", self.barre_type.id)],
                       order="start asc", limit=1))

        first = order._auto_place_clase_fija()
        second = order._auto_place_clase_fija()

        self.assertGreater(first, 0)
        self.assertEqual(
            second, 0,
            "a second run booked %s more - a renewal would double every "
            "week of her membership" % second)

    def test_a_week_she_cancelled_is_not_silently_rebooked(self):
        """She cancelled that week on purpose. A renewal must not undo it."""
        partner = self._student("cancelled")
        self._weekly_series(self.barre_type, weeks=4)
        order = self._membership(partner, self.single)
        anchor = self.env["calendar.event"].search(
            [("class_type_id", "=", self.barre_type.id)],
            order="start asc", limit=1)
        self._slot(order, anchor)
        order._auto_place_clase_fija()

        one = self.env["fitness.booking"].sudo().search(
            [("student_id", "=", partner.id)], order="id desc", limit=1)
        target = one.calendar_event_id
        one.write({"state": "cancelled"})

        order._auto_place_clase_fija()

        again = self.env["fitness.booking"].sudo().search_count([
            ("student_id", "=", partner.id),
            ("calendar_event_id", "=", target.id),
            ("state", "=", "booked"),
        ])
        self.assertEqual(
            again, 0,
            "the week she cancelled was booked again behind her")


@tagged("post_install", "-at_install")
class TestCombinedPlanKeepsTwoPools(ClaseFijaFixture):
    """3.4 - Barre and Reformer are counted separately, never traded.

    This is Eli's plan. Before d9f1fe9 the guard compared every active slot
    against one number, so her second slot was refused outright.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.combined = cls.env["product.template"].create({
            "name": "Fija 1 Barre + 1 Reformer", "list_price": 145.0,
            "type": "service", "sale_ok": True,
            "fitness_is_subscription_plan": True, "recurring_invoice": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": 1,
            "fitness_secondary_class_type": "reformer",
            "fitness_secondary_weekly_allowance": 1,
        })

    def test_she_can_hold_one_slot_in_each_discipline(self):
        """The bug, stated plainly: she bought two classes a week and the
        second slot was refused."""
        partner = self._student("combined")
        barre = self._weekly_series(self.barre_type, weeks=4, hour=17)
        reformer = self._weekly_series(
            self.reformer_type, weeks=4, hour=19, weekday_offset=3)
        order = self._membership(partner, self.combined)

        self._slot(order, barre[0])
        self._slot(order, reformer[0])   # refused before d9f1fe9

        self.assertEqual(
            len(order.fitness_clase_fija_ids.filtered("active")), 2,
            "a combined plan could not hold its two fixed slots")

    def test_a_second_slot_in_the_same_discipline_is_still_refused(self):
        """The guard must still guard. Relaxing it per discipline is not
        the same as switching it off."""
        partner = self._student("same_disc")
        barre_a = self._weekly_series(self.barre_type, weeks=4, hour=17)
        barre_b = self._weekly_series(self.barre_type, weeks=4, hour=9)
        order = self._membership(partner, self.combined)
        self._slot(order, barre_a[0])

        with self.assertRaises(ValidationError):
            self._slot(order, barre_b[0])

    def test_each_discipline_reports_its_own_allowance(self):
        partner = self._student("alloc")
        order = self._membership(partner, self.combined)
        self.assertEqual(
            order.fitness_effective_weekly_allowance(discipline="barre"), 1)
        self.assertEqual(
            order.fitness_effective_weekly_allowance(discipline="reformer"), 1)

    def test_booking_barre_does_not_spend_the_reformer_allowance(self):
        """The pools must not be added together anywhere."""
        partner = self._student("pools")
        barre = self._weekly_series(self.barre_type, weeks=2, hour=17)
        reformer = self._weekly_series(
            self.reformer_type, weeks=2, hour=19, weekday_offset=3)
        order = self._membership(partner, self.combined)
        self._slot(order, barre[0])
        self._slot(order, reformer[0])
        order._auto_place_clase_fija()

        when = barre[0].start
        used_barre = order.fitness_weekly_used_count(when, discipline="barre")
        used_reformer = order.fitness_weekly_used_count(
            when, discipline="reformer")

        self.assertEqual(
            used_barre, 1,
            "her Barre week does not show the Barre class she is booked into")
        self.assertEqual(
            used_reformer, 1,
            "her Reformer week should count her Reformer class and nothing "
            "else - counting Barre here is how a cancelled Barre class eats "
            "her Reformer allowance")

    def test_placement_books_both_disciplines_across_the_period(self):
        """End to end, the shape Eli actually bought."""
        partner = self._student("eli_shape")
        barre = self._weekly_series(self.barre_type, weeks=6, hour=17)
        reformer = self._weekly_series(
            self.reformer_type, weeks=6, hour=19, weekday_offset=3)
        order = self._membership(partner, self.combined)
        self._slot(order, barre[0])
        self._slot(order, reformer[0])

        order._auto_place_clase_fija()

        # One entry per booking. mapped() through a relation returns the
        # union of the related records first, so twelve bookings across two
        # class types collapse to two values and every count reads 1.
        rooms = [b.calendar_event_id.class_type_id.classroom_type
                 for b in self.env["fitness.booking"].sudo().search(
                     [("student_id", "=", partner.id)])]
        self.assertIn("barre", rooms, "no Barre class was placed")
        self.assertIn("reformer", rooms, "no Reformer class was placed")
        self.assertEqual(
            rooms.count("barre"), len(barre),
            "she is short of Barre classes for the period")
        self.assertEqual(
            rooms.count("reformer"), len(reformer),
            "she is short of Reformer classes for the period")
