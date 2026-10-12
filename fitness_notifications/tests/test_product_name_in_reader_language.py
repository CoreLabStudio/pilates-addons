# -*- coding: utf-8 -*-
"""A purchase notification names the product in the reader's language.

The sentence was translated into the student's language, but the
product name was read in the language of whoever confirmed the sale -
usually a manager working in English. On production a Spanish reader
got "Reformer Private Pack 5 confirmada" while her balances screen said
"Bono Reformer Privado 5".

Now the reader's language decides both, falling back to the company's
and then English, each only if installed. es, ca and en, a reader with
no language, and one whose language is not installed.

Clock pinned; the confirming user is English on purpose, which is the
failing condition.
"""
from datetime import datetime

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
NAMES = {
    'en_US': 'Reformer Private Pack 5',
    'es_ES': 'Bono Reformer Privado 5',
    'ca_ES': 'Bo Reformer Privat 5',
}
CONFIRMED = {
    'en_US': 'Reformer Private Pack 5 confirmed',
    'es_ES': 'Bono Reformer Privado 5',
    'ca_ES': 'Bo Reformer Privat 5',
}


@tagged('post_install', '-at_install')
class TestProductNameInReaderLanguage(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.pack = self.env['product.template'].with_context(
            lang='en_US').create({
                'name': NAMES['en_US'], 'list_price': 225.0,
                'type': 'service', 'fitness_is_package': True,
                'fitness_class_count': 5, 'fitness_validity_days': 90,
                'fitness_class_type': 'reformer',
                'fitness_session_type': 'private'})
        for lang in ('es_ES', 'ca_ES'):
            self.pack.with_context(lang=lang).name = NAMES[lang]
        self.plan = self.env['product.template'].with_context(
            lang='en_US').create({
                'name': 'Reformer 1 a week', 'list_price': 60.0,
                'type': 'service', 'sale_ok': True,
                'fitness_is_subscription_plan': True,
                'recurring_invoice': True, 'fitness_class_type': 'reformer',
                'fitness_session_type': 'group', 'weekly_class_allowance': 1})
        self.plan.with_context(lang='es_ES').name = 'Reformer 1 a la semana'
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'PN Manager', 'login': 'pn.manager@example.invalid',
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('sales_team.group_sale_salesman').id,
                    self.env.ref('fitness_core.group_fitness_manager').id])],
            })
        self._seq = 0

    def _student(self, lang):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'PN Student %d' % self._seq,
                'login': 'pn.%d@example.invalid' % self._seq,
                'email': 'pn.%d@example.invalid' % self._seq,
                'lang': lang, 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])],
            })

    def _bought(self, user, product=None):
        product = product or self.pack
        vals = {'partner_id': user.partner_id.id}
        if product == self.plan:
            vals['plan_id'] = self.env.ref(
                'sale_subscription.subscription_plan_month').id
        order = self.env['sale.order'].sudo().create(vals)
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': product.list_price,
            'fitness_class_type': 'reformer'})
        order.with_user(self.manager).with_context(
            lang='en_US').sudo().action_confirm()
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'purchase_completed')])

    def test_each_reader_gets_the_name_in_her_language(self):
        for lang in ('en_US', 'es_ES', 'ca_ES'):
            with self.subTest(lang=lang):
                notif = self._bought(self._student(lang))
                self.assertEqual(len(notif), 1)
                self.assertIn(NAMES[lang], notif.title)
                others = [NAMES[o] for o in NAMES if o != lang]
                for other in others:
                    self.assertNotIn(other, notif.title)

    def test_the_sentence_and_the_name_agree(self):
        notif = self._bought(self._student('es_ES'))
        self.assertNotIn('confirmed', notif.title,
                         'the Spanish reader got an English sentence')
        self.assertIn('Bono Reformer Privado 5', notif.title)

    def test_no_language_falls_back_to_the_company(self):
        self.env.company.partner_id.lang = 'ca_ES'
        notif = self._bought(self._student(False))
        self.assertIn(NAMES['ca_ES'], notif.title)

    def test_an_uninstalled_language_falls_back_to_the_company(self):
        """Asked of the chooser directly: the ORM will not store an
        inactive code on a partner, so no real reader can carry one -
        but a language uninstalled later leaves exactly that behind."""
        self.env.company.partner_id.lang = 'es_ES'
        order = self.env['sale.order'].sudo().create(
            {'partner_id': self._student('en_US').partner_id.id})

        class Reader:
            lang = 'fr_FR'
        self.assertEqual(order._fitness_reader_lang(Reader()), 'es_ES')
        Reader.lang = False
        self.assertEqual(order._fitness_reader_lang(Reader()), 'es_ES')
        self.env.company.partner_id.lang = 'en_US'
        Reader.lang = 'fr_FR'
        self.assertEqual(order._fitness_reader_lang(Reader()), 'en_US')

    def test_english_counts_even_where_it_is_not_flagged_active(self):
        """A database installed with --load-language leaves en_US with
        active NULL. English is the source language and always renders,
        so an English reader there must still be told in English."""
        self.env.company.partner_id.lang = 'es_ES'
        self.env.cr.execute(
            "UPDATE res_lang SET active = NULL WHERE code = 'en_US'")
        self.env['res.lang'].invalidate_model()
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        notif = self._bought(self._student('en_US'))
        self.assertIn(NAMES['en_US'], notif.title)
        self.assertIn('confirmed', notif.title)

    def test_a_membership_is_named_in_her_language_too(self):
        notif = self._bought(self._student('es_ES'), self.plan)
        self.assertIn('Reformer 1 a la semana', notif.title)
