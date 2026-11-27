# -*- coding: utf-8 -*-
"""The registration fee comes back 30 days after the last paid day.

The studio's rule (Nov 2026): a member who has not renewed has 30 days
after her last paid day to renew without the fee. A renewal starting on
day 30 carries none; day 31 does. It applies to everyone, including members
who left before the rule existed, and it never touches a commitment of
three months or more, which waives the fee as before.

Covered on every path that builds the lines: the rule itself, the app
checkout over HTTP, the desk's Renew (cash) of a closed membership, and
the desk sale - plus a free gift, which stays 0.00 with no fee line, and
the fee's own price, 39.00 gross under a price-included tax.

Dates are built from the studio's real today and the last paid day is
written directly, so nothing here depends on month lengths or the clock
change.
"""
import re
from datetime import timedelta

from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_core.models.studio_time import studio_today
from odoo.addons.fitness_subscriptions.models.membership_dates import FEE_WINDOW_DAYS

MATRICULA = 'fitness_subscriptions.product_matricula'
MANAGER = 'fitness_core.group_fitness_manager'
STUDENT = 'fitness_core.group_fitness_student'
PW = 'fee30-pw-1'


@tagged('post_install', '-at_install')
class TestFeeAfterThirtyDays(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.today = studio_today()
        cls.matricula = env.ref(MATRICULA).sudo()
        cls.matricula.active = True
        tax = cls.matricula.taxes_id.filtered(lambda t: t.company_id == env.company)[:1]
        if not tax or tax.price_include_override != 'tax_included':
            tax = env['account.tax'].sudo().create({
                'name': 'Fee30 IVA 21% incl', 'amount_type': 'percent', 'amount': 21.0,
                'type_tax_use': 'sale', 'price_include_override': 'tax_included',
                'company_id': env.company.id})
            cls.matricula.write({'taxes_id': [(6, 0, tax.ids)]})
        Plan = env['sale.subscription.plan'].sudo()
        cls.monthly = Plan.create({'name': 'Fee30 Mensual', 'billing_period_value': 1,
                                   'billing_period_unit': 'month'})
        cls.quarterly = Plan.create({'name': 'Fee30 Trimestral', 'billing_period_value': 3,
                                     'billing_period_unit': 'month'})
        cls.membership = env['product.template'].sudo().create({
            'name': 'Fee30 Barre', 'type': 'service', 'list_price': 95.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2, 'fitness_subscription_plan_id': cls.monthly.id,
            'taxes_id': [(6, 0, tax.ids)]})
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Fee30 Manager', 'login': 'fee30.manager@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref(MANAGER).id,
                                  env.ref('sales_team.group_sale_manager').id,
                                  env.ref('account.group_account_invoice').id])]})
        if not env['account.journal'].sudo().search(
                [('type', '=', 'cash'), ('company_id', '=', env.company.id)], limit=1):
            env['account.journal'].sudo().create({
                'name': 'Fee30 Cash', 'code': 'F30C', 'type': 'cash', 'company_id': env.company.id})
        cls.seq = 0

    # -- fixtures ------------------------------------------------------------

    def _member(self):
        type(self).seq += 1
        n = self.seq
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Fee30 Member %d' % n, 'login': 'fee30.m%d@example.invalid' % n,
            'email': 'fee30.m%d@example.invalid' % n, 'password': PW, 'lang': 'en_US',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref(STUDENT).id])]})

    def _ended(self, partner, days_ago):
        """A paid membership whose last paid day was `days_ago` days ago,
        closed the way the daily job closes it."""
        last = self.today - timedelta(days=days_ago)
        so = self.env['sale.order'].sudo().create({
            'partner_id': partner.id, 'plan_id': self.monthly.id,
            'start_date': last - timedelta(days=29),
            'order_line': [(0, 0, {'product_id': self.membership.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        so.next_invoice_date = last + timedelta(days=1)
        so.set_close(close_reason_id=self.env.ref('fitness_portal.close_reason_membership_ended').id)
        so.end_date = last
        self.assertEqual(so._fitness_paid_up_to(), last)
        return so

    def _due(self, partner, plan=None):
        return bool(self.membership.fitness_matricula_due(partner, plan or self.monthly))

    def _fee_lines(self, order):
        return order.order_line.filtered(lambda l: l.product_id.product_tmpl_id == self.matricula)

    # -- the rule --------------------------------------------------------------

    def test_day_29_and_30_carry_no_fee_and_day_31_does(self):
        for days, due in ((29, False), (FEE_WINDOW_DAYS, False), (FEE_WINDOW_DAYS + 1, True)):
            p = self._member().partner_id
            self._ended(p, days)
            self.assertEqual(self._due(p), due, 'day %d' % days)

    def test_a_three_month_plan_waives_it_on_day_31(self):
        p = self._member().partner_id
        self._ended(p, FEE_WINDOW_DAYS + 1)
        self.assertFalse(self._due(p, self.quarterly))

    def test_a_member_who_left_long_before_today_pays_it(self):
        p = self._member().partner_id
        self._ended(p, 200)
        self.assertTrue(self._due(p))

    def test_a_first_time_member_pays_it_as_before(self):
        self.assertTrue(self._due(self._member().partner_id))

    def test_a_running_member_and_one_waiting_for_her_first_payment_do_not(self):
        p = self._member().partner_id
        self._ended(p, 300)
        running = self.env['sale.order'].sudo().create({
            'partner_id': p.id, 'plan_id': self.monthly.id, 'start_date': self.today,
            'order_line': [(0, 0, {'product_id': self.membership.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        running.with_context(skip_fitness_notification=True).action_confirm()
        self.assertFalse(self._due(p), 'waiting for its first payment: still a member')
        running.next_invoice_date = self.today + timedelta(days=20)
        self.assertFalse(self._due(p), 'paid and running')

    def test_the_most_recent_membership_counts(self):
        p = self._member().partner_id
        self._ended(p, 400)
        self._ended(p, 10)
        self.assertFalse(self._due(p))

    def test_the_fee_is_39_gross_under_the_included_tax(self):
        p = self._member().partner_id
        self._ended(p, FEE_WINDOW_DAYS + 1)
        lines = self.membership.fitness_order_line_vals(p, plan=self.monthly)
        order = self.env['sale.order'].sudo().create({
            'partner_id': p.id, 'plan_id': self.monthly.id})
        order.write({'order_line': [(0, 0, v) for v in lines]})
        fee = self._fee_lines(order)
        self.assertEqual(len(fee), 1)
        self.assertAlmostEqual(fee.price_total, self.matricula.fitness_effective_price(), places=2)
        self.assertAlmostEqual(fee.price_total, 39.0, places=2)

    # -- the app checkout, over HTTP ---------------------------------------------

    def _checkout(self, user):
        self.authenticate(user.login, PW)
        url = '/my/packages/%d/checkout?plan_id=%d' % (self.membership.id, self.monthly.id)
        page = self.url_open(url, timeout=30)
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        self.assertTrue(tok, 'no checkout form for a returning member')
        self.url_open('/my/packages/%d/checkout' % self.membership.id, data={
            'csrf_token': tok.group(1), 'payment_method': 'cash', 'terms_accepted': '1',
            'plan_id': self.monthly.id}, timeout=30)
        return self.env['sale.order'].sudo().search(
            [('partner_id', '=', user.partner_id.id), ('state', '=', 'draft')], order='id desc', limit=1)

    def test_app_checkout_charges_it_on_day_31_only(self):
        for days, charged in ((FEE_WINDOW_DAYS, False), (FEE_WINDOW_DAYS + 1, True)):
            user = self._member()
            self._ended(user.partner_id, days)
            self.env.flush_all()
            order = self._checkout(user)
            self.assertTrue(order, 'checkout created no order (day %d)' % days)
            self.assertEqual(bool(self._fee_lines(order)), charged, 'day %d' % days)

    # -- the desk's Renew (cash) of a closed membership ---------------------------

    def test_desk_renew_after_close_charges_it_on_day_31_only(self):
        for days, charged in ((FEE_WINDOW_DAYS, False), (FEE_WINDOW_DAYS + 1, True)):
            p = self._member().partner_id
            closed = self._ended(p, days)
            closed.with_user(self.manager).sudo()._fitness_renew_cash_after_close()
            new = self.env['sale.order'].sudo().search(
                [('partner_id', '=', p.id), ('id', '>', closed.id)], limit=1)
            self.assertEqual(bool(self._fee_lines(new)), charged, 'day %d' % days)
            if charged:
                self.assertAlmostEqual(self._fee_lines(new).price_total, 39.0, places=2)

    # -- the desk sale --------------------------------------------------------------

    def _desk(self, partner, method):
        Wizard = self.env['fitness.desk.sale.wizard'].with_user(self.manager)
        w = Wizard.create({'partner_id': partner.id, 'product_id': self.membership.id,
                           'plan_id': self.monthly.id, 'payment_method': method})
        if method == 'cash':
            w.amount_paid = w.normal_price
        else:
            w.reason = 'Fee30 gift'
        return w

    def test_desk_cash_sale_charges_it_on_day_31_and_says_why(self):
        p = self._member().partner_id
        self._ended(p, FEE_WINDOW_DAYS + 1)
        w = self._desk(p, 'cash')
        self.assertAlmostEqual(w.matricula_fee, 39.0, places=2)
        self.assertIn(str(FEE_WINDOW_DAYS), w.matricula_note)
        w.action_create_sale()
        order = self.env['sale.order'].sudo().search([('partner_id', '=', p.id)], order='id desc', limit=1)
        self.assertEqual(len(self._fee_lines(order)), 1)
        self.assertAlmostEqual(order.amount_total, w.amount_paid, places=2)

    def test_desk_cash_sale_on_day_30_carries_none(self):
        p = self._member().partner_id
        self._ended(p, FEE_WINDOW_DAYS)
        w = self._desk(p, 'cash')
        self.assertFalse(w.matricula_fee)

    def test_a_free_gift_on_day_31_is_0_with_no_fee_line(self):
        p = self._member().partner_id
        self._ended(p, FEE_WINDOW_DAYS + 1)
        w = self._desk(p, 'free')
        w.action_create_sale()
        order = self.env['sale.order'].sudo().search([('partner_id', '=', p.id)], order='id desc', limit=1)
        self.assertEqual(order.amount_total, 0.0)
        self.assertFalse(self._fee_lines(order))
