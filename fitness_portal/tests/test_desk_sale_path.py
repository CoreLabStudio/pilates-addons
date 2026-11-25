# -*- coding: utf-8 -*-
"""A desk sale is the same sale as one made in the app.

Owner's decisions (25 Nov 2026):
  * cash: membership and credits, an invoice for the real amount posted and
    paid in the cash journal, the order confirmation mail and the invoice
    mail - both only to a contact with an email;
  * free gift: membership and credits, NO invoice and no invoice number, the
    confirmation mail only, and a normal membership of the plan's length:
    neither close job may close it early;
  * the contact: found or created by email; a NEW contact with an email
    already on another one is refused, naming it; picking a contact whose
    email is also on another one only warns;
  * a gift's card in the app says when it ends ("Valid until"), never
    "Next billing" or "Next renewal".
"""
import html
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_core.models.studio_lang import studio_date

MANAGER = 'fitness_core.group_fitness_manager'
STUDENT = 'fitness_core.group_fitness_student'
PW = 'desk-path-pw-1'


@tagged('post_install', '-at_install')
class TestDeskSalePath(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        for code in ('es_ES', 'ca_ES'):
            env['res.lang']._activate_and_install_lang(code)
        env['res.lang']._activate_lang('en_US')
        Plan = env['sale.subscription.plan'].sudo()
        cls.monthly = Plan.create({'name': 'DP Mensual', 'billing_period_value': 1,
                                   'billing_period_unit': 'month'})
        cls.quarterly = Plan.create({'name': 'DP Trimestral', 'billing_period_value': 3,
                                     'billing_period_unit': 'month'})
        cls.membership = env['product.template'].sudo().create({
            'name': 'DP Barre', 'type': 'service', 'list_price': 95.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2, 'fitness_subscription_plan_id': cls.monthly.id})
        cls.pack = env['product.template'].sudo().create({
            'name': 'DP Pack 5', 'type': 'service', 'list_price': 50.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'DP Manager', 'login': 'dp.manager@example.invalid',
            'email': 'dp.manager@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref(MANAGER).id])]})
        cls.teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'DP Teacher', 'login': 'dp.teacher@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('fitness_core.group_fitness_teacher').id])]})
        if not env['account.journal'].sudo().search(
                [('type', '=', 'cash'), ('company_id', '=', env.company.id)], limit=1):
            env['account.journal'].sudo().create({
                'name': 'DP Cash', 'code': 'DPC', 'type': 'cash', 'company_id': env.company.id})
        cls.seq = 0

    # -- fixtures --------------------------------------------------------------

    def _contact(self, account, email):
        type(self).seq += 1
        n = self.seq
        addr = ('dp.c%d@example.invalid' % n) if email else False
        if account:
            user = self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'DP Member %d' % n, 'login': 'dp-login-%d' % n, 'email': addr,
                'password': PW, 'lang': 'en_US',
                'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                      self.env.ref(STUDENT).id])]})
            return user.partner_id, user
        return self.env['res.partner'].sudo().create({'name': 'DP Contact %d' % n, 'email': addr}), None

    def _sell(self, partner, method, plan=None):
        w = self.env['fitness.desk.sale.wizard'].with_user(self.manager).create({
            'partner_id': partner.id, 'product_id': self.membership.id,
            'plan_id': (plan or self.monthly).id, 'payment_method': method})
        if method == 'cash':
            w.amount_paid = w.normal_price
        else:
            w.reason = 'DP gift'
        w.action_create_sale()
        order = self.env['sale.order'].sudo().search([('partner_id', '=', partner.id)],
                                                     order='id desc', limit=1)
        return order, w

    def _confirmation_mails(self, order):
        return order.message_ids.filtered(
            lambda m: order.partner_id in m.partner_ids and order.name in (m.subject or ''))

    def _path(self, method, account, email):
        partner, user = self._contact(account, email)
        moves_before = self.env['account.move'].sudo().search_count([])
        order, wizard = self._sell(partner, method)
        self.assertEqual((order.state, order.subscription_state), ('sale', '3_progress'))
        self.assertTrue(order.fitness_subscription_product_id, 'no membership was granted')
        mails = self._confirmation_mails(order)
        self.assertEqual(bool(mails), bool(email), 'confirmation mail sent: %s' % bool(mails))
        if method == 'cash':
            inv = order.invoice_ids
            self.assertEqual(len(inv), 1)
            self.assertEqual(inv.state, 'posted')
            self.assertAlmostEqual(inv.amount_total, wizard.amount_paid, places=2)
            self.assertIn(inv.payment_state, ('paid', 'in_payment'))
            pay = self.env['account.payment'].sudo().search([('partner_id', '=', partner.id)])
            self.assertEqual(pay.journal_id.type, 'cash')
            self.assertTrue(pay.is_reconciled, 'the cash payment is not matched to the invoice')
            self.assertEqual(inv.is_move_sent, bool(email), 'invoice mail')
            if user:
                self.assertTrue(self.env['account.move'].with_user(user).search([('id', '=', inv.id)]),
                                'the member cannot see her invoice in the app')
        else:
            self.assertFalse(order.invoice_ids, 'a gift was invoiced')
            self.assertEqual(self.env['account.move'].sudo().search_count([]), moves_before,
                             'a gift created an accounting entry')
            self.assertEqual(order.amount_total, 0.0)
            self.assertEqual(order.next_invoice_date, order.start_date + self.monthly.billing_period)
        if user:
            self.assertTrue(self.env['sale.order'].with_user(user).search([('id', '=', order.id)]),
                            'the member cannot see the order in the app')
        else:
            self.assertFalse(partner.user_ids)
        return order

    # -- the eight paths ---------------------------------------------------------

    def test_cash_account_email(self):
        self._path('cash', True, True)

    def test_cash_account_no_email(self):
        self._path('cash', True, False)

    def test_cash_no_account_email(self):
        self._path('cash', False, True)

    def test_cash_no_account_no_email(self):
        self._path('cash', False, False)

    def test_free_account_email(self):
        self._path('free', True, True)

    def test_free_account_no_email(self):
        self._path('free', True, False)

    def test_free_no_account_email(self):
        self._path('free', False, True)

    def test_free_no_account_no_email(self):
        self._path('free', False, False)

    # -- answer c: which mails -----------------------------------------------------

    def test_cash_sends_confirmation_and_invoice_a_gift_the_confirmation_only(self):
        cash, _w = self._sell(self._contact(False, True)[0], 'cash')
        gift, _w = self._sell(self._contact(False, True)[0], 'free')
        self.assertTrue(self._confirmation_mails(cash))
        self.assertTrue(cash.invoice_ids.is_move_sent)
        self.assertTrue(self._confirmation_mails(gift))
        self.assertFalse(gift.invoice_ids)

    # -- a gift's dates: neither close job closes it early ---------------------------

    def _odoo_selects(self, order, day):
        dt = datetime(day.year, day.month, day.day)
        with patch.object(fields.Date, 'today', staticmethod(lambda *a: day)), \
                patch.object(fields.Datetime, 'today', staticmethod(lambda *a: dt)):
            self.env['sale.order'].flush_model()
            return order.id in {r['so_id'] for r in self.env['sale.order']._get_expired_subscriptions()}

    def test_a_gift_runs_its_whole_plan_under_both_close_jobs(self):
        SO = self.env['sale.order']
        for plan in (self.monthly, self.quarterly):
            gift, _w = self._sell(self._contact(False, False)[0], 'free', plan)
            start, end = gift.start_date, gift.start_date + plan.billing_period
            self.assertEqual(gift.next_invoice_date, end)
            day = start
            while day < end:
                self.assertFalse(self._odoo_selects(gift, day),
                                 "Odoo's expiry job selects a %s gift on %s" % (plan.name, day))
                self.assertNotIn(gift, SO._fitness_memberships_to_close(day),
                                 'the fitness job closes a %s gift on %s' % (plan.name, day))
                day += timedelta(days=1)
            self.assertIn(gift, SO._fitness_memberships_to_close(end),
                          'a gift does not end the day a paid membership would')
            self.assertEqual(gift._fitness_paid_up_to(), end - timedelta(days=1))

    def test_a_gift_uses_no_invoice_number(self):
        Move = self.env['account.move'].sudo()
        last = Move.search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted')],
                           order='id desc', limit=1).name
        self._sell(self._contact(False, True)[0], 'free')
        cash, _w = self._sell(self._contact(False, True)[0], 'cash')
        posted = Move.search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                              ('name', '!=', last)], order='id desc')
        self.assertEqual(posted.filtered(lambda m: m.id > (Move.search(
            [('name', '=', last)], limit=1).id or 0)), cash.invoice_ids,
            'an invoice number was taken by the gift')

    # -- the contact ---------------------------------------------------------------

    def test_a_new_contact_is_created_with_its_email(self):
        Partner = self.env['res.partner'].with_user(self.manager).with_context(fitness_desk_new_contact=True)
        pid, _name = Partner.name_create('DP Walk In <dp.walkin@example.invalid>')
        self.assertEqual(self.env['res.partner'].browse(pid).email, 'dp.walkin@example.invalid')
        found = self.env['res.partner'].with_user(self.manager).name_search('dp.walkin@example.invalid')
        self.assertIn(pid, [r[0] for r in found], 'the Student field does not find a contact by email')

    def test_a_new_contact_with_an_email_already_used_is_refused_naming_it(self):
        existing, _u = self._contact(False, True)
        Partner = self.env['res.partner'].with_user(self.manager).with_context(fitness_desk_new_contact=True)
        with self.assertRaises(UserError) as caught:
            Partner.name_create('Someone Else <%s>' % existing.email.upper())
        self.assertIn(existing.display_name, str(caught.exception))
        # Outside the desk's field nothing changes: she still cannot create a
        # contact at all.
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.manager).name_create('Other <%s>' % existing.email)

    def test_a_manager_without_contact_creation_creates_a_student_and_nothing_else(self):
        self.assertFalse(self.manager.has_group('base.group_partner_manager'), 'fixture: she must lack the right')
        Partner = self.env['res.partner'].with_user(self.manager)
        with self.assertRaises(AccessError):
            Partner.create({'name': 'DP Direct'})
        # Through the desk's field, with a default from the context that the
        # elevated create must not apply.
        pid, _n = Partner.with_context(fitness_desk_new_contact=True, default_comment='SMUGGLED',
                                       default_function='SMUGGLED').name_create('DP Desk New <dp.desknew@example.invalid>')
        p = self.env['res.partner'].browse(pid)
        self.assertEqual((p.name, p.email, p.phone), ('DP Desk New', 'dp.desknew@example.invalid', False))
        self.assertFalse(p.function)
        self.assertFalse(p.comment)
        self.assertEqual(p.create_uid, self.manager)
        q = Partner.fitness_desk_create_student('DP Phone', email='dp.phone@example.invalid', phone='600 000 000')
        self.assertEqual((q.name, q.email, q.phone), ('DP Phone', 'dp.phone@example.invalid', '600 000 000'))
        order, _w = self._sell(q, 'free')
        self.assertEqual(order.state, 'sale', 'a student created at the desk cannot be sold to')

    def test_instructors_and_members_cannot_create_a_student(self):
        member = self._contact(True, True)[1]
        for user in (self.teacher, member):
            with self.assertRaises(AccessError):
                self.env['res.partner'].with_user(user).fitness_desk_create_student(
                    'DP Nope', email='dp.nope@example.invalid')
        self.assertFalse(self.env['res.partner'].sudo().search([('email', '=', 'dp.nope@example.invalid')]))

    def test_an_app_cash_request_approved_at_the_desk_sends_both_mails_with_an_email_only(self):
        for email in (True, False):
            partner, _u = self._contact(False, email)
            order = self.env['sale.order'].sudo().create({
                'partner_id': partner.id, 'fitness_payment_method': 'cash',
                'fitness_cash_requested_on': fields.Datetime.now(),
                'order_line': [(0, 0, {'product_id': self.pack.product_variant_ids[:1].id,
                                       'product_uom_qty': 1, 'price_unit': 50.0})]})
            order.with_user(self.manager).action_fitness_approve_cash()
            self.assertEqual(order.state, 'sale')
            self.assertEqual(bool(self._confirmation_mails(order)), email, 'confirmation mail (email %s)' % email)
            self.assertEqual(order.invoice_ids.is_move_sent, email, 'invoice mail (email %s)' % email)

    def test_picking_a_contact_whose_email_is_shared_warns_and_sells(self):
        one, _u = self._contact(False, True)
        two = self.env['res.partner'].sudo().create({'name': 'DP Same Address', 'email': one.email})
        wiz = self.env['fitness.desk.sale.wizard'].with_user(self.manager).new({'partner_id': one.id})
        res = wiz._onchange_partner_shared_email()
        self.assertTrue(res and res.get('warning'), 'no warning for a shared email')
        self.assertIn(two.display_name, res['warning']['message'])
        order, _w = self._sell(one, 'cash')
        self.assertEqual(order.state, 'sale', 'the warning blocked the sale')

    # -- the card in the app ------------------------------------------------------------

    def _page(self, user, url, lang):
        user.lang = lang
        self.env.flush_all()
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, url)
        return html.unescape(res.text)

    def test_a_gift_card_says_when_it_ends_in_three_languages(self):
        partner, user = self._contact(True, True)
        gift, _w = self._sell(partner, 'free')
        paid_partner, paid_user = self._contact(True, True)
        paid, _w = self._sell(paid_partner, 'cash')
        for lang in ('en_US', 'es_ES', 'ca_ES'):
            tr = self.env(context=dict(self.env.context, lang=lang))._
            valid, billing, renewal = tr('Valid until'), tr('Next billing'), tr('Next renewal')
            ends = studio_date(self.env, gift._fitness_paid_up_to(), 'd MMM y', lang)
            for url in ('/my/history', '/my/subscription'):
                page = self._page(user, url, lang)
                self.assertIn(valid, page, '%s %s' % (lang, url))
                self.assertIn(ends, page, '%s %s' % (lang, url))
                self.assertNotIn(billing, page, '%s %s' % (lang, url))
                self.assertNotIn(renewal, page, '%s %s' % (lang, url))
            page = self._page(paid_user, '/my/history', lang)
            self.assertIn(billing, page, 'a paid membership lost its billing date (%s)' % lang)
            self.assertIn(renewal, self._page(paid_user, '/my/subscription', lang), lang)
        self.assertTrue(paid.invoice_ids)
