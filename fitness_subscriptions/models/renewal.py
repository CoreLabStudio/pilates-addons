# -*- coding: utf-8 -*-
"""Is this plan renewable now? One answer for the shop, the desk and the reminder.

The studio's rule (owner, 14 Oct): a plan she bought before can be renewed
from the moment the renewal reminder goes out - a window of N days before
it ends - and at any time after it has ended. A plan with more days left
than that is simply Active. The window is one system parameter,
fitness.renewal_window_days (default 3), read by the renewal reminder as
well, so the reminder never invites her to renew a plan the shop still
refuses.

A membership "ends" on its next_invoice_date: that is the first day of the
period she has not paid for. A pack ends when its validity runs out or its
credits are used up.
"""
from datetime import timedelta

from odoo import api, models

from odoo.addons.fitness_core.models.studio_time import studio_today

RENEWAL_WINDOW_PARAM = 'fitness.renewal_window_days'
RENEWAL_WINDOW_DEFAULT = 3


class SaleOrderRenewal(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _fitness_renewal_window_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(RENEWAL_WINDOW_PARAM)
        try:
            days = int(raw) if raw not in (None, False, '') else RENEWAL_WINDOW_DEFAULT
        except (TypeError, ValueError):
            days = RENEWAL_WINDOW_DEFAULT
        return max(0, days)

    def _fitness_renewal_opens_on(self):
        """The first day a running membership may be renewed, or None."""
        self.ensure_one()
        if not self.next_invoice_date:
            return None
        return self.next_invoice_date - timedelta(days=self._fitness_renewal_window_days())

    def _fitness_renewable_now(self, today=None):
        """Running: inside the window. Ended (closed): always."""
        self.ensure_one()
        today = today or studio_today()
        if self.end_date and self.next_invoice_date and self.end_date < self.next_invoice_date:
            return False   # ends before its next bill: replaced by its renewal
        if self.subscription_state in ('3_progress', '4_paused'):
            opens = self._fitness_renewal_opens_on()
            return bool(opens) and today >= opens
        return self.subscription_state in ('6_churn',)


    def action_confirm(self):
        """A renewal continues from the old plan's end, and the old plan stops there.

        Card, cash approval and desk sale all confirm through here, so they
        share it. When she renews a membership still running inside the
        window, the new one starts on the old one's end (next_invoice_date)
        so she loses no days - Odoo would otherwise start it today - and the
        old one is given that day as its end: Odoo's billing job closes it
        there instead of invoicing it again or, with no card on file,
        closing it as unpaid. A renewal of an ended plan starts today.
        """
        successions = []
        # Odoo's own renewal and upsell quotations (subscription_id set) carry
        # their parent themselves; they are left to Odoo.
        for order in self.filtered(lambda o: o.state in ('draft', 'sent')
                                   and not o.subscription_id):
            tmpls = order.order_line.product_id.product_tmpl_id.filtered(
                'fitness_is_subscription_plan')
            if len(tmpls) != 1 or not order.plan_id:
                continue
            renewal = order.partner_id._fitness_renewal_state(tmpls)
            previous = renewal['order']
            if (renewal['state'] != 'renewable' or not previous
                    or previous.subscription_state not in ('3_progress', '4_paused')
                    or previous.end_date):
                continue
            start = renewal['continue_from']
            if start and (not order.start_date or order.start_date < start):
                order.start_date = start
            successions.append((order, previous))
        res = super().action_confirm()
        for order, previous in successions:
            if order.state != 'sale' or previous.end_date:
                continue
            # Her last paid day: the day before the first unpaid one. On the
            # end day itself, overdue, or through a cash request approved
            # after the end, that is today or earlier - and still the end, so
            # nothing bills the days she renewed instead of paying for.
            paid_to = (previous.next_invoice_date or order.start_date) - timedelta(days=1)
            previous.sudo().end_date = min(paid_to, order.start_date - timedelta(days=1))
        return res


class ResPartnerRenewal(models.Model):
    _inherit = 'res.partner'

    def _fitness_renewal_state(self, product_tmpl, today=None):
        """What the shop and the desk may do with a product she held before.

        Returns a dict:
          state          'none'      - never held: an ordinary purchase
                         'active'    - held and running outside the window
                         'renewable' - inside the window, or ended
          opens_on       first day it becomes renewable (running plans)
          continue_from  the day a renewal starts so she loses no days: the
                         old plan's end, when that is still ahead of today
          order          the membership concerned, if any
        """
        self.ensure_one()
        today = today or studio_today()
        out = {'state': 'none', 'opens_on': None, 'continue_from': None,
               'order': self.env['sale.order']}
        if product_tmpl.fitness_is_subscription_plan:
            SO = self.env['sale.order'].sudo()
            subs = SO.search([
                ('partner_id', '=', self.id),
                ('is_subscription', '=', True),
                ('order_line.product_id.product_tmpl_id', '=', product_tmpl.id),
                ('subscription_state', 'in', ('3_progress', '4_paused', '6_churn')),
            ])
            # Paused is held: it is hers, and buying it again would give her
            # two. A plan given an end date is being replaced by its renewal,
            # so the one carrying on is the one without.
            running = subs.filtered(
                lambda s: s.subscription_state in ('3_progress', '4_paused'))
            current = running.filtered(lambda s: not s.end_date) or running
            if running:
                latest = current.sorted(lambda s: s.next_invoice_date or today)[-1:]
                out['order'] = latest
                out['opens_on'] = latest._fitness_renewal_opens_on()
                # A membership whose first period has not been invoiced yet -
                # a renewal or purchase confirmed and waiting for its payment
                # (transfer, Bizum) - is hers and Active: renewing it again
                # stacked a third membership on the same days.
                if (latest.end_date and latest.end_date < today
                        and not running.filtered(lambda s: not s.end_date)):
                    # Ended - its end date has passed and nothing carries on
                    # after it - but still marked running until Odoo's weekly
                    # expiry job closes it. It is renewable now, as if closed:
                    # for up to a week she could not buy her plan back.
                    out['state'] = 'renewable'
                elif (latest.start_date and latest.next_invoice_date
                        and latest.next_invoice_date <= latest.start_date):
                    out['state'] = 'active'
                elif latest._fitness_renewable_now(today):
                    out['state'] = 'renewable'
                    if latest.next_invoice_date and latest.next_invoice_date > today:
                        out['continue_from'] = latest.next_invoice_date
                else:
                    out['state'] = 'active'
            elif subs:
                out['state'] = 'renewable'
                out['order'] = subs.sorted('id')[-1:]
            return out
        if product_tmpl.fitness_is_package:
            SOL = self.env['sale.order.line'].sudo()
            held = SOL.search([
                ('order_partner_id', '=', self.id),
                ('product_id.product_tmpl_id', '=', product_tmpl.id),
                ('order_id.state', 'in', list(SOL.SPENDABLE_ORDER_STATES)),
            ])
            if not held:
                return out
            window = self.env['sale.order']._fitness_renewal_window_days()
            live = held.filtered(lambda l: l.fitness_remaining_classes > 0 and (
                not l.fitness_validity_end_date
                or l.fitness_validity_end_date >= today + timedelta(days=window)))
            if live:
                out['state'] = 'active'
                ends = [l.fitness_validity_end_date for l in live if l.fitness_validity_end_date]
                out['opens_on'] = (max(ends) - timedelta(days=window)) if len(ends) == len(live) else None
            else:
                out['state'] = 'renewable'
            return out
        return out
