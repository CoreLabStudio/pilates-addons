# -*- coding: utf-8 -*-
"""A late cancellation has to be visible, to the desk and to her.

Nothing notifies a manager when a student cancels inside the window: the
student simply stops appearing, and the credit quietly stays spent. And
her own history said either "Credit returned" or nothing at all, where
nothing is precisely the case she rings the studio about.

So: a label on the Roster and on the booking, a filter to go looking
with, and all three outcomes named in her history. These tests hold the
label to the FACTS it claims - a label that says "credit kept" about a
booking whose credit came back is worse than no label, because the desk
would act on it.
"""
import re

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.fitness_bookings.tests.test_student_may_cancel_late import (
    LateCancelFixture,
)


@tagged("post_install", "-at_install")
class TestALateCancellationIsVisible(LateCancelFixture):

    def _cancel(self, hours_before, tag):
        user = self._student(tag)
        line = self._packline(user)
        booking = self._book(user, self._class(hours_before))
        booking.with_user(user).action_cancel()
        return user, line, booking

    # == the label says what actually happened =======================
    def test_a_late_cancellation_says_the_credit_was_kept(self):
        _u, _l, booking = self._cancel(self.window - 2, "lbllate")
        self.assertTrue(booking.fitness_is_late_cancel)
        self.assertEqual(
            booking.fitness_cancel_label, "Cancelled late, credit kept")

    def test_a_cancellation_in_good_time_gets_no_label(self):
        """The Roster column is for the exceptions. A label on every
        ordinary cancellation is a column nobody reads."""
        _u, _l, booking = self._cancel(self.window + 4, "lblgood")
        self.assertTrue(booking.credit_returned)
        self.assertFalse(booking.fitness_is_late_cancel)
        self.assertEqual(booking.fitness_cancel_label, "")

    def test_a_live_booking_gets_no_label(self):
        user = self._student("lbllive")
        self._packline(user)
        booking = self._book(user, self._class(self.window + 10))
        self.assertFalse(booking.fitness_is_late_cancel)
        self.assertEqual(booking.fitness_cancel_label, "")

    def test_the_label_changes_when_the_studio_gives_it_back(self):
        """The whole point of computing it: it cannot drift from the two
        fields it describes."""
        _u, _l, booking = self._cancel(self.window - 2, "lblback")
        self.assertEqual(
            booking.fitness_cancel_label, "Cancelled late, credit kept")

        booking.with_user(self._manager())._give_credit_back("She was ill.")

        self.assertEqual(
            booking.fitness_cancel_label,
            "Cancelled late, credit given back",
            "the label still says the credit was kept after the studio gave "
            "it back, so the desk would give it back a second time")
        self.assertTrue(
            booking.fitness_is_late_cancel,
            "it stopped counting as a late cancellation once forgiven, so "
            "the figures lose it")

    def test_a_no_show_is_not_a_late_cancellation(self):
        """Both forfeit, and they are different things. A no-show never
        told the studio anything; a late cancellation at least freed the
        seat, and the label must not blur them."""
        user = self._student("lblnoshow")
        self._packline(user)
        booking = self._book(user, self._class(self.window + 10))
        booking.sudo().write({"state": "no_show"})
        self.assertFalse(booking.fitness_is_late_cancel)
        self.assertEqual(booking.fitness_cancel_label, "")

    # == the filter finds them, and only them ========================
    def test_the_filter_finds_the_late_ones(self):
        _u, _l, late = self._cancel(self.window - 2, "fltlate")
        _u2, _l2, good = self._cancel(self.window + 4, "fltgood")
        user3 = self._student("fltlive")
        self._packline(user3)
        live = self._book(user3, self._class(self.window + 10))

        Booking = self.env["fitness.booking"].sudo()
        found = Booking.search([("fitness_is_late_cancel", "=", True)])

        self.assertIn(late, found)
        self.assertNotIn(
            good, found,
            "a cancellation in good time shows up under Cancelled Late, so "
            "the desk is handed a list it has to re-check by hand")
        self.assertNotIn(live, found)

    def test_the_filter_inverts(self):
        """= False must mean every other booking, not an empty list. A
        half-working search is how a report quietly loses rows."""
        _u, _l, late = self._cancel(self.window - 2, "invlate")
        _u2, _l2, good = self._cancel(self.window + 4, "invgood")

        Booking = self.env["fitness.booking"].sudo()
        not_late = Booking.search([("fitness_is_late_cancel", "=", False)])

        self.assertIn(good, not_late)
        self.assertNotIn(late, not_late)

    def test_the_two_halves_of_the_filter_partition_the_table(self):
        """Every booking is on exactly one side. Together they must add up
        to the whole table, or something falls between them."""
        self._cancel(self.window - 2, "partlate")
        self._cancel(self.window + 4, "partgood")
        Booking = self.env["fitness.booking"].sudo()
        total = Booking.search_count([])
        yes = Booking.search_count([("fitness_is_late_cancel", "=", True)])
        no = Booking.search_count([("fitness_is_late_cancel", "=", False)])
        self.assertEqual(
            yes + no, total,
            "%d bookings are on neither side of the filter" % (
                total - yes - no))

    def test_an_unsupported_operator_is_refused_not_ignored(self):
        """A search that silently returns everything is a report that
        silently lies.

        Called directly rather than through search(): the ORM rejects
        'like' on a boolean while optimising the domain, so it never
        reaches the method. The guard is for the operators that DO reach
        it, and asserting through search() would be asserting Odoo.
        """
        Booking = self.env["fitness.booking"].sudo()
        with self.assertRaises(UserError):
            Booking._search_fitness_is_late_cancel("like", "yes")
        # The two it does honour, so the guard cannot be over-tight.
        self.assertTrue(Booking._search_fitness_is_late_cancel("=", True))
        self.assertTrue(Booking._search_fitness_is_late_cancel("!=", True))

    # == the screens that show it ====================================
    def test_the_roster_shows_the_label(self):
        view = self.env.ref(
            "fitness_bookings.view_calendar_event_form_roster")
        self.assertIn(
            "fitness_cancel_label", view.arch,
            "the Roster does not show the label, so the one screen a "
            "manager opens after a class still does not say what happened "
            "to the credit")

    def test_the_search_view_offers_both_filters(self):
        view = self.env.ref("fitness_bookings.view_fitness_booking_search")
        self.assertIn('name="filter_late_cancel"', view.arch)
        self.assertIn('name="filter_credit_given_back"', view.arch)

    def test_the_roster_does_not_relabel_the_column_in_its_arch(self):
        """One binding, so one translation.

        A string= in the arch is a SECOND msgid, bound to that view, and a
        view term is translated per view - which is how the same words end
        up translated on one screen and English on the next. The field's
        own label is translated once.
        """
        field = self.env["ir.model.fields"].sudo().search([
            ("model", "=", "fitness.booking"),
            ("name", "=", "fitness_cancel_label")], limit=1)
        self.assertTrue(field)
        self.assertEqual(field.field_description, "Cancellation")
        view = self.env.ref(
            "fitness_bookings.view_calendar_event_form_roster")
        tag = re.search(r'<field name="fitness_cancel_label"[^>]*>', view.arch)
        self.assertTrue(tag, "the label is not on the Roster at all")
        self.assertNotIn(
            "string=", tag.group(0),
            "the Roster relabels the column in its arch, so the header is a "
            "second msgid bound to this view and needs a translation nobody "
            "will remember to write: %s" % tag.group(0))
