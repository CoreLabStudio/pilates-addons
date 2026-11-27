# -*- coding: utf-8 -*-
"""The 30-day renewal rule, said beside the registration card.

One sentence, on the Memberships tab only, in the member's language. Its
two numbers are not typed: the days are the fee rule's own FEE_WINDOW_DAYS
and the amount is the registration product's price, so the sentence moves
when either does.
"""
import html

from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_subscriptions.models.membership_dates import FEE_WINDOW_DAYS

PW = 'fee-note-pw-1'
MATRICULA = 'fitness_subscriptions.product_matricula'
SENTENCE = {
    'en_US': "Your membership ends on its last paid day. You have {days} days to renew without paying the "
             "registration fee again. After that, the {fee} registration fee applies.",
    'es_ES': "Tu membresía termina el último día pagado. Tienes {days} días para renovarla sin volver a pagar "
             "la matrícula. Pasado ese plazo, se aplicará de nuevo la matrícula de {fee}.",
    'ca_ES': "La teva membresia acaba l'últim dia pagat. Tens {days} dies per renovar-la sense tornar a pagar "
             "la matrícula. Passat aquest termini, s'aplicarà de nou la matrícula de {fee}.",
}


@tagged('post_install', '-at_install')
class TestFeeWindowNote(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        for code in ('es_ES', 'ca_ES'):
            env['res.lang']._activate_and_install_lang(code)
        env['res.lang']._activate_lang('en_US')
        cls.matricula = env.ref(MATRICULA).sudo()
        cls.matricula.active = True
        cls.month = env.ref('sale_subscription.subscription_plan_month')
        cls.plan = env['product.template'].sudo().create({
            'name': 'FN membership', 'list_price': 95.0, 'type': 'service', 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2, 'fitness_subscription_plan_id': cls.month.id})
        cls.seq = 0

    def _open(self, url, lang):
        type(self).seq += 1
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FN Student %d' % self.seq, 'login': 'fn.s%d@example.invalid' % self.seq,
            'email': 'fn.s%d@example.invalid' % self.seq, 'password': PW, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        self.env.flush_all()
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, url)
        self.assertNotIn('name="password"', res.text, 'session lost on %s' % url)
        return html.unescape(res.text)

    def _expected(self, lang):
        price = self.matricula.fitness_effective_price()
        amount = '%d' % price if float(price).is_integer() else None
        self.assertTrue(amount, 'fixture: the fee is expected to be a whole number of euros')
        symbol = self.matricula.currency_id.symbol or '€'
        return SENTENCE[lang].format(days=FEE_WINDOW_DAYS, fee='%s %s' % (amount, symbol))

    def test_the_memberships_tab_says_it_in_three_languages(self):
        for lang in SENTENCE:
            page = self._open('/my/packages?tab=subscriptions', lang)
            self.assertIn(self._expected(lang), page, lang)
        self.assertIn('the 39 ', self._expected('en_US'), 'the studio fee is 39')

    def test_it_shows_nowhere_else(self):
        for url in ('/my/packages?tab=classes', '/my/packages?tab=packages',
                    '/my/packages/%d' % self.plan.id, '/my/packages/%d/checkout' % self.plan.id,
                    '/my/home'):
            page = self._open(url, 'en_US')
            self.assertNotIn('days to renew without paying', page, url)
            self.assertEqual(page.count('class="mv-fee-window"'), 0, url)

    def test_the_amount_follows_the_fee_product(self):
        self.matricula.list_price = self.matricula.list_price + 6.0
        page = self._open('/my/packages?tab=subscriptions', 'en_US')
        self.assertIn(self._expected('en_US'), page)
        self.assertNotIn('the 39 ', page.split('days to renew without paying')[1][:120])

    def test_no_fee_product_no_sentence(self):
        self.matricula.active = False
        page = self._open('/my/packages?tab=subscriptions', 'en_US')
        self.assertNotIn('days to renew without paying', page)
