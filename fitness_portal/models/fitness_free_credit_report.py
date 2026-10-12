# -*- coding: utf-8 -*-
"""Everything the studio has given away for nothing, in one place.

WHY THIS IS A DATABASE VIEW AND NOT A TABLE.

Credits in this system ARE sale order lines. The expiry, the Saldo
ledger, the payment-source picker and the cancellation refund all read
the line, so a second copy of "what was given" would be a second opinion,
and every records-disagree fault found in this codebase has had that
shape. There is already a table of exactly that kind - fitness.gift.log -
and it holds nothing: the only thing that ever wrote to it is the gift
wizard, whose view file was never added to the manifest's data list, so
nothing has ever been recorded there and nothing will be until that
screen exists. Reading it would have handed the owner an empty list and
called it history.

So this reads the orders. Nothing is copied and nothing is backfilled:
the free packs and memberships the studio gave before this change are in
here because they always were - confirmed orders whose
fitness_payment_method is 'free'. The history exists from day one because
it is not a new record of anything. It is a different way of looking at
records that were already being written.

WHY A POSTGRES VIEW RATHER THAN A MODEL OVER sale.order.line. A fitness
manager cannot read sale.order.line: she is not a Sales user, and on this
database only the owner is. The audit measured that. A model whose rows
come from a Postgres view has its OWN access rules, and Postgres does not
consult Odoo's - so a single access row grants managers this list and
nothing else, and no read access to sale.order.line is added to anybody.
A student or an instructor has no row at all, which is a refusal over
RPC and not merely a menu they cannot see.

WHAT A ROW IS. One confirmed, free order line that granted something: a
free single class, a free pack, or a free membership. A combined pack is
two lines - one credit pool per discipline - and shows as two rows, which
is what the student actually holds.

WHAT IS DELIBERATELY NOT A ROW. A student claiming something that costs
her nothing is not the studio giving her anything. /my/packages has a
self-service path that writes fitness_payment_method = 'free' for a
product whose price for her is zero, and those orders she created
herself. Listing them would show the owner gifts she never gave, with the
student's own name in "Given by". So a row needs somebody other than the
student behind it, or the desk's own reason on it.
"""
import logging

from odoo import models, fields, api, tools, _
from odoo.addons.fitness_subscriptions.models.sale_order import (
    ACTIVE_SUBSCRIPTION_STATE,
)
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# id IS the order line's id. Deliberately: it makes a row and the credit
# behind it the same thing, so order_line_id can never be out of step
# with the row it sits on and there is nothing to keep in sync.
#
# The WHERE clause is the whole definition of "given":
#
#   fitness_payment_method = 'free'
#       The desk's Free credit, and the only marker a free grant has ever
#       carried. Written by the desk wizard since it was first built,
#       which is why packs and memberships given before this change are
#       already in the list.
#   state IN ('sale', 'done')
#       Confirmed. A draft quotation granted nothing - the credits are
#       written by action_confirm - so listing one would claim the studio
#       gave away something it did not.
#   a package or a membership plan
#       The thing that grants. It also drops the registration-fee line,
#       which is not a gift and is never on a free order anyway.
#   somebody other than the student, or a reason from the desk
#       See the module docstring. %s is ACTIVE_SUBSCRIPTION_STATE.
FREE_CREDIT_SQL = """
    SELECT
        sol.id                                      AS id,
        sol.id                                      AS order_line_id,
        so.id                                       AS order_id,
        so.partner_id                               AS student_id,
        so.date_order                               AS given_on,
        -- The month in MADRID. date_order is stored as naive UTC, so a
        -- gift given just after midnight on the 1st in Madrid is still
        -- the previous day in UTC and used to be filed under the wrong
        -- month.
        to_char((so.date_order AT TIME ZONE 'UTC')
                AT TIME ZONE 'Europe/Madrid', 'YYYY-MM')
                                                    AS given_month,
        -- "This month" and "Last month" decided here, on Madrid's
        -- calendar, rather than in the search view from the browser's.
        to_char((so.date_order AT TIME ZONE 'UTC')
                AT TIME ZONE 'Europe/Madrid', 'YYYY-MM')
            = to_char(now() AT TIME ZONE 'Europe/Madrid', 'YYYY-MM')
                                                    AS is_this_month,
        to_char((so.date_order AT TIME ZONE 'UTC')
                AT TIME ZONE 'Europe/Madrid', 'YYYY-MM')
            = to_char((now() AT TIME ZONE 'Europe/Madrid')
                      - interval '1 month', 'YYYY-MM')
                                                    AS is_last_month,
        so.create_uid                               AS given_by,
        pt.id                                       AS product_id,
        so.currency_id                              AS currency_id,
        so.fitness_free_reason                      AS reason,
        CASE
            WHEN COALESCE(pt.fitness_is_subscription_plan, false)
                THEN 'membership'
            WHEN COALESCE(pt.fitness_is_courtesy, false)
                THEN 'class'
            ELSE 'package'
        END                                         AS given_type,
        COALESCE(sol.fitness_class_type, pt.fitness_class_type)
                                                    AS discipline,
        pt.fitness_session_type                     AS session_type,
        sol.fitness_validity_end_date               AS expires_on,
        COALESCE(sol.fitness_original_class_count, 0)
                                                    AS credits_given,
        COALESCE(sol.fitness_remaining_classes, 0)  AS credits_left,
        -- The product's list price, not the line's. The line is 0.00
        -- because that is the whole point; what the owner wants to see
        -- is what she chose not to charge.
        COALESCE(pt.list_price, 0.0) * COALESCE(sol.product_uom_qty, 1)
                                                    AS value_given,
        CASE
            -- Spent comes first. A credit that was used and whose date
            -- has since passed was still used, and reading "expired"
            -- would say the studio gave her nothing.
            WHEN COALESCE(sol.fitness_original_class_count, 0) > 0
                 AND COALESCE(sol.fitness_remaining_classes, 0) <= 0
                THEN 'used'
            WHEN sol.fitness_validity_end_date IS NOT NULL
                 AND sol.fitness_validity_end_date
                     < (now() AT TIME ZONE 'Europe/Madrid')::date
                THEN 'expired'
            -- A membership has no credit counter - the allowance is
            -- weekly and lives on the subscription - so whether it is
            -- still something she has is the subscription's own state,
            -- and nothing else here can answer it.
            WHEN COALESCE(pt.fitness_is_subscription_plan, false)
                 AND COALESCE(so.subscription_state, '') <> %s
                THEN 'expired'
            ELSE 'available'
        END                                         AS status
    FROM sale_order_line sol
    JOIN sale_order so ON so.id = sol.order_id
    JOIN product_product pp ON pp.id = sol.product_id
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE so.fitness_payment_method = 'free'
      AND so.state IN ('sale', 'done')
      AND (COALESCE(pt.fitness_is_package, false)
           OR COALESCE(pt.fitness_is_subscription_plan, false))
      AND (so.fitness_free_reason IS NOT NULL
           OR NOT EXISTS (SELECT 1 FROM res_users u
                           WHERE u.id = so.create_uid
                             AND u.partner_id = so.partner_id))
"""


class FitnessFreeCreditReport(models.Model):
    _name = 'fitness.free.credit.report'
    _description = 'Free classes given'
    _auto = False
    _order = 'given_on desc, id desc'
    # With _auto = False this is already the default; said out loud so
    # nobody adds create_date columns to the SELECT looking for it.
    _log_access = False

    # ── who got what, and when ──────────────────────────────────────
    given_on = fields.Datetime('Given', readonly=True)
    # Grouped on by the pivot and by "Group by > Month". A Char from
    # to_char rather than a date_trunc, because Odoo's own month grouping
    # on a Datetime groups by the SERVER's month and the studio reads
    # these in Europe/Madrid; this way the column and the group agree.
    given_month = fields.Char('Month', readonly=True)
    is_this_month = fields.Boolean('Given this month', readonly=True)
    is_last_month = fields.Boolean('Given last month', readonly=True)
    student_id = fields.Many2one('res.partner', 'Student', readonly=True)
    product_id = fields.Many2one('product.template', 'Product',
                                 readonly=True)
    given_type = fields.Selection([
        ('class', 'Free class'),
        ('package', 'Free pack'),
        ('membership', 'Free membership'),
    ], string='What', readonly=True)
    discipline = fields.Selection([
        ('barre', 'Barre'),
        ('reformer', 'Reformer Pilates'),
        ('any', 'Any'),
    ], string='Discipline', readonly=True)
    session_type = fields.Selection([
        ('group', 'Group'),
        ('private', 'Private (1-on-1)'),
        ('duo', 'Duo (2 people)'),
    ], string='Session', readonly=True)
    given_by = fields.Many2one('res.users', 'Given by', readonly=True)
    # Written by the desk from this version on. A gift given BEFORE this
    # change has its reason in the order's chatter and nowhere else, so
    # this reads empty for one and the row opens the order, which is
    # where it is. Parsing it back out of a chatter body would mean
    # matching a prefix that was translated into whatever language the
    # manager had at the time, and history that is quietly wrong is worse
    # than history that is visibly absent.
    reason = fields.Text('Reason', readonly=True)

    # ── what became of it ───────────────────────────────────────────
    status = fields.Selection([
        ('available', 'Available'),
        ('used', 'Used'),
        ('expired', 'Expired'),
    ], string='Status', readonly=True)
    expires_on = fields.Date('Expires on', readonly=True)
    credits_given = fields.Integer('Classes given', readonly=True)
    credits_left = fields.Integer('Classes left', readonly=True)
    # Summed, so a row is worth something on a pivot: "what did we give
    # away in March" is a total, not a row count, once a free 5-pack sits
    # in the list beside a free single class.
    value_given = fields.Monetary(
        'Value', readonly=True, currency_field='currency_id',
        help="What the product normally costs - what the studio chose "
             "not to charge.")
    currency_id = fields.Many2one('res.currency', readonly=True)

    # ── the way back out ────────────────────────────────────────────
    order_id = fields.Many2one('sale.order', 'Order', readonly=True)
    order_line_id = fields.Many2one('sale.order.line', 'Credit line',
                                    readonly=True)

    # Not in the SQL. A booking points at the line, so joining it would
    # multiply the rows: a free 10-pack with four classes booked would
    # appear four times and the pivot would count forty classes given.
    # One query for the whole list instead, and a count beside the class.
    used_event_id = fields.Many2one(
        'calendar.event', 'Class it paid for', compute='_compute_used',
        help="The class this credit was spent on - the most recent one, "
             "when a pack paid for several.")
    used_event_count = fields.Integer('Classes booked',
                                      compute='_compute_used')

    @api.depends('order_line_id')
    def _compute_used(self):
        # sudo on fitness.booking only to search by a line id the manager
        # has already been granted on this row. It reads no field of
        # sale.order.line and widens nothing.
        Booking = self.env['fitness.booking'].sudo()
        line_ids = [lid for lid in self.mapped('order_line_id').ids if lid]
        by_line = {}
        if line_ids:
            for booking in Booking.search(
                    [('package_order_line_id', 'in', line_ids),
                     ('state', '!=', 'cancelled')], order='id desc'):
                by_line.setdefault(
                    booking.package_order_line_id.id, []).append(booking)
        for row in self:
            bookings = by_line.get(row.order_line_id.id, [])
            row.used_event_count = len(bookings)
            row.used_event_id = (
                bookings[0].calendar_event_id if bookings else False)

    # ── Excel ───────────────────────────────────────────────────────
    #
    # A button rather than Odoo's own Export, and the reason is an access
    # one. Odoo gates Export behind base.group_allow_export, which on this
    # database is implied by group_system alone - so a fitness manager
    # cannot export anything at all. Granting her that group would let her
    # export every model she can read, not this one list, and the brief
    # for this change is explicit that nothing widens beyond managers.
    #
    # So the export is scoped to this report: one route, manager-checked,
    # reading the rows back through the ORM as the person who asked, so
    # the access row above is what decides and the ids in the URL cannot
    # be used to fish anything out.
    def action_export_xlsx(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/fitness/free_credits/export.xlsx?ids=%s'
                   % ','.join(str(i) for i in self.ids),
            'target': 'self',
        }

    # ── the view ────────────────────────────────────────────────────
    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # The table name is this class's own constant; the one value that
        # varies is passed as a parameter rather than %-formatted in.
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW %s AS (%s)'
            % (self._table, FREE_CREDIT_SQL),
            (ACTIVE_SUBSCRIPTION_STATE,))
        _logger.info("[FREE CREDITS] view %s (re)created", self._table)

    # Read-only all the way down. The Postgres view would refuse an
    # INSERT anyway, with a message about a view having no rule - which
    # tells a manager nothing. These say what is true instead.
    @api.model_create_multi
    def create(self, vals_list):
        raise UserError(_(
            "Free classes given is a history of what the studio gave. It "
            "is not something you can add to: give the class at Sell at "
            "desk and it appears here."))

    def write(self, vals):
        raise UserError(_(
            "A gift already given cannot be edited here. Open the order "
            "to see or change what was recorded."))

    def unlink(self):
        raise UserError(_(
            "A gift already given cannot be deleted from the history."))
