# -*- coding: utf-8 -*-
"""A membership closes the day after its last paid day, and she is told.

Odoo's own expiry job (sale_subscription, weekly) closes a plan with an end
date up to seven days late, and a plan with no end date only when its next
billing date is fifteen days gone (auto_close_limit): sixteen to twenty-two
days in which the membership is still "In Progress", still in
_fitness_live_membership_domain, and still pays for classes nobody paid
for. And it tells her nothing - it writes only to the salesperson, and only
about an unpaid invoice, which with Odoo's recurring invoicing switched off
on this database never exists.

So, every day:

  * a membership whose end date has passed is closed - a renewal sets that
    date to her last paid day (fitness_subscriptions/models/renewal.py);
  * a membership with no end date whose next billing date has come, with a
    grace of fitness.close_grace_days (default 0), is closed and its end
    date set to her last paid day.

A plan never billed for its first period (a purchase confirmed and waiting
for a transfer) is not "lapsed": it has no paid day to close after.

She is told once, in her language, with the way back - unless she has
already acted. A renewal that is paid: never. A renewal asked for and not
settled yet - cash waiting at the desk, a transfer, a card or Bizum payment
still pending: not yet. The message goes when that request is declined, or
when it is still unsettled fitness.expired_notice_wait_days (default 3)
after the later of the request and the close.

Classes already booked after the end are left booked and named in the
chatter: cancelling a class she may be about to pay for is the studio's
call, not a job's.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.fitness_core.models.studio_lang import (
    recipient_lang, studio_date, studio_datetime, studio_lang)
from odoo.addons.fitness_core.models.studio_time import studio_today

_logger = logging.getLogger(__name__)

CLOSE_GRACE_PARAM = 'fitness.close_grace_days'
CLOSE_GRACE_DEFAULT = 0
EXPIRED_WAIT_PARAM = 'fitness.expired_notice_wait_days'
EXPIRED_WAIT_DEFAULT = 3
# How far back a closed plan is still waiting for its message. Past this, a
# plan closed and never told stays untold: a message about a month-old end
# is news to nobody.
EXPIRED_LOOKBACK_DAYS = 30
EXPIRED_URL = '/my/packages?tab=subscriptions'


class FitnessNotificationExpired(models.Model):
    _inherit = 'fitness.notification'

    notification_type = fields.Selection(
        selection_add=[('membership_expired', 'Membership Expired')],
        ondelete={'membership_expired': 'cascade'})


class SaleOrderClose(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _fitness_days_param(self, key, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        try:
            days = int(raw) if raw not in (None, False, '') else default
        except (TypeError, ValueError):
            days = default
        return max(0, days)

    @api.model
    def _fitness_memberships_to_close(self, today):
        grace = self._fitness_days_param(CLOSE_GRACE_PARAM, CLOSE_GRACE_DEFAULT)
        running = self.sudo().search([
            ('is_subscription', '=', True),
            ('state', '=', 'sale'),
            ('subscription_state', '=', '3_progress'),
            ('fitness_subscription_product_id', '!=', False),
        ])
        return running.filtered(lambda s: (
            (s.end_date and s.end_date < today)
            or (not s.end_date and s.next_invoice_date and s.start_date
                and s.next_invoice_date > s.start_date
                and s.next_invoice_date + timedelta(days=grace) <= today)))

    def _fitness_same_plan_orders(self):
        """Her other orders for this plan's product, made after this one."""
        self.ensure_one()
        tmpl = self.fitness_subscription_product_id.product_tmpl_id
        return self.env['sale.order'].sudo().search([
            ('partner_id', '=', self.partner_id.id),
            ('id', '>', self.id),
            ('order_line.product_id.product_tmpl_id', '=', tmpl.id),
        ])

    def _fitness_paid_successor(self):
        self.ensure_one()
        return self._fitness_same_plan_orders().filtered(lambda s: (
            s.is_subscription and s.state == 'sale'
            and s.subscription_state in ('3_progress', '4_paused')
            and s.next_invoice_date and s.start_date
            and s.next_invoice_date > s.start_date))[:1]

    def _fitness_pending_successors(self):
        """Requests to carry this plan on that are not settled yet, each with
        the moment it was made: cash waiting at the desk, a card or Bizum
        payment still pending, a transfer confirmed and not yet paid."""
        self.ensure_one()
        out = []
        for o in self._fitness_same_plan_orders():
            if o.state in ('draft', 'sent'):
                if o.fitness_cash_pending:
                    out.append((o, o.fitness_cash_requested_on))
                    continue
                pending = o.transaction_ids.filtered(lambda t: t.state == 'pending')
                if pending:
                    out.append((o, max(pending.mapped('create_date'))))
            elif (o.state == 'sale' and o.is_subscription
                  and o.subscription_state == '3_progress'
                  and o.next_invoice_date and o.start_date
                  and o.next_invoice_date <= o.start_date):
                out.append((o, o.date_order))
        return out

    def _fitness_expired_notice_due(self, today):
        """True, False, or the pending request she is still waiting on."""
        self.ensure_one()
        if self._fitness_paid_successor():
            return False
        pending = self._fitness_pending_successors()
        if not pending:
            return True
        wait = self._fitness_days_param(EXPIRED_WAIT_PARAM, EXPIRED_WAIT_DEFAULT)
        closed_on = (self.end_date or today) + timedelta(days=1)
        asked_on = max(fields.Date.to_date(at) if at else closed_on for _o, at in pending)
        if today >= max(asked_on, closed_on) + timedelta(days=wait):
            return True
        return pending[-1][0]

    def _fitness_told_expired(self):
        self.ensure_one()
        user = self.partner_id.user_ids[:1]
        if not user or not self.end_date:
            return False
        return bool(self.env['fitness.notification'].sudo().search_count([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'membership_expired'),
            ('create_date', '>=', fields.Datetime.to_datetime(self.end_date)),
        ]))

    def _fitness_send_expired(self):
        self.ensure_one()
        user = self.partner_id.user_ids[:1]
        if not user:
            return False
        lang = recipient_lang(self.env, user)
        env = self.with_context(lang=lang).env
        plan = self.fitness_subscription_product_id.with_context(lang=lang).name or self.name
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id, 'membership_expired',
            env._('Your membership has ended'),
            env._('Your %(plan)s membership ended on %(date)s. Renew it in the '
                  'app to keep booking your classes.',
                  plan=plan, date=studio_date(self.env, self.end_date, 'd MMM y', lang)),
            action_url=EXPIRED_URL)
        return True

    def _fitness_close_ended(self, today):
        reason = self.env.ref('fitness_portal.close_reason_membership_ended')
        for so in self.sudo():
            if not so.end_date:
                so.end_date = so.next_invoice_date - timedelta(days=1)
            so.set_close(close_reason_id=reason.id)
            later = self.env['fitness.booking'].sudo().search([
                ('subscription_id', '=', so.id),
                ('state', '!=', 'cancelled'),
                ('class_start', '>=', fields.Datetime.to_datetime(so.end_date + timedelta(days=1))),
            ], order='class_start')
            # For the studio, so in the studio's language.
            lang = studio_lang(self.env)
            env = self.with_context(lang=lang).env
            end = studio_date(self.env, so.end_date, 'd MMM y', lang)
            note = env._('Closed: the membership ended on %(date)s, its last paid day.',
                         date=end)
            if later:
                note += ' ' + env._(
                    '%(count)s class(es) booked after that day were left booked: '
                    '%(classes)s. Cancel them if she does not renew.',
                    count=len(later), classes=', '.join(
                        studio_datetime(self.env, b.class_start, 'd MMM y HH:mm', lang) for b in later))
            so.message_post(body=note, subtype_xmlid='mail.mt_note')

    @api.model
    def _cron_fitness_close_ended_memberships(self, today=None):
        today = today or studio_today()
        to_close = self._fitness_memberships_to_close(today)
        to_close._fitness_close_ended(today)
        # Told now, or later once what she asked for is settled one way or
        # the other. Closed by this job and not told yet, within the window.
        reason = self.env.ref('fitness_portal.close_reason_membership_ended')
        closed = self.sudo().search([
            ('is_subscription', '=', True),
            ('subscription_state', '=', '6_churn'),
            ('close_reason_id', '=', reason.id),
            ('end_date', '>=', today - timedelta(days=EXPIRED_LOOKBACK_DAYS)),
        ])
        told = 0
        for so in closed:
            if so._fitness_told_expired():
                continue
            due = so._fitness_expired_notice_due(today)
            if due is True and so._fitness_send_expired():
                told += 1
        _logger.info("[CLOSE] closed %d membership(s), told %d student(s)",
                     len(to_close), told)
        return to_close
