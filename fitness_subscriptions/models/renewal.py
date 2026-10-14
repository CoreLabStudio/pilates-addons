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
        if self.subscription_state == '3_progress':
            opens = self._fitness_renewal_opens_on()
            return bool(opens) and today >= opens
        return self.subscription_state in ('6_churn',)


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
                ('subscription_state', 'in', ('3_progress', '6_churn')),
            ])
            running = subs.filtered(lambda s: s.subscription_state == '3_progress')
            if running:
                latest = running.sorted(lambda s: s.next_invoice_date or today)[-1:]
                out['order'] = latest
                out['opens_on'] = latest._fitness_renewal_opens_on()
                if latest._fitness_renewable_now(today):
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
