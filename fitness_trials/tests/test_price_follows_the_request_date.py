# -*- coding: utf-8 -*-
"""She asked while it was free, so she is not charged for the delay.

A student asks for a trial on the 15th. The studio gets to her on the
18th, two days after the offer closed. Approving her then raised an
order at the list price - she was billed for the thing she had been
offered free, because the studio was slow.

PRICE_FOLLOWS_REQUEST_DATE is the whole rule, and it is a flag so it can
be turned off in one place if the owner decides the other way.

The clock is pinned with Odoo's freeze_time in setUp, released by
addCleanup.
"""
from datetime import datetime

import pytz

from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
OFFER_END = '2026-10-16'


def _utc(local_naive):
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class _TrialPricing(TransactionCase):

    PINNED = datetime(2026, 10, 15, 12, 0)

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
        prods = self.TR._all_trial_products()
        if not prods:
            self.fail("no trial products on this database")
        self.product = prods[0]
        self.product.sudo().write({
            'fitness_promo_mode': 'free',
            'fitness_promo_end': OFFER_END,
            'list_price': 12.0,
        })

    def _request_made_at(self, local_naive):
        """A request whose create_date is a given Madrid moment."""
        req = self.TR.create({
            'name': 'Pricing Student',
            'email': 'pricing.student@example.invalid',
        })
        # create_date is readonly and the ORM will not take it, so it
        # goes straight to the column - the same reason the stale
        # payment test had to.
        self.env.cr.execute(
            "UPDATE fitness_trial_request SET create_date = %s WHERE id = %s",
            (_utc(local_naive), req.id))
        req.invalidate_recordset(['create_date'])
        return req


@tagged("post_install", "-at_install")
class TestAskedWhileItWasFree(_TrialPricing):
    """Approved after the deadline, asked before it."""

    longMessage = False
    PINNED = datetime(2026, 10, 17, 0, 30)

    def test_the_price_date_is_the_day_she_asked(self):
        req = self._request_made_at(datetime(2026, 10, 15, 12, 0))
        self.assertEqual(str(req._price_date()), '2026-10-15')

    def test_she_is_still_charged_nothing(self):
        req = self._request_made_at(datetime(2026, 10, 15, 12, 0))
        self.assertAlmostEqual(
            self.product.sudo().fitness_effective_price(
                on=req._price_date()), 0.0, places=2,
            msg="she asked while it was free and is being charged for the "
                "studio's delay in answering")

    def test_asking_on_the_last_evening_still_counts(self):
        """23:30 Madrid on the 16th is already the 17th in UTC."""
        req = self._request_made_at(datetime(2026, 10, 16, 23, 30))
        self.assertEqual(str(req._price_date()), '2026-10-16')
        self.assertAlmostEqual(
            self.product.sudo().fitness_effective_price(
                on=req._price_date()), 0.0, places=2)


@tagged("post_install", "-at_install")
class TestAskedAfterItEnded(_TrialPricing):
    """The negative: asking late is charged, whenever it is approved."""

    longMessage = False
    PINNED = datetime(2026, 10, 18, 12, 0)

    def test_the_price_date_is_the_day_she_asked(self):
        req = self._request_made_at(datetime(2026, 10, 17, 10, 0))
        self.assertEqual(str(req._price_date()), '2026-10-17')

    def test_she_pays_the_list_price(self):
        req = self._request_made_at(datetime(2026, 10, 17, 10, 0))
        self.assertAlmostEqual(
            self.product.sudo().fitness_effective_price(
                on=req._price_date()), 12.0, places=2,
            msg="a request made after the offer ended is still free")

    def test_half_past_midnight_on_the_seventeenth_is_too_late(self):
        """00:30 Madrid on the 17th is still 22:30 UTC on the 16th.

        Under the old reader's-timezone rule this was the leak: she
        would have been priced on the 16th and got it free.
        """
        req = self._request_made_at(datetime(2026, 10, 17, 0, 30))
        self.assertEqual(str(req._price_date()), '2026-10-17')
        self.assertAlmostEqual(
            self.product.sudo().fitness_effective_price(
                on=req._price_date()), 12.0, places=2)


@tagged("post_install", "-at_install")
class TestTheRuleCanBeTurnedOff(_TrialPricing):
    """One flag, so the owner can have it the other way."""

    longMessage = False
    PINNED = datetime(2026, 10, 18, 12, 0)

    def test_without_it_the_price_is_todays(self):
        req = self._request_made_at(datetime(2026, 10, 15, 12, 0))
        self.patch(type(req), 'PRICE_FOLLOWS_REQUEST_DATE', False)
        self.assertEqual(str(req._price_date()), '2026-10-18',
                         "turning the flag off did not fall back to today")
        self.assertAlmostEqual(
            self.product.sudo().fitness_effective_price(
                on=req._price_date()), 12.0, places=2)
