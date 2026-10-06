# -*- coding: utf-8 -*-
"""What /trial says once the free trial is over, in each language.

The message was built in the controller with _(), which resolves against
request.env.lang. The rest of that page does not work that way: it reads
an mv_lang cookie into `_lang` and branches on it by hand. On a public
page there is no user, so _() fell back to the database default and a
Spanish visitor got a Spanish heading with an English sentence under it.

Nothing here reads a seeded promotion: the products, their prices and
the offer's end are all set by this test.

The app trial page (/my/trial) is deliberately not covered the same way:
it has no ended-offer sentence at all - once the offer closes it sets
trial_offer_url to False and stops offering the card - and its labels
resolve against a logged-in student's own language, so the mismatch
cannot arise there.
"""
from datetime import datetime

import pytz

from odoo.tests import HttpCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
BARRE_PRICE = 12.0
REFORMER_PRICE = 18.0
#: the offer ended yesterday relative to the pinned clock
OFFER_END = '2026-10-16'
PINNED = datetime(2026, 10, 17, 10, 0)

SENTENCE = {
    'es_ES': 'La clase de prueba gratuita ha terminado',
    'ca_ES': "La classe de prova gratuïta s'ha acabat",
    'en_US': 'The free trial has ended',
}
#: the sentence that must NOT appear in the other two languages
OTHERS = {
    'es_ES': ('The free trial has ended', "La classe de prova"),
    'ca_ES': ('The free trial has ended', 'La clase de prueba gratuita'),
    'en_US': ('La clase de prueba gratuita', 'La classe de prova'),
}
SUBTITLE = {
    'es_ES': 'rellena el formulario',
    'ca_ES': 'omple el formulari',
    'en_US': 'fill in the form',
}


def _utc(local_naive):
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


@tagged("post_install", "-at_install")
class TestEndedOfferMessage(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(_utc(PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)

        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_lang(code)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', OFFER_END)
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        TR = self.env['fitness.trial.request'].sudo()
        prices = {'barre': BARRE_PRICE, 'reformer': REFORMER_PRICE}
        for prod in TR._all_trial_products():
            kind = prod.fitness_class_type
            if kind in prices:
                prod.sudo().write({
                    'list_price': prices[kind],
                    'fitness_promo_mode': 'free',
                    'fitness_promo_end': OFFER_END,
                })
        self.env.flush_all()

    def _page(self, lang):
        """The public form, as a visitor whose cookie says this language."""
        self.opener.cookies.set('mv_lang', lang)
        res = self.url_open('/trial')
        self.assertEqual(res.status_code, 200,
                         "/trial did not load for %s" % lang)
        return res.text

    # ── the sentence, in each language ───────────────────────────────
    def test_spanish(self):
        self._assert_language('es_ES')

    def test_catalan(self):
        self._assert_language('ca_ES')

    def test_english(self):
        self._assert_language('en_US')

    def _assert_language(self, lang):
        body = self._page(lang)
        self.assertIn(
            SENTENCE[lang], body,
            "%s does not carry its own ended-offer sentence" % lang)
        for other in OTHERS[lang]:
            self.assertNotIn(
                other, body,
                "%s is showing another language's sentence (%r) - the "
                "message is resolving against a different language from "
                "the page" % (lang, other[:40]))

    # ── euros, never EUR ─────────────────────────────────────────────
    def test_the_prices_are_in_euro_signs_not_the_word(self):
        for lang in SENTENCE:
            body = self._page(lang)
            self.assertIn('€', body,
                          "%s does not use the euro sign" % lang)
            self.assertNotIn(
                'EUR (Barre)', body,
                "%s still writes EUR instead of the euro sign" % lang)

    # ── the prices come from the products ────────────────────────────
    def test_the_prices_are_the_products_list_prices(self):
        body = self._page('es_ES')
        self.assertIn('12', body, "the Barre list price is not on the page")
        self.assertIn('18', body, "the Reformer list price is not on the page")

    def test_changing_a_list_price_changes_the_page(self):
        """Proves the figures are read, not written into the template."""
        TR = self.env['fitness.trial.request'].sudo()
        for prod in TR._all_trial_products():
            if prod.fitness_class_type == 'barre':
                prod.sudo().write({'list_price': 33.0})
        self.env.flush_all()
        body = self._page('es_ES')
        self.assertIn('33', body,
                      "the page still shows the old Barre price, so the "
                      "figure is hardcoded somewhere")

    # ── no form, and no invitation to fill one in ────────────────────
    def test_there_is_no_form(self):
        for lang in SENTENCE:
            body = self._page(lang)
            self.assertNotIn(
                'action="/trial/submit"', body,
                "%s still draws a form that cannot be submitted" % lang)

    def test_there_is_no_fill_in_the_form_subtitle(self):
        for lang, phrase in SUBTITLE.items():
            body = self._page(lang)
            self.assertNotIn(
                phrase, body,
                "%s still invites her to fill in a form that is not "
                "on the page" % lang)

    # ── the negative: while the offer runs, none of this shows ───────
    def test_while_the_offer_runs_there_is_a_form_and_no_message(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2099-12-31')
        self.env.registry.clear_cache()
        body = self._page('es_ES')
        self.assertIn('action="/trial/submit"', body,
                      "the form is missing while the offer is still open")
        self.assertNotIn(
            SENTENCE['es_ES'], body,
            "the ended-offer message shows while the offer is still open")
