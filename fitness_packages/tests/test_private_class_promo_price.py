# -*- coding: utf-8 -*-
"""A promotion on a private-class product is charged, not ignored.

The promotion block - Full price / Free / Percentage off, with a date
window - sits on EVERY fitness product. The studio sets it on the
product screen and expects the app to charge it, and everywhere she
sells from does: the shop, the desk sale wizard and the membership
lines all ask fitness_effective_price().

This one screen asked for list_price. So the one discount she could set
and not get was on a private class - and because the two numbers are
identical outside the promotion's window, nothing looked wrong until
somebody put a promotion on one.

Asserted on the price the wizard proposes, which is what the manager is
shown and what action_add charges unless she overrides it.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

PRIVATE_REFORMER = 'fitness_packages.product_private_single'


@tagged("post_install", "-at_install")
class TestPrivateClassPromoPrice(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.manager = cls.env["res.users"].create({
            "name": "Promo Price Manager",
            "login": "promo.price.mgr@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Promo price room", "classroom_type": "reformer",
            "capacity": 6})
        cls.private_type = cls.env["fitness.class.type"].create({
            "name": "Promo price private", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "private",
            "classroom_id": cls.room.id})
        cls.student = cls.env["res.partner"].create({
            "name": "Promo Price Student",
            "email": "promo.price.student@example.invalid"})
        cls.product = cls.env.ref(PRIVATE_REFORMER).sudo()

    # -- fixtures ---------------------------------------------------------

    def _event(self, days=21):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": "Promo price class", "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.private_type.id,
            "classroom_id": self.room.id,
            "is_fitness_class": True, "capacity": 1,
        })

    def _proposed_price(self, event):
        """What the wizard puts in the price box when it opens."""
        wiz = self.env["fitness.add.student.wizard"].with_user(self.manager)
        defaults = wiz.with_context(
            active_model='calendar.event', active_id=event.id,
        ).default_get(['price', 'product_id', 'event_id'])
        return defaults.get('price')

    def _set_promo(self, mode, percent=0.0, days_from=-1, days_to=30):
        today = fields.Date.context_today(self.env.user)
        self.product.write({
            'fitness_promo_mode': mode,
            'fitness_promo_percent': percent,
            'fitness_promo_start': today + timedelta(days=days_from),
            'fitness_promo_end': today + timedelta(days=days_to),
        })

    # -- the fault --------------------------------------------------------

    def test_a_live_percentage_promotion_is_charged(self):
        self.product.write({'list_price': 50.0})
        self._set_promo('percent', percent=20.0)

        price = self._proposed_price(self._event())

        self.assertAlmostEqual(
            price, 40.0, places=2,
            msg="the studio set 20%% off a 50.00 private class and the "
                "wizard proposes %.2f" % (price or 0.0))

    def test_a_live_free_promotion_is_charged_as_nothing(self):
        self.product.write({'list_price': 50.0})
        self._set_promo('free')

        price = self._proposed_price(self._event())

        self.assertAlmostEqual(
            price, 0.0, places=2,
            msg="the class was made free and the wizard proposes %.2f"
                % (price or 0.0))

    def test_it_agrees_with_the_product_itself(self):
        """Whatever the promotion is, one answer - the product's."""
        self.product.write({'list_price': 50.0})
        self._set_promo('percent', percent=35.0)

        self.assertAlmostEqual(
            self._proposed_price(self._event()),
            self.product.fitness_effective_price(), places=2,
            msg="the wizard and the product disagree about today's price")

    # -- the negatives ----------------------------------------------------

    def test_no_promotion_still_charges_the_list_price(self):
        """The ordinary case has to keep working."""
        self.product.write({
            'list_price': 50.0, 'fitness_promo_mode': 'none',
            'fitness_promo_start': False, 'fitness_promo_end': False})

        self.assertAlmostEqual(
            self._proposed_price(self._event()), 50.0, places=2,
            msg="a class with no promotion is no longer charged at its "
                "own price")

    def test_a_promotion_that_has_not_started_is_not_charged(self):
        self.product.write({'list_price': 50.0})
        self._set_promo('free', days_from=5, days_to=40)

        self.assertAlmostEqual(
            self._proposed_price(self._event()), 50.0, places=2,
            msg="a promotion starting next week is already being given away")

    def test_an_expired_promotion_is_not_charged(self):
        self.product.write({'list_price': 50.0})
        self._set_promo('free', days_from=-40, days_to=-5)

        self.assertAlmostEqual(
            self._proposed_price(self._event()), 50.0, places=2,
            msg="a promotion that ended last week is still being honoured")
