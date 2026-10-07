# -*- coding: utf-8 -*-
"""A request already with the studio, on both sides of the offer's last night.

The offer ends on a Madrid date. Everything about claiming a trial stops at
that moment - the promotion, the price, the cards. A request that was made
while the offer was open does not: the studio has it, the studio said it
would come back to her, and the app must keep saying so on 17 October just
as it did on the 16th. Otherwise a student who asked at 23:00 opens the app
after midnight and is told to go and buy something.

The clock is pinned with Odoo's freeze_time, started in setUp and stopped
by addCleanup - never a run() override - following the file that already
pins this same boundary for the offer itself.
"""
from datetime import datetime

import pytz

from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone("Europe/Madrid")
OFFER_END = "2026-10-16"


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
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", OFFER_END)
        self.env.company.email = "studio.inbox@example.invalid"
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        self.TR = self.env["fitness.trial.request"].sudo()
        self.Mail = self.env["mail.mail"].sudo()

    # -- helpers -----------------------------------------------------
    def _marker(self):
        return self.Mail.search([], order="id desc", limit=1).id or 0

    def _studio_mail_since(self, marker):
        self.env.flush_all()
        return self.Mail.search([("id", ">", marker)]).filtered(
            lambda m: self.env.company.email in (m.email_to or ""))

    def _student(self, tag):
        user = self.env["res.users"].create({
            "name": "Boundary %s" % tag,
            "login": "boundary.%s@example.invalid" % tag,
            "lang": "en_US",
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        return user

    def _ask(self, user):
        return self.TR.create({
            "name": user.name,
            "email": user.login,
            "partner_id": user.partner_id.id,
            "class_interest": "barre",
        })

    def _still_open(self, user):
        """What the three screens ask: is the studio still holding it?"""
        return bool(self.TR._open_request_for(user.partner_id))


@tagged("post_install", "-at_install")
class TestTheLastEveningOfTheOffer(_AtMadridTime):
    """16 October, 23:30 in Barcelona. The offer is open."""

    PINNED = datetime(2026, 10, 16, 23, 30)

    def test_a_request_made_now_reaches_the_studio(self):
        user = self._student("lastnight")
        marker = self._marker()
        rec = self._ask(user)
        self.assertEqual(rec.status, "pending")
        self.assertTrue(
            self._studio_mail_since(marker),
            "a request made on the last evening of the offer does not "
            "reach the studio, so the last night's leads are the ones lost")

    def test_the_app_knows_the_studio_is_holding_it(self):
        user = self._student("lastnightscreen")
        self._ask(user)
        self.assertTrue(
            self._still_open(user),
            "the request reads as closed the moment it is made")


@tagged("post_install", "-at_install")
class TestJustAfterMidnightInBarcelona(_AtMadridTime):
    """17 October, 00:30. The offer is over; her request is not."""

    PINNED = datetime(2026, 10, 17, 0, 30)

    def test_a_request_made_before_midnight_is_still_open_after_it(self):
        """The offer ending does not cancel what the studio already has."""
        user = self._student("aftermidnight")
        rec = self._ask(user)
        self.assertEqual(
            rec.status, "pending",
            "the request changed state when the offer lapsed")
        self.assertTrue(
            self._still_open(user),
            "her request stopped counting as open the moment the offer "
            "ended, so the app goes back to telling her to buy something "
            "while the studio is still holding her free class")

    def test_the_studio_is_still_told_about_a_request_made_now(self):
        """Somebody asking after the deadline still has to be answered."""
        user = self._student("afterdeadline")
        marker = self._marker()
        self._ask(user)
        self.assertTrue(
            self._studio_mail_since(marker),
            "a request made after the offer ended reaches nobody, so it "
            "sits in the list unanswered")

    def test_the_offer_itself_really_is_over(self):
        """Proves the clock is where this test says it is."""
        barre = self.env.ref("fitness_packages.product_barre_trial")
        self.assertFalse(
            barre.sudo()._fitness_promo_window_open(),
            "the fixture is wrong: the offer is still open at 00:30 on the "
            "17th, so nothing above is being tested after the deadline")
