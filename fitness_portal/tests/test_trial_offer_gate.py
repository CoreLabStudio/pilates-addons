# -*- coding: utf-8 -*-
"""One answer to "is the free trial still claimable?", not two.

fitness_portal carried a hardcoded TRIAL_OFFER_END_DEFAULT of
'2026-09-30' and fell back to it whenever the parameter was unset.
fitness_trials read the same parameter with no fallback at all. So on
any database where nobody had set it - a fresh install, a rebuilt
staging, every odoo.sh test build - the two modules answered the same
question differently about the same studio on the same day.

On 1 October 2026 the hardcoded date passed and it stopped being
theoretical. Production had the parameter cleared, which looked like
"no deadline" and meant 30 September: the trial was shut in the app
while both products were free until 16 October and the website was
advertising exactly that.

UNSET MEANS OPEN. That is not new - the portal's own gate already read
`if not end: return True`, and fitness_trials already behaved that way.
The constant was overriding both.

Both halves are pinned here: a database with nothing set behaves
identically in both modules, and a database with a real date behaves
exactly as it does today.
"""

from datetime import date

from odoo.tests import TransactionCase, freeze_time, tagged

from odoo.addons.fitness_core.models.studio_time import studio_today

PARAM = 'fitness.trial_offer_end'

#: 00:30 in Madrid, 23:30 UTC on the day before.
#:
#: The deadline is a calendar date and the gate compares it with
#: studio_today(), so the only hour in which "which date is it" has two
#: answers is the one pinned here. Running unpinned, the boundary test
#: below agreed with the gate for 23 hours a day and disagreed for the
#: other one, which is the shape of fault that gets rerun and shrugged at
#: rather than read.
PINNED_UTC = '2026-11-09 23:30:00'
PINNED_MADRID_DATE = date(2026, 11, 10)
PINNED_UTC_DATE = date(2026, 11, 9)


@tagged("post_install", "-at_install")
@freeze_time(PINNED_UTC)
class TestTrialOfferGate(TransactionCase):

    longMessage = False

    def _set(self, value):
        self.env['ir.config_parameter'].sudo().set_param(PARAM, value)

    def _model(self):
        return self.env['fitness.trial.request'].sudo()

    def _open(self):
        return self._model()._trial_offer_open()

    def _end(self):
        return self._model()._trial_offer_end()

    # -- nothing set -------------------------------------------------------

    def test_unset_means_no_deadline(self):
        self._set(False)
        self.assertIsNone(
            self._end(),
            "an unset parameter produced a deadline out of nowhere - which "
            "is how a hardcoded 30 September closed the offer on every "
            "database nobody had configured")

    def test_unset_means_the_offer_is_open(self):
        self._set(False)
        self.assertTrue(
            self._open(),
            "the trial is closed on a database where the studio has set no "
            "deadline at all")

    def test_blank_is_the_same_as_unset(self):
        """A cleared field and an absent one are one state, not two."""
        self._set('')
        self.assertIsNone(self._end(), "a blank value invented a deadline")
        self.assertTrue(self._open(), "a blank value closed the offer")

    def test_whitespace_is_the_same_as_unset(self):
        self._set('   ')
        self.assertTrue(
            self._open(), "a field containing spaces closed the offer")

    # -- a real date -------------------------------------------------------

    def test_a_future_date_leaves_it_open(self):
        self._set('2099-12-31')
        self.assertTrue(
            self._open(), "a deadline decades away is closing the offer")
        self.assertEqual(str(self._end()), '2099-12-31')

    def test_a_past_date_closes_it(self):
        self._set('2000-01-01')
        self.assertFalse(
            self._open(),
            "a deadline in the past is not closing the offer, so the "
            "parameter does nothing")

    def test_today_is_still_open(self):
        """The boundary. `<=`, so the last day counts as open."""
        self._set(str(studio_today()))
        self.assertTrue(
            self._open(),
            "the offer closed on its own last day - a student on the final "
            "day is told she has missed it")

    def test_the_last_day_is_the_studios_day_not_the_readers(self):
        """Who is asking must not change when the offer ends.

        At the pinned instant it is already the 10th in Barcelona and
        still the 9th in UTC. A deadline of the 9th has therefore passed
        and a deadline of the 10th has not - whoever is reading, and
        whatever timezone her account carries, which for most portal
        accounts is none at all.
        """
        self._set(PINNED_UTC_DATE.isoformat())
        self.assertFalse(
            self._open(),
            "a deadline that is yesterday in Barcelona is still letting "
            "students claim the trial, because the gate is reading the UTC "
            "date rather than the studio's")

        self._set(PINNED_MADRID_DATE.isoformat())
        self.assertTrue(
            self._open(),
            "the offer's own last day in Barcelona is already closed, which "
            "is the gate reading a date that has not arrived there yet")

    def test_the_clock_is_pinned_and_the_two_dates_differ(self):
        """The test above means nothing unless both halves hold."""
        from odoo import fields as odoo_fields
        self.assertEqual(
            studio_today(), PINNED_MADRID_DATE,
            "the clock is not pinned, so the boundary tests are reading "
            "whatever date the suite happens to run on")
        self.assertEqual(
            odoo_fields.Date.today(), PINNED_UTC_DATE,
            "the pinned instant no longer straddles midnight in Madrid, so "
            "the two dates are the same and nothing above discriminates")

    # -- a value nobody can read -------------------------------------------

    def test_a_malformed_date_does_not_raise(self):
        """It is read on the shop page. Raising there is a 500."""
        self._set('not-a-date')
        try:
            self._open()
        except Exception as exc:                        # noqa: BLE001
            self.fail("a typo in the parameter raised %s: %s"
                      % (type(exc).__name__, exc))

    def test_a_malformed_date_leaves_the_offer_open(self):
        """Loud in the log, open in the shop.

        Deliberate, and the quieter of two bad options: treating an
        unreadable value as a closure lets one typo shut the whole funnel
        with nothing on screen to say why - which is the fault this file
        exists about.
        """
        self._set('16/10/2026')
        self.assertTrue(
            self._open(),
            "a date typed in the wrong format closed the trial offer")

    # -- the two modules give one answer ------------------------------------

    def test_the_portal_asks_the_same_question_as_the_model(self):
        """Not "they agree" - there is only one implementation now.

        fitness_portal's controller delegates to this model, so the test
        is that the delegation exists and answers the same way in both
        directions, rather than two code paths that happen to match today.
        """
        from odoo.addons.fitness_portal.controllers.portal import (
            FitnessStudentPortal,
        )
        self.assertFalse(
            hasattr(FitnessStudentPortal, 'TRIAL_OFFER_END_DEFAULT'),
            "the hardcoded fallback is back on the controller; an unset "
            "parameter will close the offer again the day that date passes")

        for value, expected in (('2099-12-31', True),
                                ('2000-01-01', False),
                                (False, True)):
            self._set(value)
            self.assertEqual(
                self._open(), expected,
                "the shared gate answered %r for %r" % (self._open(), value))

    def test_fitness_trials_reads_the_parameter_through_the_model(self):
        """It used to parse the parameter itself, in its own controller."""
        import inspect
        from odoo.addons.fitness_trials.controllers import trial as trial_ctl
        source = inspect.getsource(trial_ctl)
        self.assertNotIn(
            "get_param(\n            'fitness.trial_offer_end')", source,
            "fitness_trials is parsing the parameter again instead of "
            "asking the model, which is how the two came to disagree")
        self.assertIn(
            "_trial_offer_end()", source,
            "fitness_trials no longer consults the offer deadline at all")
