# -*- coding: utf-8 -*-
"""The dashboard's classes card: a week view, and a count worth reading.

Parts H and I. The card only ever showed today, and made you count. The seats
column already read "2/8" and is deliberately left alone.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDashboardClassesCard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Card Barre",
            "classroom_type": "barre",
            "duration": 45,
            "level": "all",
            "session_type": "group",
        })

    def _bounds(self, span="today"):
        """The window the card is actually looking at, in naive UTC.

        Asked of the model rather than computed from the clock: the studio is
        in Madrid, so "two hours from now" run late in the evening lands after
        midnight local and is tomorrow - which is how the first version of
        these tests failed for a reason that had nothing to do with the card.
        """
        dash = self.env["fitness.admin.dashboard"].create({"classes_range": span})
        return dash._range_bounds()

    def _event_at(self, start, name="Card class"):
        return self.env["calendar.event"].create({
            "name": name,
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
            "capacity": 8,
        })

    def _event_today(self, name="Card class"):
        start, _end, _d = self._bounds("today")
        return self._event_at(start + timedelta(hours=10), name)

    def _event_later_this_week(self, name="Later this week"):
        _start, end, _d = self._bounds("today")
        return self._event_at(end + timedelta(hours=10), name)

    def _card(self, span="today"):
        dash = self.env["fitness.admin.dashboard"].create({"classes_range": span})
        return dash, dash.preview_classes_html or ""

    def test_the_card_opens_on_today(self):
        dash, _html = self._card()
        self.assertEqual(dash.classes_range, "today")

    def test_the_card_counts_what_it_shows(self):
        """PART I - a sentence, not a column to add up."""
        self._event_today("Later today")
        _dash, html = self._card()
        self.assertIn(
            "across", html,
            "the card should say how many students and how many classes",
        )

    def test_the_week_view_reaches_past_today(self):
        """PART H - the studio plans in weeks."""
        self._event_later_this_week("Three days out")
        _d1, today_html = self._card("today")
        _d2, week_html = self._card("week")
        self.assertNotIn("Three days out", today_html)
        self.assertIn(
            "Three days out", week_html,
            "a class three days away belongs in the week view and not in today",
        )

    def test_the_week_view_names_the_day(self):
        """A time alone does not identify a class once the range spans days."""
        self._event_later_this_week()
        _d1, today_html = self._card("today")
        _d2, week_html = self._card("week")
        self.assertNotIn("<th>Day</th>", today_html)
        self.assertIn("<th>Day</th>", week_html)

    def test_seats_are_still_shown_as_booked_over_capacity(self):
        """Left exactly as it was - it already read 2/8."""
        self._event_today()
        _dash, html = self._card()
        self.assertIn("0/8", html)

    def test_see_all_follows_the_range(self):
        dash, _html = self._card("week")
        action = dash.action_view_today_classes()
        start = action["domain"][1][2]
        end = action["domain"][2][2]
        self.assertGreater(
            (end - start).days, 1,
            "See all should open on the span the card is describing",
        )

    def test_a_cancelled_class_is_not_counted(self):
        """The summary is what the studio reads to decide if a day is worth
        running, so counting classes that are already off overstates it."""
        event = self._event_today("Off today")
        event.class_state = "cancelled"
        _dash, html = self._card()
        self.assertIn("0 students booked across 0 classes", html)
