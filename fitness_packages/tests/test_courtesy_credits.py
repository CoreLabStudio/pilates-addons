# -*- coding: utf-8 -*-
"""The free class credits: what each one pays for, and for how long.

Four products, one per discipline and session type. The payment-source
picker matches on BOTH fitness_class_type and fitness_session_type, so a
free group Barre credit pays for every group Barre class and nothing
else - not Reformer, and not a private Barre session.

The validity moved from 30 days to 15. The thing that has to be true,
and is asserted here rather than assumed, is that **a credit already in
somebody's hands keeps the dates it was given**: the expiry lives on the
order line as fitness_validity_end_date, written once when the order is
confirmed. Changing the product changes the next credit, never one
already issued.
"""
from datetime import date, datetime, timedelta

import pytz

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, common, tagged

from odoo.addons.fitness_core.models.studio_time import studio_today
from odoo.addons.fitness_packages.models.sale_order_line import (
    VALIDITY_LAST_DAY_OFFSET,
)

MADRID = pytz.timezone('Europe/Madrid')
#: Monday 12 October 2026, 10:00 in Madrid (CEST, UTC+2).
PINNED = datetime(2026, 10, 12, 8, 0, 0)


def utc(y, m, d, hh, mm):
    """A Madrid wall-clock time as the naive UTC Odoo stores."""
    return MADRID.localize(datetime(y, m, d, hh, mm)).astimezone(
        pytz.utc).replace(tzinfo=None)

COURTESY = {
    'fitness_packages.product_courtesy_barre': ('barre', 'group'),
    'fitness_packages.product_courtesy_reformer': ('reformer', 'group'),
    'fitness_packages.product_courtesy_barre_private': ('barre', 'private'),
    'fitness_packages.product_courtesy_reformer_private': ('reformer',
                                                           'private'),
}


@tagged("post_install", "-at_install")
class TestCourtesyCredits(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "CC Student",
                "login": "cc.student@example.invalid",
                "lang": "en_US", "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id])]})

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)

    # -- fixtures ----------------------------------------------------
    def _product(self, xmlid):
        product = self.env.ref(xmlid, raise_if_not_found=False)
        self.assertTrue(product, "%s does not exist" % xmlid)
        return product

    def _give(self, product):
        """A zero-priced confirmed order, the way a gift is recorded."""
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.student.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 0.0,
                "fitness_class_type": product.fitness_class_type})]})
        order.action_confirm()
        return order.order_line[:1]

    def _class(self, discipline, session, hours=30):
        ct = self.env["fitness.class.type"].create({
            "name": "CC %s %s" % (discipline, session),
            "classroom_type": discipline, "duration": 50,
            "level": "all", "session_type": session})
        start = fields.Datetime.now() + timedelta(hours=hours)
        return self.env["calendar.event"].sudo().create({
            "name": "CC %s %s class" % (discipline, session),
            "start": start, "stop": start + timedelta(minutes=50),
            "class_type_id": ct.id, "is_fitness_class": True,
            "capacity": 6, "session_type": session})

    # == all four exist and are shaped right =========================
    def test_all_four_products_exist_and_are_free(self):
        for xmlid, (disc, session) in COURTESY.items():
            product = self._product(xmlid)
            self.assertEqual(product.list_price, 0.0,
                             "%s is not free" % xmlid)
            self.assertEqual(product.fitness_class_count, 1,
                             "%s is not a single class" % xmlid)
            self.assertEqual(product.fitness_class_type, disc)
            self.assertEqual(product.fitness_session_type, session)
            self.assertTrue(product.fitness_is_package)

    def test_no_student_can_buy_one(self):
        """sale_ok=False keeps them out of the shop entirely."""
        for xmlid in COURTESY:
            product = self._product(xmlid)
            self.assertFalse(
                product.sale_ok,
                "%s is sellable, so it can reach the shop" % xmlid)

    def test_all_four_are_valid_fifteen_days(self):
        """All four, not just the private pair.

        The group pair shipped at 30 and is moved to 15 two ways: the
        data file, for a fresh install, and the 19.0.1.1.19
        post-migration, for a database that already holds the records.
        This asserts the result on whichever shape the suite is run on,
        which is the only way the two paths can be seen to agree.
        """
        for xmlid in COURTESY:
            self.assertEqual(
                self._product(xmlid).fitness_validity_days, 15,
                "%s is not valid for 15 days" % xmlid)

    # == what each one pays for ======================================
    def test_each_credit_pays_for_its_own_discipline_and_session(self):
        Booking = self.env["fitness.booking"].sudo()
        for xmlid, (disc, session) in COURTESY.items():
            product = self._product(xmlid)
            line = self._give(product)
            event = self._class(disc, session)
            source = Booking._select_payment_source(
                self.student.partner_id.id, event)
            self.assertEqual(
                source, {"package_order_line_id": line.id},
                "%s did not pay for its own %s %s class"
                % (xmlid, session, disc))
            line.sudo().fitness_remaining_classes = 0   # spend it

    def test_a_free_barre_credit_will_not_pay_for_reformer(self):
        """The negative that matters: it is not a free class anywhere."""
        from odoo.exceptions import UserError
        line = self._give(
            self._product('fitness_packages.product_courtesy_barre'))
        self.assertTrue(line)
        reformer = self._class("reformer", "group")
        with self.assertRaises(UserError):
            self.env["fitness.booking"].sudo()._select_payment_source(
                self.student.partner_id.id, reformer)

    def test_a_group_credit_will_not_pay_for_a_private_class(self):
        from odoo.exceptions import UserError
        self._give(self._product('fitness_packages.product_courtesy_barre'))
        private = self._class("barre", "private")
        with self.assertRaises(UserError):
            self.env["fitness.booking"].sudo()._select_payment_source(
                self.student.partner_id.id, private)

    def test_a_private_credit_will_not_pay_for_a_group_class(self):
        from odoo.exceptions import UserError
        self._give(self._product(
            'fitness_packages.product_courtesy_barre_private'))
        group = self._class("barre", "group")
        with self.assertRaises(UserError):
            self.env["fitness.booking"].sudo()._select_payment_source(
                self.student.partner_id.id, group)

    # == expiry, and what the change to 15 days does ==================
    def test_the_expiry_is_fifteen_days_from_the_day_it_is_given(self):
        product = self._product(
            'fitness_packages.product_courtesy_barre_private')
        line = self._give(product)
        expected = studio_today() + timedelta(days=15)
        self.assertEqual(
            line.fitness_validity_end_date, expected,
            "a credit given today does not run out in 15 days")

    def test_a_credit_already_given_keeps_its_own_dates(self):
        """The promise behind changing the product from 30 days to 15.

        The expiry is written onto the ORDER LINE when the order is
        confirmed. Changing the product afterwards must not move it, or
        the studio would be shortening credits people already hold.
        """
        product = self._product(
            'fitness_packages.product_courtesy_barre_private')
        product.sudo().fitness_validity_days = 30
        line = self._give(product)
        given_expiry = line.fitness_validity_end_date
        self.assertEqual(
            given_expiry, studio_today() + timedelta(days=30))

        # now the studio shortens the product, as the migration does
        product.sudo().fitness_validity_days = 15
        line.invalidate_recordset()
        self.assertEqual(
            line.fitness_validity_end_date, given_expiry,
            "shortening the product moved the expiry of a credit somebody "
            "already holds - she would lose days she was given")

    def test_an_expired_credit_stops_paying_for_anything(self):
        from odoo.exceptions import UserError
        product = self._product('fitness_packages.product_courtesy_barre')
        line = self._give(product)
        line.sudo().fitness_validity_end_date = (
            studio_today() - timedelta(days=1))
        line.invalidate_recordset()
        self.assertTrue(line.fitness_is_expired)
        with self.assertRaises(UserError):
            self.env["fitness.booking"].sudo()._select_payment_source(
                self.student.partner_id.id, self._class("barre", "group"))

    def test_it_still_pays_on_its_last_day(self):
        """The other side of the boundary."""
        product = self._product('fitness_packages.product_courtesy_barre')
        line = self._give(product)
        line.sudo().fitness_validity_end_date = studio_today()
        line.invalidate_recordset()
        self.assertFalse(
            line.fitness_is_expired,
            "a credit expires on its last day instead of at the end of it")

    # == a gift never touches her free trial =========================
    def test_giving_a_free_class_leaves_the_free_trial_alone(self):
        """They are different products, and that is the whole point."""
        # This module's own copy of the pair, not the portal controller's.
        # fitness_packages does not depend on fitness_portal - the
        # dependency runs the other way - so importing the controller here
        # made a fitness_packages test fail to even load on any build
        # where the portal is not installed.
        from odoo.addons.fitness_packages.models.fitness_booking import (
            FitnessBookingPackage,
        )
        self._give(self._product('fitness_packages.product_courtesy_barre'))
        trials = self.env["product.template"].sudo().browse()
        for xmlid in FitnessBookingPackage.TRIAL_XMLIDS:
            prod = self.env.ref(xmlid, raise_if_not_found=False)
            if prod:
                trials |= prod.sudo()
        used = self.env["sale.order.line"].sudo().search_count([
            ("order_partner_id", "=", self.student.partner_id.id),
            ("product_id", "in", trials.mapped("product_variant_ids").ids)])
        self.assertEqual(
            used, 0,
            "giving a free class consumed her free trial, so she would "
            "never be offered the trial she has not had")

    # == the owner's decision (b), cut on Madrid time =================
    def test_the_owner_decision_is_the_same_as_every_pack(self):
        """Given Monday 12 October, it works until the end of Tuesday 27."""
        self.assertEqual(VALIDITY_LAST_DAY_OFFSET, 0,
                         'owner decision (b): the same rule as every pack')
        line = self._give(self._product(
            'fitness_packages.product_courtesy_barre'))
        self.assertEqual(line.fitness_validity_end_date, date(2026, 10, 27))

    def test_the_day_given_is_madrids_not_the_servers(self):
        """00:30 on the 13th in Madrid is still the 12th in UTC."""
        with common.freeze_time(utc(2026, 10, 13, 0, 30)):
            line = self._give(self._product(
                'fitness_packages.product_courtesy_reformer'))
        self.assertEqual(line.fitness_validity_end_date, date(2026, 10, 28))

    def test_it_pays_to_the_end_of_its_last_day_in_madrid(self):
        """Both sides of midnight in Madrid, after the 25 October change."""
        line = self._give(self._product(
            'fitness_packages.product_courtesy_barre'))
        self.assertEqual(line.fitness_validity_end_date, date(2026, 10, 27))
        Booking = self.env['fitness.booking'].sudo()
        cls = self._class('barre', 'group', hours=24 * 20)
        with common.freeze_time(utc(2026, 10, 27, 23, 59)):
            self.assertEqual(
                Booking._select_payment_source(
                    self.student.partner_id.id, cls),
                {'package_order_line_id': line.id},
                'it stopped before the end of its last day in Madrid')
        with common.freeze_time(utc(2026, 10, 28, 0, 0)):
            with self.assertRaises(UserError):
                Booking._select_payment_source(
                    self.student.partner_id.id, cls)

    def test_none_of_the_four_is_in_the_catalog(self):
        action = self.env.ref('fitness_packages.action_fitness_package_products')
        from odoo.tools.safe_eval import safe_eval
        listed = self.env['product.template'].with_context(
            active_test=False).search(safe_eval(action.domain))
        for xmlid in COURTESY:
            self.assertNotIn(self._product(xmlid), listed, xmlid)
        self.assertTrue(listed, 'the catalog lists no package at all')


    def test_all_four_are_named_in_three_languages(self):
        """On a fresh database too: the data file names them in English
        and the catalogues carry es and ca. (An upgraded one is named by
        the migration as well.)"""
        names = {
            'fitness_packages.product_courtesy_barre': (
                'Free Barre class', 'Clase de cortesía (Barre)',
                'Classe de cortesia (Barre)'),
            'fitness_packages.product_courtesy_reformer': (
                'Free Reformer class', 'Clase de cortesía (Reformer)',
                'Classe de cortesia (Reformer)'),
            'fitness_packages.product_courtesy_barre_private': (
                'Free private Barre class',
                'Clase privada de cortesía (Barre)',
                'Classe privada de cortesia (Barre)'),
            'fitness_packages.product_courtesy_reformer_private': (
                'Free private Reformer class',
                'Clase privada de cortesía (Reformer)',
                'Classe privada de cortesia (Reformer)'),
        }
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for xmlid, expected in names.items():
            product = self._product(xmlid)
            for lang, name in zip(('en_US', 'es_ES', 'ca_ES'), expected):
                with self.subTest(xmlid=xmlid, lang=lang):
                    self.assertEqual(
                        product.with_context(lang=lang).name, name)

@tagged("post_install", "-at_install")
class TestCourtesyNotInTheShop(HttpCase):
    """Never in the shop the student uses, on any tab."""

    def test_the_shop_never_offers_one(self):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "CC Shopper", "login": "cc.shopper@example.invalid",
                "password": "cc-shopper-Pw-26", "lang": "en_US",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id])]})
        self.authenticate(user.login, "cc-shopper-Pw-26")
        pages = ''.join(self.url_open('/my/packages?tab=%s' % tab).text
                        for tab in ('classes', 'packages', 'subscriptions'))
        self.assertIn('/my/packages/', pages, 'the shop shows nothing at all')
        for xmlid in COURTESY:
            product = self.env.ref(xmlid)
            self.assertNotIn('/my/packages/%d"' % product.id, pages, xmlid)
