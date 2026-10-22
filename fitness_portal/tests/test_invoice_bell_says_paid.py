# -*- coding: utf-8 -*-
"""Her invoice bell says "Paid" when she has paid, and "Amount due" only when she owes.

Every invoice bell ended "Amount due: 65.00 EUR" - including the invoice
for the class she paid for at the desk a second earlier, or by card or
Bizum before Odoo raised it. Read as a second bill. The bell is created at
posting, which on every pay-up-front path comes before the payment entry,
so "paid" is answered from how the money came: the ledger, a completed
online payment behind the order, or cash taken at the desk.

es, ca and en.
"""
from odoo.tests import TransactionCase, tagged

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
STUDENT_GROUP = 'fitness_core.group_fitness_student'
PAID = {'en_US': 'Paid: ', 'es_ES': 'Pagada: ', 'ca_ES': 'Pagada: '}
DUE = {'en_US': 'Amount due: ', 'es_ES': 'Importe a pagar: ', 'ca_ES': 'Import a pagar: '}


@tagged('post_install', '-at_install')
class TestInvoiceBellSaysPaid(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'IB Manager', 'login': 'ib.mgr@example.invalid',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref(MANAGER_GROUP).id])]})
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'IB Pack', 'type': 'service', 'list_price': 75.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        if not cls.env['account.journal'].sudo().search(
                [('type', '=', 'cash'), ('company_id', '=', cls.env.company.id)]):
            cls.env['account.journal'].sudo().create({'name': 'IB Cash', 'code': 'IBC', 'type': 'cash'})
        cls._seq = 0

    def _student(self, lang):
        type(self)._seq += 1
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'IB Student %d' % self._seq, 'login': 'ib.%d@example.invalid' % self._seq,
            'email': 'ib.%d@example.invalid' % self._seq, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref(STUDENT_GROUP).id])]})

    def _bell(self, user):
        bells = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id), ('notification_type', '=', 'invoice_issued')])
        self.assertEqual(len(bells), 1, 'expected one invoice bell, got %d' % len(bells))
        return bells

    def _order(self, user, method=False):
        order = self.env['sale.order'].sudo().create({
            'partner_id': user.partner_id.id, 'fitness_payment_method': method})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        return order

    def test_cash_at_the_desk_is_announced_as_paid(self):
        for lang in PAID:
            with self.subTest(lang=lang):
                user = self._student(lang)
                wiz = self.env['fitness.desk.sale.wizard'].with_user(self.manager).create({
                    'partner_id': user.partner_id.id, 'product_id': self.pack.id,
                    'payment_method': 'cash'})
                wiz._onchange_product_id()
                wiz.action_create_sale()
                bell = self._bell(user)
                self.assertTrue(bell.body.startswith(PAID[lang]), '%s: %s' % (lang, bell.body))
                self.assertNotIn(DUE[lang].strip(), bell.body)

    def test_an_approved_cash_request_is_announced_as_paid(self):
        from odoo import fields
        user = self._student('ca_ES')
        order = self._order(user, 'cash')
        order.fitness_cash_requested_on = fields.Datetime.now()
        order.with_user(self.manager).action_fitness_approve_cash()
        bell = self._bell(user)
        self.assertTrue(bell.body.startswith(PAID['ca_ES']), bell.body)

    def test_a_completed_card_or_bizum_payment_is_announced_as_paid(self):
        for lang in PAID:
            with self.subTest(lang=lang):
                user = self._student(lang)
                order = self._order(user, 'stripe')
                PM = self.env['payment.method'].sudo().with_context(active_test=False)
                self.env['payment.transaction'].sudo().create({
                    'provider_id': self.env['payment.provider'].sudo().search([], limit=1).id,
                    'payment_method_id': PM.search([], limit=1).id,
                    'reference': 'IB-%s' % order.id, 'amount': order.amount_total,
                    'currency_id': order.currency_id.id, 'partner_id': user.partner_id.id,
                    'state': 'done', 'sale_order_ids': [(6, 0, order.ids)]})
                order.action_confirm()
                order._create_invoices().action_post()
                bell = self._bell(user)
                self.assertTrue(bell.body.startswith(PAID[lang]), '%s: %s' % (lang, bell.body))

    def test_an_invoice_nobody_has_paid_still_says_amount_due(self):
        for lang in DUE:
            with self.subTest(lang=lang):
                user = self._student(lang)
                order = self._order(user, 'transfer')
                order.action_confirm()
                order._create_invoices().action_post()
                bell = self._bell(user)
                self.assertTrue(bell.body.startswith(DUE[lang]), '%s: %s' % (lang, bell.body))

    def test_renew_cash_marks_the_invoice_it_posts_as_paid(self):
        """The in-window Renew (cash) posts the plan's own order, bought online or not."""
        user = self._student('es_ES')
        order = self._order(user, 'stripe')
        order.action_confirm()
        order._create_invoices().with_context(fitness_paid_in_cash=True).action_post()
        self.assertTrue(self._bell(user).body.startswith(PAID['es_ES']))
