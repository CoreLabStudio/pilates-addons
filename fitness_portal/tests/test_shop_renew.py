# -*- coding: utf-8 -*-
"""Renew in the student shop, by the one renewal rule.

A plan she bought before shows Renew when it is time to renew - from the
renewal reminder (N days before its end, fitness.renewal_window_days) and
at any time after it has ended - and Active while it is running with more
days left. Renew is the normal checkout. A renewal of a membership still
running starts on the old end, so she loses no days, and the old one is
given that day as its end so nothing bills it again.
"""
import re
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, common, tagged

PW = 'Shop-renew-26'
RENEW = {'en_US': 'Renew', 'es_ES': 'Renovar', 'ca_ES': 'Renovar'}
BUY_NOW = {'en_US': 'Buy now', 'es_ES': 'Comprar ahora', 'ca_ES': 'Comprar ara'}


class RenewFixture:

    @classmethod
    def _fixture(cls):
        env = cls.env
        cls.today = fields.Date.context_today(env['res.users'])
        cls.month = env.ref('sale_subscription.subscription_plan_month')
        cls.plan = env['product.template'].create({
            'name': 'SR membership', 'list_price': 95.0, 'type': 'service', 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2, 'fitness_subscription_plan_id': cls.month.id})
        cls.pack = env['product.template'].create({
            'name': 'SR pack 5', 'list_price': 50.0, 'type': 'service', 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        cls.seq = 0

    def _student(self, lang='en_US'):
        type(self).seq += 1
        n = self.seq
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'SR Student %d' % n, 'login': 'sr.s%d@example.invalid' % n,
            'email': 'sr.s%d@example.invalid' % n, 'password': PW, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})

    def _membership(self, partner, ends_in_days, state=None):
        so = self.env['sale.order'].create({
            'partner_id': partner.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        if ends_in_days < 0:
            # An ended plan began before it ended (Odoo: next >= start).
            so.start_date = self.today + timedelta(days=ends_in_days - 30)
        so.next_invoice_date = self.today + timedelta(days=ends_in_days)
        if state:
            so.subscription_state = state
        return so

    def _pack(self, partner, ends_in_days, left=5):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': self.pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 50.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        so.order_line[:1].write({
            'fitness_validity_end_date': self.today + timedelta(days=ends_in_days),
            'fitness_remaining_classes': left})
        return so


@tagged('post_install', '-at_install')
class TestShopRenew(RenewFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        cls._fixture()

    def _login(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)

    def _renew_link(self, html, product):
        # Attribute order is QWeb's (static class before the computed href).
        href = 'href="/my/packages/%d/checkout"' % product.id
        return any(href in a for a in re.findall(r'<a[^>]*mv-btn-renew[^>]*>', html))

    def test_inside_the_window_the_shop_says_renew_in_each_language(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                u = self._student(lang)
                self._membership(u.partner_id, 2)
                self._login(u, lang)
                html = self.url_open('/my/packages?tab=subscriptions').text
                self.assertTrue(self._renew_link(html, self.plan), 'no Renew button: %s' % re.findall(r'<a[^>]*/my/packages/%d/[^>]*>[^<]*' % self.plan.id, html)[:4])
                self.assertIn('>%s<' % RENEW[lang], html)

    def test_outside_the_window_it_is_active_with_no_button(self):
        u = self._student()
        self._membership(u.partner_id, 10)
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=subscriptions').text
        self.assertFalse(self._renew_link(html, self.plan), 'Renew offered on a running plan')
        self.assertNotIn('/my/packages/%d/checkout' % self.plan.id, html,
                         'a running plan can still be bought from its card')

    def test_an_ended_membership_says_renew(self):
        u = self._student()
        self._membership(u.partner_id, -5, state='6_churn')
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=subscriptions').text
        self.assertTrue(self._renew_link(html, self.plan))

    def test_a_pack_near_its_end_says_renew(self):
        u = self._student()
        self._pack(u.partner_id, 2)
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=packages').text
        self.assertTrue(self._renew_link(html, self.pack))

    def test_never_held_still_says_buy(self):
        u = self._student()
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=subscriptions').text
        self.assertFalse(self._renew_link(html, self.plan))
        self.assertIn('/my/packages/%d/checkout' % self.plan.id, html)

    def test_the_product_page_offers_renew_and_buy_now_still_translates(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                u = self._student(lang)
                self._membership(u.partner_id, 2)
                self._login(u, lang)
                html = self.url_open('/my/packages/%d' % self.plan.id).text
                self.assertTrue(self._renew_link(html, self.plan), 'no Renew on the page')
                fresh = self._student(lang)
                self._login(fresh, lang)
                html = self.url_open('/my/packages/%d' % self.pack.id).text
                self.assertIn(BUY_NOW[lang], html, 'Buy now lost its translation')

    def test_checkout_allows_a_first_purchase_a_renewal_and_a_plan_not_held(self):
        other = self.env['product.template'].create({
            'name': 'SR other membership', 'list_price': 120.0, 'type': 'service', 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 3, 'fitness_subscription_plan_id': self.month.id})
        first = self._student()
        renewer = self._student()
        self._membership(renewer.partner_id, 2)
        holder = self._student()
        self._membership(holder.partner_id, 10)
        for who, product, why in ((first, self.plan, 'a first purchase'),
                                  (renewer, self.plan, 'a renewal inside the window'),
                                  (holder, other, 'a plan she does not hold')):
            with self.subTest(case=why):
                self._login(who, 'en_US')
                r = self.url_open('/my/packages/%d/checkout' % product.id)
                self.assertEqual(r.status_code, 200, why)
                self.assertIn('/checkout', r.url, '%s was refused: %s' % (why, r.url))

    def test_checkout_refuses_a_running_plan_or_pack_outside_the_window(self):
        u = self._student()
        self._membership(u.partner_id, 10)
        self._pack(u.partner_id, 10)
        self._login(u, 'en_US')
        for product in (self.plan, self.pack):
            with self.subTest(product=product.name):
                r = self.url_open('/my/packages/%d/checkout' % product.id)
                self.assertNotIn('/checkout', r.url, '%s was sold again while running' % product.name)

    def test_an_ended_plan_waiting_for_closure_says_renew(self):
        """End date passed, still marked running until Odoo's weekly expiry
        job: Renew on the card, and the checkout goes ahead."""
        u = self._student()
        so = self._membership(u.partner_id, 10)
        so.end_date = self.today - timedelta(days=1)
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=subscriptions').text
        self.assertTrue(self._renew_link(html, self.plan), 'an ended plan shows no Renew')
        r = self.url_open('/my/packages/%d/checkout' % self.plan.id)
        self.assertIn('/checkout', r.url, 'an ended plan could not be bought back: %s' % r.url)

    def test_a_paused_membership_is_not_sold_again(self):
        u = self._student()
        so = self._membership(u.partner_id, 10)
        so.subscription_state = '4_paused'
        self._login(u, 'en_US')
        html = self.url_open('/my/packages?tab=subscriptions').text
        self.assertNotIn('/my/packages/%d/checkout' % self.plan.id, html,
                         'a paused membership offered Buy')
        r = self.url_open('/my/packages/%d/checkout' % self.plan.id)
        self.assertNotIn('/checkout', r.url, 'a paused membership was sold again')

    def test_checkout_refuses_a_running_plan_outside_the_window(self):
        u = self._student()
        self._membership(u.partner_id, 10)
        self._login(u, 'en_US')
        r = self.url_open('/my/packages/%d/checkout' % self.plan.id)
        self.assertNotIn('/checkout', r.url, 'the checkout sold a plan that is still running')
        self.assertIn('/my/packages/%d' % self.plan.id, r.url)

    def test_checkout_goes_ahead_inside_the_window(self):
        u = self._student()
        self._membership(u.partner_id, 2)
        self._login(u, 'en_US')
        r = self.url_open('/my/packages/%d/checkout' % self.plan.id)
        self.assertEqual(r.status_code, 200)
        self.assertIn('/checkout', r.url)


@tagged('post_install', '-at_install')
class TestRenewalContinuesFromTheOldEnd(RenewFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()

    def _buy_again(self, partner):
        so = self.env['sale.order'].create({
            'partner_id': partner.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        return so

    def test_a_renewal_inside_the_window_starts_on_the_old_end(self):
        p = self._student().partner_id
        old = self._membership(p, 2)
        new = self._buy_again(p)
        self.assertEqual(new.start_date, old.next_invoice_date, 'she lost days')
        self.assertEqual(old.end_date, new.start_date - timedelta(days=1),
                         'the old plan was left to be billed again')

    def test_a_renewal_after_the_end_starts_today(self):
        p = self._student().partner_id
        old = self._membership(p, -5, state='6_churn')
        new = self._buy_again(p)
        self.assertEqual(new.start_date, self.today)
        self.assertFalse(old.end_date)

    def test_outside_the_window_nothing_is_moved(self):
        p = self._student().partner_id
        old = self._membership(p, 10)
        new = self._buy_again(p)
        self.assertEqual(new.start_date, self.today)
        self.assertFalse(old.end_date)


@tagged('post_install', '-at_install')
class TestRenewalAndOdoosBillingJob(RenewFixture, TransactionCase):
    """Renewed inside the window, then Odoo's own billing and expiry jobs run
    on the old plan's end date and well past its closing limit: the old plan
    is not invoiced again, and the renewed plan is not closed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()
        # Production takes the money into its cash journal; the test company
        # has none, and an invoice left unpaid is closed by Odoo after its
        # limit whatever this batch does.
        if not cls.env['account.journal'].search([
                ('type', '=', 'cash'), ('company_id', '=', cls.env.company.id)], limit=1):
            cls.env['account.journal'].create({'name': 'SR Cash', 'type': 'cash', 'code': 'SRCSH'})

    def test_no_third_invoice_and_no_closure_after_a_renewal(self):
        p = self._student().partner_id
        start = self.today + timedelta(days=2) - relativedelta(months=1)
        old = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id, 'start_date': start,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        old.with_context(skip_fitness_notification=True).action_confirm()
        inv = old._create_invoices()
        inv.action_post()
        old.fitness_settle_invoice_in_cash(inv)        # month one paid
        self.assertEqual(old.next_invoice_date, self.today + timedelta(days=2),
                         'fixture: month one paid, ending in 2 days')
        new = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        new.with_context(skip_fitness_notification=True).action_confirm()
        inv = new._create_invoices()
        inv.action_post()
        new.fitness_settle_invoice_in_cash(inv)        # paid, as a card or cash renewal is
        self.assertEqual(new.start_date, old.next_invoice_date)
        posted = lambda so: so.invoice_ids.filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        old_n, new_n = len(posted(old)), len(posted(new))
        SO = self.env['sale.order']
        for day in (new.start_date, new.start_date + timedelta(days=20)):
            with common.freeze_time(day):
                SO._cron_recurring_create_invoice()
                SO._cron_subscription_expiration()
        old.invalidate_recordset()
        new.invalidate_recordset()
        self.assertEqual(len(posted(old)), old_n, 'the old plan was invoiced again')
        self.assertEqual(len(posted(new)), new_n, 'the renewed plan was invoiced early')
        self.assertEqual(new.subscription_state, '3_progress',
                         'the renewed plan was closed: reason %s, end %s, next %s, invoices %s' % (
                             new.close_reason_id.name, new.end_date, new.next_invoice_date,
                             [(m.name, m.payment_state) for m in posted(new)]))
        self.assertNotEqual(old.subscription_state, '3_progress',
                            'the old plan was left running past its end')

    # -- D1: a renewal on or after the old end ------------------------------

    def _old_paid(self, ends_in_days):
        """Month one paid; its next billing date ends_in_days from today."""
        p = self._student().partner_id
        nxt = self.today + timedelta(days=ends_in_days)
        old = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id,
            'start_date': nxt - relativedelta(months=1),
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        old.with_context(skip_fitness_notification=True).action_confirm()
        inv = old._create_invoices()
        inv.action_post()
        old.fitness_settle_invoice_in_cash(inv)
        self.assertEqual(old.next_invoice_date, nxt, 'fixture')
        return p, old

    def _paid_renewal(self, p):
        new = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        new.with_context(skip_fitness_notification=True).action_confirm()
        inv = new._create_invoices()
        inv.action_post()
        new.fitness_settle_invoice_in_cash(inv)
        return new

    def _jobs_then_assert(self, old, new):
        posted = lambda so: so.invoice_ids.filtered(
            lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
        Tx = self.env['payment.transaction'].sudo()
        old_n, new_n = len(posted(old)), len(posted(new))
        old_tx = Tx.search_count([('sale_order_ids', 'in', old.ids)])
        SO = self.env['sale.order']
        for day in (self.today, self.today + timedelta(days=20)):
            with common.freeze_time(day):
                SO._cron_recurring_create_invoice()
                SO._cron_subscription_expiration()
        old.invalidate_recordset()
        new.invalidate_recordset()
        self.assertEqual(len(posted(old)), old_n, 'the old plan was invoiced again')
        self.assertEqual(Tx.search_count([('sale_order_ids', 'in', old.ids)]), old_tx,
                         'a payment was attempted on the old plan')
        self.assertEqual(len(posted(new)), new_n, 'the renewal was invoiced early')
        self.assertEqual(new.subscription_state, '3_progress', 'the renewal was closed')
        self.assertNotEqual(old.subscription_state, '3_progress',
                            'the old plan was left running: end %s' % old.end_date)

    def test_renewal_on_the_end_day(self):
        p, old = self._old_paid(0)
        new = self._paid_renewal(p)
        self.assertEqual(new.start_date, self.today)
        self.assertEqual(old.end_date, self.today - timedelta(days=1))
        self._jobs_then_assert(old, new)

    def test_renewal_while_overdue(self):
        p, old = self._old_paid(-3)
        new = self._paid_renewal(p)
        self.assertEqual(new.start_date, self.today)
        self.assertEqual(old.end_date, self.today - timedelta(days=4),
                         'the old plan must end on its last paid day')
        self._jobs_then_assert(old, new)

    def test_a_cash_request_approved_after_the_end(self):
        p, old = self._old_paid(-2)
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'SR Desk', 'login': 'sr.desk.%d@example.invalid' % old.id,
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('fitness_core.group_fitness_manager').id])]})
        req = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id,
            'fitness_payment_method': 'cash',
            'fitness_cash_requested_on': fields.Datetime.now() - timedelta(days=4),
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        # The approval settles the invoice once, and logs no ERROR doing it.
        with self.assertNoLogs('odoo.addons.fitness_portal.models.sale_order', level='ERROR'):
            req.with_user(manager).action_fitness_approve_cash()
        self.assertEqual(req.state, 'sale')
        # One payment, invoice paid - what a real approval leaves behind.
        inv = req.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv.payment_state in ('paid', 'in_payment'), True, inv.payment_state)
        self.assertEqual(len(inv._get_reconciled_payments()), 1,
                         'the approval did not leave exactly one payment')
        self.assertEqual(req.start_date, self.today)
        self.assertEqual(old.end_date, self.today - timedelta(days=3))
        self._jobs_then_assert(old, req)

    # -- D4: a renewal waiting for its payment ------------------------------

    def test_a_renewal_waiting_for_payment_is_not_renewable_again(self):
        p, old = self._old_paid(2)
        new = self.env['sale.order'].create({
            'partner_id': p.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        new.with_context(skip_fitness_notification=True).action_confirm()   # no invoice yet
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'active',
                         'a renewal waiting for its payment offered Renew again')

    # -- Odoo's weekly expiry job (34) on its own ----------------------------

    def test_job_34_closes_the_old_plan_and_keeps_the_renewal(self):
        """Production runs only job 34 (expiry); invoicing (35) is off.
        After a renewal gives the old plan its end date, job 34 run the day
        after that end closes the old plan and leaves the renewal running."""
        p, old = self._old_paid(2)
        new = self._paid_renewal(p)
        self.assertEqual(old.end_date, self.today + timedelta(days=1))
        with common.freeze_time(old.end_date + timedelta(days=1)):
            self.env['sale.order']._cron_subscription_expiration()
        old.invalidate_recordset()
        new.invalidate_recordset()
        self.assertEqual(old.subscription_state, '6_churn',
                         'job 34 left the old plan running: %s' % old.subscription_state)
        self.assertEqual(new.subscription_state, '3_progress',
                         'job 34 closed the renewal: %s' % new.subscription_state)

    # -- E2: a plan with an end date, before its next bill -------------------

    def test_ended_ending_and_replaced_plans(self):
        """Ended (end passed, nothing after it): renewable. Ending (end today
        or later): not renewable - D4 unchanged. Replaced (end passed, its
        renewal running): the renewal decides, not the old plan."""
        p = self._student().partner_id
        ended = self._membership(p, 10)
        ended.end_date = self.today - timedelta(days=1)
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'renewable',
                         'an ended plan could not be bought back')
        p2 = self._student().partner_id
        ending = self._membership(p2, 10)
        ending.end_date = self.today + timedelta(days=5)
        self.assertEqual(p2._fitness_renewal_state(self.plan)['state'], 'active',
                         'a plan still running to its end date was offered Renew')
        p3, old = self._old_paid(-3)
        new = self._paid_renewal(p3)              # old.end_date = its last paid day
        self.assertTrue(old.end_date and old.end_date < self.today)
        st = p3._fitness_renewal_state(self.plan)
        self.assertEqual(st['order'], new, 'the replaced plan, not its renewal, was read')
        self.assertEqual(st['state'], 'active', 'a renewed plan was offered Renew again')
