# -*- coding: utf-8 -*-
"""The free trial ends at the end of 16 October in Barcelona.

Not at the end of 16 October wherever each student's account happens to
think it is. _trial_offer_open compared fields.Date.context_today(self),
which answers in the READER's timezone and falls back to UTC when she
has none, so on production one deadline was spread across five and a
half hours:

    131 students on Europe/Madrid   offer ended 16 Oct 24:00 Madrid
      7 students with no timezone   offer ended 17 Oct 02:00 Madrid
      3 students on Asia/Calcutta   offer ended 16 Oct 20:30 Madrid

The same offer, three different endings, decided by a field nobody ever
filled in. Eli, who is on Asia/Calcutta, would have lost it three and a
half hours before a student standing next to her in the studio.

Every test pins the clock with Odoo's freeze_time started in setUp and
stopped by addCleanup, never a run() override.
"""
from datetime import date, datetime

import pytz

from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
OFFER_END = '2026-10-16'


def _utc(local_naive):
    """A Madrid wall clock reading, as the naive UTC the database holds."""
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class _AtMadridTime(TransactionCase):
    """Pins the clock to a Madrid wall clock time."""

    PINNED = datetime(2026, 10, 16, 23, 30)

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(_utc(self.PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', OFFER_END)
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        self.TR = self.env['fitness.trial.request'].sudo()

    def _as(self, tz):
        """The same question asked by a student carrying this timezone."""
        user = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'TZ Student %s' % (tz or 'blank'),
                'login': 'tz.%s@example.invalid'
                         % (tz or 'blank').replace('/', '.').lower(),
                'tz': tz or False,
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        return self.env['fitness.trial.request'].with_user(user).sudo()


@tagged("post_install", "-at_install")
class TestTheLastEveningOfTheOffer(_AtMadridTime):
    """16 October, 23:30 in Barcelona. Still open, for everybody."""

    longMessage = False
    PINNED = datetime(2026, 10, 16, 23, 30)

    def test_the_offer_is_open(self):
        self.assertTrue(self.TR._trial_offer_open(),
                        "the offer closed before the day was out")

    def test_it_is_open_for_a_student_with_no_timezone(self):
        self.assertTrue(
            self._as(None)._trial_offer_open(),
            "a student with no timezone set is seeing a different deadline")

    def test_it_is_open_for_a_student_in_india(self):
        """Asia/Calcutta is UTC+5:30: it is already the 17th for her.

        She is the one this fixes. On the old rule the offer had ended
        for her three and a half hours earlier.
        """
        self.assertTrue(
            self._as('Asia/Calcutta')._trial_offer_open(),
            "the offer ended early for a student on an eastern timezone")

    def test_it_is_open_for_a_student_in_madrid(self):
        self.assertTrue(self._as('Europe/Madrid')._trial_offer_open())


@tagged("post_install", "-at_install")
class TestJustAfterMidnightInBarcelona(_AtMadridTime):
    """17 October, 00:30 in Barcelona. Closed, for everybody."""

    longMessage = False
    PINNED = datetime(2026, 10, 17, 0, 30)

    def test_the_offer_is_closed(self):
        self.assertFalse(self.TR._trial_offer_open(),
                         "the offer is still open after the day it ends")

    def test_it_is_closed_for_a_student_with_no_timezone(self):
        """It is still 22:30 UTC on the 16th for her.

        This is the two-hour leak: seven accounts on production carry no
        timezone, and every one of them could still claim a free trial
        after it had ended for everyone else.
        """
        self.assertFalse(
            self._as(None)._trial_offer_open(),
            "a student with no timezone can still claim the free trial")

    def test_it_is_closed_for_a_student_in_lisbon(self):
        """Europe/Lisbon is an hour behind Madrid - still the 16th there."""
        self.assertFalse(
            self._as('Europe/Lisbon')._trial_offer_open(),
            "a student an hour west can still claim the free trial")

    def test_it_is_closed_for_a_student_in_madrid(self):
        self.assertFalse(self._as('Europe/Madrid')._trial_offer_open())


@tagged("post_install", "-at_install")
class TestThePromotionAgreesWithTheOffer(_AtMadridTime):
    """The price and the gate must not disagree.

    They are two different pieces of code answering the same question.
    If one says free and the other charges, a student is shown a price
    the next screen refuses.
    """

    longMessage = False
    PINNED = datetime(2026, 10, 17, 0, 30)

    def _trial_products(self):
        prods = self.env['fitness.trial.request'].sudo(
            )._all_trial_products()
        if not prods:
            self.fail("no trial products on this database")
        return prods

    def test_the_promotion_is_over_too(self):
        for prod in self._trial_products():
            prod.sudo().write({'fitness_promo_end': OFFER_END,
                               'fitness_promo_mode': 'free'})
            self.assertFalse(
                prod.sudo()._fitness_promo_window_open(),
                "%s is still promoting after the offer ended" % prod.name)

    def test_the_price_is_the_list_price_again(self):
        for prod in self._trial_products():
            prod.sudo().write({'fitness_promo_end': OFFER_END,
                               'fitness_promo_mode': 'free',
                               'list_price': 12.0})
            self.assertAlmostEqual(
                prod.sudo().fitness_effective_price(), 12.0, places=2,
                msg="%s is still free after the offer ended" % prod.name)

    def test_a_student_in_india_is_not_charged_early(self):
        """The mirror of the gate test: on the last evening the price
        must still be zero for her, not just the gate open."""
        freezer = common.freeze_time(_utc(datetime(2026, 10, 16, 23, 30)))
        freezer.start()
        self.addCleanup(freezer.stop)
        for prod in self._trial_products():
            prod.sudo().write({'fitness_promo_end': OFFER_END,
                               'fitness_promo_mode': 'free'})
            self.assertAlmostEqual(
                prod.sudo().with_context(
                    tz='Asia/Calcutta').fitness_effective_price(),
                0.0, places=2,
                msg="%s charges a student on an eastern timezone while the "
                    "offer is still running" % prod.name)


@tagged("post_install", "-at_install")
class TestTheHelperItself(TransactionCase):
    """studio_today() answers in Barcelona, whoever asks."""

    longMessage = False

    def test_it_ignores_the_readers_timezone(self):
        from odoo.addons.fitness_core.models.studio_time import studio_today
        freezer = common.freeze_time(_utc(datetime(2026, 10, 16, 23, 30)))
        freezer.start()
        self.addCleanup(freezer.stop)
        # 23:30 Madrid on the 16th is already 03:00 on the 17th in India
        # and still 21:30 on the 16th in UTC. The answer is the 16th.
        self.assertEqual(studio_today(), date(2026, 10, 16))

    def test_it_follows_the_clock_change(self):
        """26 October is CET; the stored UTC instant is an hour earlier."""
        from odoo.addons.fitness_core.models.studio_time import studio_today
        freezer = common.freeze_time(_utc(datetime(2026, 10, 26, 0, 30)))
        freezer.start()
        self.addCleanup(freezer.stop)
        self.assertEqual(studio_today(), date(2026, 10, 26))
