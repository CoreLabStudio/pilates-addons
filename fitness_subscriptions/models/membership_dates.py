# -*- coding: utf-8 -*-
"""Her last paid day, and the 30 days after it. One definition.

The studio's rule (owner, Nov 2026): a membership ends on its last paid
day. After it she has FEE_WINDOW_DAYS days to renew without paying the
registration fee again; a renewal starting after that pays it, whoever she
is and whenever she left.

Two readers must never disagree about those dates: the Renewals list
(fitness_portal, a database view, so it can be filtered and grouped by
status) and the registration-fee rule (product_template.py). So both come
from here: the fee rule calls the Python, the list embeds the SQL, and the
two are written side by side and proved equal by test_membership_dates.

"Last paid day":
  * billed at least once (next_invoice_date after start_date): the day
    before next_invoice_date, the first day she has not paid for;
  * never billed and given for nothing (total 0.00): the end of the plan's
    first period - a gift is a normal membership of the plan's length;
  * never billed and not free (a purchase waiting for its transfer): none.
    No day is paid yet, so she has not ended.
  An end date earlier than that (a renewal that replaced it, a close)
  caps it.
"""
from datetime import timedelta

from odoo import api, models

# Developer default for the client's "30 days to renew": renewing on day 30
# after the last paid day is free of the fee, day 31 is not.
FEE_WINDOW_DAYS = 30


def fitness_fee_free_until(last_paid_day):
    """The last start date on which a renewal carries no registration fee."""
    if not last_paid_day:
        return None
    return last_paid_day + timedelta(days=FEE_WINDOW_DAYS)


def fitness_renewal_pays_fee(last_paid_day, new_start):
    """True when a membership starting on new_start comes more than
    FEE_WINDOW_DAYS after last_paid_day."""
    until = fitness_fee_free_until(last_paid_day)
    return bool(until and new_start and new_start > until)


class SaleOrderMembershipDates(models.Model):
    _inherit = 'sale.order'

    def _fitness_paid_up_to(self):
        """This membership's last paid day, or None (see the module doc)."""
        self.ensure_one()
        start, nxt, end = self.start_date, self.next_invoice_date, self.end_date
        if not start:
            return None
        if nxt and nxt > start:
            last = nxt - timedelta(days=1)
        elif self.currency_id.is_zero(self.amount_total) and self.plan_id:
            last = start + self.plan_id.sudo().billing_period - timedelta(days=1)
        else:
            return None
        if end and end < last:
            last = end
        return last

    @api.model
    def _fitness_paid_up_to_sql(self, so='so', plan='ssp'):
        """The same rule as _fitness_paid_up_to, as a SQL date expression
        over sale_order `so` LEFT JOINed to sale_subscription_plan `plan`."""
        period = (
            "CASE {p}.billing_period_unit"
            " WHEN 'year' THEN make_interval(years => {p}.billing_period_value)"
            " WHEN 'month' THEN make_interval(months => {p}.billing_period_value)"
            " WHEN 'week' THEN make_interval(weeks => {p}.billing_period_value)"
            " ELSE make_interval(days => {p}.billing_period_value) END").format(p=plan)
        last = (
            "CASE WHEN {so}.start_date IS NULL THEN NULL"
            " WHEN {so}.next_invoice_date > {so}.start_date THEN {so}.next_invoice_date - 1"
            " WHEN ROUND({so}.amount_total, 2) = 0 AND {p}.id IS NOT NULL"
            " THEN ({so}.start_date + {period})::date - 1"
            " END").format(so=so, p=plan, period=period)
        return ("(CASE WHEN ({last}) IS NULL THEN NULL"
                " WHEN {so}.end_date IS NOT NULL AND {so}.end_date < ({last}) THEN {so}.end_date"
                " ELSE ({last}) END)").format(last=last, so=so)

    def _fitness_renewed_by(self):
        """The confirmed membership that carries this one on, if any: any later
        membership of hers, whatever the plan (owner, 25 Nov 2026) - a member
        who moves to another plan has not dropped. Only the Renewals list,
        its alerts and the member's reminder read this; the shop's Renew
        button keeps its own same-product rule (_fitness_renewal_state).

        A consequence, said out loud: two memberships held side by side (one
        per discipline) look the same as a switch, so the earlier one is
        treated as carried on by the later."""
        self.ensure_one()
        if not self.fitness_subscription_product_id or not self.partner_id:
            return self.browse()
        return self.sudo().search([
            ('partner_id', '=', self.partner_id.id),
            ('id', '>', self.id),
            ('state', '=', 'sale'),
            ('is_subscription', '=', True),
            ('subscription_state', 'in', ('3_progress', '4_paused', '5_renewed', '6_churn')),
            ('fitness_subscription_product_id', '!=', False),
        ], limit=1)

    @api.model
    def _fitness_renewed_by_sql(self, so='so'):
        """The same test as _fitness_renewed_by, as a SQL EXISTS over `so`."""
        return (
            "EXISTS (SELECT 1 FROM sale_order nx"
            " WHERE nx.partner_id = {so}.partner_id AND nx.id > {so}.id AND nx.state = 'sale'"
            " AND nx.is_subscription AND nx.fitness_subscription_product_id IS NOT NULL"
            " AND nx.subscription_state IN ('3_progress', '4_paused', '5_renewed', '6_churn'))"
        ).format(so=so)

    @api.model
    def _fitness_member_last_paid_sql(self, so='so'):
        """_fitness_last_paid_day_of(partner of `so`) as a SQL subquery: the
        member's last paid day over every confirmed membership of hers, NULL
        while one is still waiting for its first payment. The Renewals list
        reads its status from this, so the list and the fee rule agree on
        whether she has dropped."""
        paid = self._fitness_paid_up_to_sql('a', 'ap')
        return (
            "(SELECT CASE WHEN bool_or(a.subscription_state IN ('3_progress', '4_paused')"
            " AND ({paid}) IS NULL) THEN NULL ELSE MAX({paid}) END"
            " FROM sale_order a LEFT JOIN sale_subscription_plan ap ON ap.id = a.plan_id"
            " WHERE a.partner_id = {so}.partner_id AND a.state = 'sale' AND a.is_subscription"
            " AND a.fitness_subscription_product_id IS NOT NULL)").format(paid=paid, so=so)

    @api.model
    def _fitness_last_paid_day_of(self, partner):
        """For the fee rule: the last paid day of her most recent membership,
        or None when she still holds one with no paid day yet (current,
        waiting for its first payment) or none with dates at all.

        Every confirmed membership of this contact counts, of any plan:
        "ended more than 30 days before the new start" is about her being
        away from the studio, not about one product."""
        if not partner:
            return None
        subs = self.sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'sale'),
            ('is_subscription', '=', True),
            ('fitness_subscription_product_id', '!=', False),
        ])
        days = []
        for sub in subs:
            last = sub._fitness_paid_up_to()
            if last is None:
                if sub.subscription_state in ('3_progress', '4_paused'):
                    return None
                continue
            days.append(last)
        return max(days) if days else None
