# -*- coding: utf-8 -*-
"""Renewals: one row per membership, for the studio, and two alerts.

WHAT A ROW IS. A confirmed membership (a subscription order carrying a
fitness plan product) that has not been carried on by a later membership
of hers, whatever the plan - once she renews or moves to another plan, the
new membership is the row. Paid by card, cash, Bizum or transfer, or given
free. Status, days left and the fee-free date are read from her last paid
day over all her memberships (member_paid_up_to), the fee rule's value.

THE DATES come from fitness_subscriptions/models/membership_dates.py, the
one definition the registration-fee rule reads as well:
  paid_up_to         this membership's last paid day
  member_paid_up_to  her last paid day over all her memberships
  days_left          member_paid_up_to - today + 1: on the last paid day, 1
  fee_free_until  the last day she can renew without the registration fee
"Today" is the studio's day (Europe/Madrid), as everywhere else.

STATUS, first that applies:
  ended      the last paid day has passed, within the fee-free window
  dropped    the last paid day has passed, and the window has too
  due_soon   5 days left or fewer
  free       a membership given for nothing (0.00, or paid "free")
  running    everything else, including a purchase still waiting for its
             first payment (no paid day yet)

WHY A DATABASE VIEW. The list must group and filter by status, which Odoo
can only do on a column, and a fitness manager cannot read sale.order: a
view has its own access row, so managers get this list and nothing more
(the same reasoning as fitness.free.credit.report).

THE ALERTS go to every Fitness Studio Manager's Odoo inbox, whatever her
email preference - the pattern of the class-cancellation notice
(fitness_notifications, _maybe_notify_studio_of_cancel): a logged note on
the membership's order, posted by the system, which notifies nobody by
itself, then delivered to each manager's inbox. The studio works in the
back office; an alert left to the preference went by e-mail to anyone set
to "Handle by Emails". Internal: the member, who follows her own order,
does not see it, and an instructor cannot read the order at all. Each alert has its own
message subtype, and the job looks for that subtype on the order before
sending - so each fires once per membership, whatever the number of runs.
"""
import logging

from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

from odoo.addons.fitness_core.models.studio_lang import studio_date, studio_lang
from odoo.addons.fitness_core.models.studio_time import STUDIO_TZ, studio_today
from odoo.addons.fitness_subscriptions.models.membership_dates import FEE_WINDOW_DAYS

_logger = logging.getLogger(__name__)

# Developer default: "5 days or less" counts the last paid day as 1 day left,
# so the notice goes out on the 5th day before the renewal date.
DUE_SOON_DAYS = 5


class FitnessRenewalReport(models.Model):
    _name = 'fitness.renewal.report'
    _description = 'Renewals'
    _auto = False
    _log_access = False
    _order = 'status_order, paid_up_to, id'

    member_id = fields.Many2one('res.partner', 'Member', readonly=True)
    product_id = fields.Many2one('product.template', 'Membership', readonly=True)
    billing_plan_ref = fields.Integer(readonly=True, aggregator=None)
    billing_plan = fields.Char('Plan', compute='_compute_billing_plan')
    payment_method = fields.Selection([
        ('stripe', 'Card'),
        ('bizum', 'Bizum'),
        ('transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('free', 'Free'),
    ], string='Paid by', readonly=True)
    is_free = fields.Boolean('Free', readonly=True)
    order_ref = fields.Char('Order', readonly=True)
    start_date = fields.Date('Started', readonly=True)
    paid_up_to = fields.Date('Paid up to', readonly=True)
    # The member's last paid day over all her memberships - the value the
    # registration-fee rule reads. Status, days left and the fee-free date
    # come from this, so the list and the fee rule cannot disagree. It equals
    # paid_up_to except while an earlier membership of hers outlasts this one.
    member_paid_up_to = fields.Date('Member paid up to', readonly=True)
    # Never summed: a total of days left across members means nothing.
    days_left = fields.Integer('Days left', readonly=True, aggregator=None)
    fee_free_until = fields.Date(
        'Renew without fee until', readonly=True,
        help="The last day she can renew without paying the registration "
             "fee again.")
    status = fields.Selection([
        ('due_soon', 'Due soon'),
        ('ended', 'Ended - can renew without fee'),
        ('dropped', 'Dropped'),
        ('free', 'Free'),
        ('running', 'Running'),
    ], string='Status', readonly=True)
    status_order = fields.Integer(readonly=True, aggregator=None)

    def _compute_billing_plan(self):
        # sudo: sale.subscription.plan is a Sales model and a fitness manager
        # is not a Sales user. Only the plan's name is shown.
        Plan = self.env['sale.subscription.plan'].sudo()
        for row in self:
            row.billing_plan = (Plan.browse(row.billing_plan_ref).exists().name
                                if row.billing_plan_ref else False)

    @api.model
    def _view_sql(self):
        SO = self.env['sale.order']
        paid = SO._fitness_paid_up_to_sql('so', 'ssp')
        renewed = SO._fitness_renewed_by_sql('so')
        member = SO._fitness_member_last_paid_sql('so')
        return """
            WITH m AS (
                SELECT so.id, so.partner_id, so.name, so.start_date,
                       pp.product_tmpl_id, so.plan_id, so.fitness_payment_method,
                       (so.fitness_payment_method = 'free'
                        OR ROUND(so.amount_total, 2) = 0) AS is_free,
                       {paid} AS paid_up_to,
                       {member} AS last_paid,
                       (now() AT TIME ZONE '{tz}')::date AS today
                  FROM sale_order so
                  JOIN product_product pp ON pp.id = so.fitness_subscription_product_id
             LEFT JOIN sale_subscription_plan ssp ON ssp.id = so.plan_id
                 WHERE so.state = 'sale' AND so.is_subscription
                   AND so.subscription_state IN ('3_progress', '4_paused', '6_churn')
                   AND NOT {renewed}
            ), s AS (
                SELECT m.*,
                       CASE
                         WHEN last_paid IS NOT NULL AND last_paid < today
                              AND today - last_paid <= {window} THEN 'ended'
                         WHEN last_paid IS NOT NULL AND last_paid < today THEN 'dropped'
                         WHEN last_paid IS NOT NULL AND last_paid - today + 1 <= {due} THEN 'due_soon'
                         WHEN is_free THEN 'free'
                         ELSE 'running'
                       END AS status
                  FROM m
            )
            SELECT id, partner_id AS member_id, product_tmpl_id AS product_id,
                   plan_id AS billing_plan_ref, fitness_payment_method AS payment_method,
                   is_free, name AS order_ref, start_date, paid_up_to,
                   last_paid AS member_paid_up_to,
                   CASE WHEN last_paid IS NULL THEN NULL
                        ELSE last_paid - today + 1 END AS days_left,
                   last_paid + {window} AS fee_free_until,
                   status,
                   CASE status WHEN 'due_soon' THEN 1 WHEN 'ended' THEN 2
                        WHEN 'dropped' THEN 3 WHEN 'free' THEN 4 ELSE 5 END AS status_order
              FROM s
        """.format(paid=paid, renewed=renewed, member=member, tz=STUDIO_TZ,
                   window=int(FEE_WINDOW_DAYS), due=int(DUE_SOON_DAYS))

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute('CREATE OR REPLACE VIEW %s AS (%s)' % (self._table, self._view_sql()))

    @api.model_create_multi
    def create(self, vals_list):
        raise UserError(_("Renewals is read from the memberships themselves. "
                          "Sell or renew a membership and it appears here."))

    def write(self, vals):
        raise UserError(_("Renewals is read from the memberships themselves. "
                          "Change the membership, not this list."))

    def unlink(self):
        raise UserError(_("Renewals is read from the memberships themselves. "
                          "Nothing here can be deleted."))

    # ── alerts ──────────────────────────────────────────────────────
    @api.model
    def _fitness_alert_recipients(self):
        group = self.env.ref('fitness_core.group_fitness_manager')
        return self.env['res.users'].sudo().search([
            ('group_ids', 'in', group.id), ('share', '=', False)])

    def _fitness_alert_body(self, event, lang):
        self.ensure_one()
        env = self.with_context(lang=lang).env
        plan = self.product_id.with_context(lang=lang).name or self.order_ref
        if self.is_free:
            plan = env._('%(plan)s (free)', plan=plan)
        paid = studio_date(self.env, self.member_paid_up_to or self.paid_up_to, 'd MMM y', lang)
        if event == 'due':
            return env._(
                'Renewal due soon: %(member)s, %(plan)s, paid up to %(date)s '
                '(%(days)s day(s) left). Order %(order)s.',
                member=self.member_id.name, plan=plan, date=paid,
                days=self.days_left, order=self.order_ref)
        return env._(
            'Membership ended without renewal: %(member)s, %(plan)s, last paid '
            'day %(date)s. Renewing is free of the registration fee until '
            '%(until)s. Order %(order)s.',
            member=self.member_id.name, plan=plan, date=paid,
            until=studio_date(self.env, self.fee_free_until, 'd MMM y', lang),
            order=self.order_ref)

    @api.model
    def _cron_fitness_renewal_alerts(self):
        """Tell the managers, once each: due soon, and ended without renewal."""
        subtypes = {
            'due': self.env.ref('fitness_portal.mt_fitness_renewal_due'),
            'ended': self.env.ref('fitness_portal.mt_fitness_membership_ended'),
        }
        recipients = self._fitness_alert_recipients()
        lang = studio_lang(self.env)
        Message = self.env['mail.message'].sudo()
        sent = {'due': 0, 'ended': 0}
        # The view reads sale_order directly: what is still only in the ORM's
        # cache would be invisible to it.
        self.env.flush_all()
        rows = self.sudo().search([('status', 'in', ('due_soon', 'ended'))])
        for row in rows:
            event = 'due' if row.status == 'due_soon' else 'ended'
            if Message.search_count([
                    ('model', '=', 'sale.order'), ('res_id', '=', row.id),
                    ('subtype_id', '=', subtypes[event].id)], limit=1):
                continue
            order = self.env['sale.order'].sudo().browse(row.id)
            # Logged, not posted: a logged note notifies nobody, so no
            # follower and no preference turns it into an e-mail. Posted by
            # the system, carrying the alert's own subtype so the next run
            # finds it.
            note = order._message_log(
                body=Markup('<p>%s</p>') % row._fitness_alert_body(event, lang),
                author_id=self.env.ref('base.partner_root').id)
            note.sudo().write({'subtype_id': subtypes[event].id})
            inbox = [{'id': u.partner_id.id, 'uid': u.id, 'notif': 'inbox'} for u in recipients]
            if inbox:
                order._notify_thread_by_inbox(note, inbox)
            sent[event] += 1
        _logger.info("[RENEWALS] alerts sent: %d due soon, %d ended (%d manager(s))",
                     sent['due'], sent['ended'], len(recipients))
        return sent
