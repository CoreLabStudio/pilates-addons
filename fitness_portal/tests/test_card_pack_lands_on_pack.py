# -*- coding: utf-8 -*-
"""Back from a card payment, she lands on what she just paid for.

Every card payment returns to /my/packages?from_payment=1. A member whose
fixed-class membership still lacks its weekly hours was sent on to the hour
picker whatever she had just paid for - so buying a pack of classes by card
took her to "Choose your weekly class" instead of to the pack. The picker is
the right place only when the payment that just went through paid that
membership (or its renewal).

Driven through Stripe in test mode: the provider is switched to 'test' with
throwaway keys, the transaction is a real Stripe payment.transaction linked
to her quotation, and it is settled by a signed payment_intent.succeeded
event POSTed to Odoo's own Stripe webhook route. Only Stripe's servers are
missing: the event is built here and signed with the throwaway secret.
Post-processing (which confirms the order) is then run the way the payment
status page triggers it.

A gate database is a fresh install of our modules, which do not depend on
payment_stripe. There the same transaction runs on another provider and is
settled by _set_done() - the state the webhook would leave - so the landing
rule is still checked on every build.
"""
import hashlib
import hmac
import json
import time

from odoo import fields
from odoo.addons.payment import utils as payment_utils
from odoo.tests import HttpCase, tagged

from .test_fixed_class_after_payment import PW, FixedFixture

WEBHOOK_SECRET = 'whsec_localrepro'


@tagged('post_install', '-at_install')
class TestCardPaymentLandsOnWhatWasPaid(FixedFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        cls.has_stripe = bool(cls.env['ir.module.module'].sudo().search_count(
            [('name', '=', 'payment_stripe'), ('state', '=', 'installed')]))
        Provider = cls.env['payment.provider'].sudo()
        if cls.has_stripe:
            cls.provider = Provider.search([('code', '=', 'stripe')], limit=1)
            cls.provider.write({
                'state': 'test',
                'stripe_publishable_key': 'pk_test_localrepro',
                'stripe_secret_key': 'sk_test_localrepro',
                'stripe_webhook_secret': WEBHOOK_SECRET,
            })
        else:
            cls.provider = Provider.search([], limit=1)
            cls.provider.write({'state': 'test'})
            # Post-processing records an account.payment, which needs a payment
            # method line for this provider on a bank journal. Stripe ships its
            # account.payment.method; a generic provider (custom, none) does not,
            # so on a gate database the payment was refused ("define a payment
            # method line"). Give the borrowed provider the same set-up Stripe has.
            code = cls.provider._get_code()
            Method = cls.env['account.payment.method'].sudo()
            if not Method.search([('code', '=', code)], limit=1):
                Method.create({'name': 'CP card', 'code': code, 'payment_type': 'inbound'})
            journal = cls.env['account.journal'].sudo().search([
                ('type', '=', 'bank'), ('company_id', '=', cls.env.company.id)], limit=1)
            if not journal:
                journal = cls.env['account.journal'].sudo().create(
                    {'name': 'CP Bank', 'type': 'bank', 'code': 'CPBK'})
            cls.provider.journal_id = journal
            cls.provider._ensure_payment_method_line()
        cls.card = cls.env.ref('payment.payment_method_card').sudo()
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'CP Reformer Pack 5', 'type': 'service', 'list_price': 60.0,
            'sale_ok': True, 'fitness_is_package': True,
            'fitness_class_count': 5, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})

    # -- helpers ---------------------------------------------------------

    def _quotation(self, user, product, price, plan=None):
        vals = {'partner_id': user.partner_id.id}
        if plan:
            vals.update(plan_id=plan.id, start_date=fields.Date.today())
        so = self.env['sale.order'].sudo().create(vals)
        self.env['sale.order.line'].sudo().create({
            'order_id': so.id, 'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': price})
        return so

    def _pay_by_card(self, so, ref):
        """A card transaction for the order, settled the way Stripe settles it."""
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id, 'payment_method_id': self.card.id,
            'reference': ref, 'amount': so.amount_total,
            'currency_id': so.currency_id.id, 'partner_id': so.partner_id.id,
            'operation': 'online_direct',
            'sale_order_ids': [(6, 0, so.ids)]})
        self.assertEqual(tx.state, 'draft')
        if self.has_stripe:
            self._stripe_webhook_succeeded(tx, so, ref)
        else:
            tx._set_done()
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'done', 'payment %s not settled' % ref)
        # What /payment/status/poll does once she is back on the site.
        tx._post_process()
        so.invalidate_recordset()
        self.assertEqual(so.state, 'sale', '%s not confirmed by the payment' % so.name)
        return tx

    def _stripe_webhook_succeeded(self, tx, so, ref):
        """POST a signed payment_intent.succeeded to Odoo's Stripe webhook."""
        self.assertEqual(tx.provider_code, 'stripe')
        self.assertEqual(tx.provider_id.state, 'test')
        event = {
            'type': 'payment_intent.succeeded',
            'data': {'object': {
                'id': 'pi_%s' % ref, 'object': 'payment_intent',
                'description': ref, 'status': 'succeeded',
                'amount': payment_utils.to_minor_currency_units(
                    so.amount_total, so.currency_id),
                'currency': so.currency_id.name.lower(),
                'payment_method': {'type': 'card', 'card': {'brand': 'visa'}},
            }},
        }
        body = json.dumps(event)
        stamp = int(time.time())
        sig = hmac.new(WEBHOOK_SECRET.encode(), f'{stamp}.{body}'.encode(),
                       hashlib.sha256).hexdigest()
        r = self.url_open('/payment/stripe/webhook', data=body, headers={
            'Content-Type': 'application/json',
            'Stripe-Signature': f't={stamp},v1={sig}'})
        self.assertEqual(r.status_code, 200)
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'done', 'the webhook did not settle %s' % ref)
        self.assertEqual(tx.provider_reference, 'pi_%s' % ref)

    def _back_from_payment(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)
        # The site first moves her to her language's prefix (/en/my/...,
        # /ca_ES/my/...). That hop is the same page; follow it, and stop at
        # the first redirect that goes anywhere else.
        url = '/my/packages?from_payment=1'
        for _hop in range(3):
            r = self.url_open(url, allow_redirects=False)
            location = r.headers.get('Location', '')
            if not (r.is_redirect and location.endswith('/my/packages?from_payment=1')):
                return r
            url = location
        self.fail('redirect loop on %s' % url)

    # -- tests -----------------------------------------------------------

    def test_pack_paid_by_card_lands_on_the_pack_not_the_hour_picker(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student = self._student('cppack' + lang[:2], lang)
                membership = self._membership(student, start=fields.Date.today())
                self.assertTrue(membership.fitness_missing_fixed_slots(),
                                'fixture: the membership must still owe hours')
                pack_so = self._quotation(student, self.pack, 60.0)
                self._pay_by_card(pack_so, 'CP-PACK-%s' % lang)
                r = self._back_from_payment(student, lang)
                location = r.headers.get('Location', '')
                self.assertNotIn('/my/fixed-class', location,
                                 'pack buyer diverted to %s' % location)
                self.assertEqual(r.status_code, 200,
                                 'expected the packages page, got %s -> %s'
                                 % (r.status_code, location))
                # Payment confirmed, on the tab that holds her pack.
                self.assertIn('id="mv-pay-done"', r.text)
                self.assertRegex(
                    r.text,
                    r'href="(/[a-z_]+)?/my/packages\?tab=packages"\s+class="mv-segment mv-active"')
                self.assertIn('CP Reformer Pack 5', r.text)

    def test_membership_paid_by_card_still_goes_to_the_hour_picker(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student = self._student('cpmemb' + lang[:2], lang)
                so = self._quotation(student, self.product, 130.0, plan=self.plan)
                self._pay_by_card(so, 'CP-MEMB-%s' % lang)
                self.assertTrue(so.fitness_missing_fixed_slots(),
                                'fixture: the paid membership must owe hours')
                r = self._back_from_payment(student, lang)
                self.assertIn(r.status_code, (301, 302, 303))
                self.assertTrue(r.headers.get('Location', '').endswith('/my/fixed-class'),
                                'landed on %s' % r.headers.get('Location'))
