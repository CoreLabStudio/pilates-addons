# -*- coding: utf-8 -*-
"""A membership that starts on the 30th or 31st renews without losing or doubling a day.

The QA seed tripped on 31 Oct 2026: "31 Oct minus one month" is 30 Sep, and
30 Sep plus one month is 30 Oct, not 31 Oct. That was the seed's own
arithmetic; this proves what the product does. A member pays month by month
in cash at the desk (Renew (cash), inside the window), across short and long
months, and every new period must start on the day the last one ended -
no gap she is not covered for, no overlap she pays twice - and each must be
one billing month long. The dates are logged, so the run itself is the proof.
Then the daily close job closes a lapsed month-end membership the day after
its last paid day.
"""
import logging
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, common, tagged

_logger = logging.getLogger(__name__)


def at(d, hour=10):
    return datetime(d.year, d.month, d.day, hour - 1, 0)   # 10:00 Madrid in winter, 11:00 in summer: always that day


@tagged('post_install', '-at_install')
class TestMonthEndRenewal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.plan = env.ref('sale_subscription.subscription_plan_month')
        cls.product = env.ref('fitness_subscriptions.product_barre_clase_fija_1')
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'ME Manager', 'login': 'me.manager@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('fitness_core.group_fitness_manager').id])]})
        if not env['account.journal'].sudo().search(
                [('type', '=', 'cash'), ('company_id', '=', env.company.id)]):
            env['account.journal'].sudo().create(
                {'name': 'ME Cash', 'code': 'MEC', 'type': 'cash', 'company_id': env.company.id})

    def _member(self, start, tag):
        with common.freeze_time(at(start)):
            partner = self.env['res.partner'].create({'name': 'ME %s' % tag})
            so = self.env['sale.order'].sudo().create(
                {'partner_id': partner.id, 'plan_id': self.plan.id, 'start_date': start})
            self.env['sale.order.line'].sudo().create({
                'order_id': so.id, 'product_id': self.product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 65.0})
            so.with_context(skip_fitness_notification=True).action_confirm()
            so._create_invoices().action_post()
        return so

    def _renew_months(self, so, months):
        periods = [(so.start_date, so.next_invoice_date)]
        for _i in range(months):
            old_next = so.next_invoice_date
            with common.freeze_time(at(old_next - timedelta(days=1))):
                so.with_user(self.manager).action_fitness_renew_cash()
            so.invalidate_recordset()
            periods.append((so.fitness_period_start_date, so.next_invoice_date))
            self.assertEqual(so.fitness_period_start_date, old_next,
                             'the new period did not start the day the last one ended')
        return periods

    def _check(self, periods, label):
        _logger.info('%s: %s', label, ' | '.join('%s -> %s' % (a, b - timedelta(days=1)) for a, b in periods))
        for (a, b), (c, _d) in zip(periods, periods[1:]):
            self.assertEqual(c, b, '%s: gap or overlap between %s and %s' % (label, b, c))
        for a, b in periods:
            self.assertEqual(b, a + relativedelta(months=1),
                             '%s: %s -> %s is not one billing month' % (label, a, b))

    def test_from_the_31st(self):
        so = self._member(date(2026, 8, 31), '31aug')
        self._check(self._renew_months(so, 6), 'start 31 Aug')   # Sep, Oct, Nov, Dec, Jan, Feb

    def test_from_the_30th(self):
        so = self._member(date(2026, 9, 30), '30sep')
        self._check(self._renew_months(so, 5), 'start 30 Sep')

    def test_the_close_job_on_a_month_end(self):
        so = self._member(date(2026, 9, 30), 'close')
        nid = so.next_invoice_date
        last_paid = nid - timedelta(days=1)
        with common.freeze_time(at(last_paid)):
            self.env['sale.order']._cron_fitness_close_ended_memberships()
        self.assertEqual(so.subscription_state, '3_progress', 'closed on her last paid day')
        with common.freeze_time(at(nid)):
            self.env['sale.order']._cron_fitness_close_ended_memberships()
        self.assertEqual(so.subscription_state, '6_churn', 'not closed the day after her last paid day')
        self.assertEqual(so.end_date, last_paid)
        _logger.info('close job: paid to %s, closed on %s, end_date %s', last_paid, nid, so.end_date)
