# -*- coding: utf-8 -*-
"""Selling a pack at the desk, for cash or for nothing.

Two things the studio could not do without a developer: take cash for a pack
and have the credits appear, and hand somebody credits as a goodwill gesture.
Both are the same act - a student ends up entitled to classes - so they are
one wizard with one difference, whether any money changed hands.

Every grant writes a real, confirmed sale order at the product's own price.
That is the whole design, not an implementation detail: credits in this system
are sale order lines. The expiry date, the Saldo ledger, the payment-source
picker and the cancellation refund all read the order, so a credit with no
order behind it would be a credit that expires wrong, shows up nowhere and
cannot be given back. Every records-disagree bug found in this codebase has
had that shape, and there is deliberately no path here that produces one.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'


class FitnessDeskSaleWizard(models.TransientModel):
    _name = 'fitness.desk.sale.wizard'
    _description = 'Sell a pack at the desk (cash or goodwill)'

    partner_id = fields.Many2one(
        'res.partner', string='Student', required=True,
        help="Who the credits are for.")
    product_id = fields.Many2one(
        'product.template', string='Pack', required=True,
        # Courtesy excluded explicitly, not left to sale_ok. 3deca50 kept
        # these two out of all three shop tabs for the same reason and in the
        # same words - "these domains never asked about sale_ok, which is how
        # two products sat in the shop unbuyable until somebody tried to buy
        # one" - and this picker was the screen that fix did not reach. They
        # are the studio's gift products at 0.00; a cash sale must not be able
        # to pick one, and a gift is given from the Roster, not sold here.
        domain=['|', ('fitness_is_package', '=', True),
                     ('fitness_is_subscription_plan', '=', True),
                ('fitness_is_courtesy', '=', False)],
        help="The pack, class or membership being sold.")

    # Memberships only. A pack has no billing period - it is credits with an
    # expiry - so this stays empty for one and decides the commitment for the
    # other. Quarterly is three months charged at once, and it is also what
    # waives the registration fee, so picking it here is not a formality.
    is_membership = fields.Boolean(compute='_compute_normal_price')
    plan_id = fields.Many2one(
        'sale.subscription.plan', string='Billing period',
        help="How long the membership is committed for. Mensual bills every "
             "month; Trimestral is three months, charged at once.")

    normal_price = fields.Monetary(
        string='Normal price', compute='_compute_normal_price',
        currency_field='currency_id',
        help="What this pack costs today, promotions included.")
    # Two genuinely different acts, so the form asks which one outright
    # rather than leaving it to be inferred from whether an amount happens to
    # be filled in. A cash sale that silently records nothing, or a gift that
    # silently records revenue, are both wrong in ways nobody would notice
    # until the books were read.
    payment_method = fields.Selection(
        [('cash', 'Cash payment - the student paid'),
         ('free', 'Free credit - no money changed hands')],
        default='cash', required=True, string='This is a')
    amount_paid = fields.Monetary(
        string='Cash taken', currency_field='currency_id',
        help="What was actually put in the till. Defaults to the normal "
             "price; lower it for a discount.")
    reason = fields.Text(
        string='Reason',
        help="Why this was given. Recorded on the order, and the only record "
             "anyone will have later.")
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    credits_granted = fields.Integer(
        string='Classes granted', compute='_compute_normal_price')
    validity_days = fields.Integer(
        string='Valid for (days)', compute='_compute_normal_price')

    @api.depends('product_id', 'plan_id')
    def _compute_normal_price(self):
        for wiz in self:
            product = wiz.product_id
            wiz.is_membership = bool(
                product and product.fitness_is_subscription_plan)
            # Times the months the period covers, or a Trimestral shows one
            # month's price and the manager takes one month's money for a
            # three-month commitment.
            wiz.normal_price = (
                product.fitness_effective_price() * wiz._months()
                if product else 0.0)
            wiz.credits_granted = product.fitness_class_count if product else 0
            wiz.validity_days = product.fitness_validity_days if product else 0

    def _months(self):
        """How many months this sale covers. One for anything without a plan."""
        self.ensure_one()
        if not (self.product_id and self.product_id.fitness_is_subscription_plan):
            return 1
        return self.env['product.template'].fitness_plan_months(
            self._effective_plan())

    def _effective_plan(self):
        """The plan this sale is on: the one chosen, else the product's own.

        Never left to whatever sale.subscription.plan happens to be first in
        the table - checkout learned that the hard way, where search([],
        limit=1) always returned Monthly and Yearly could not be bought at all.
        """
        self.ensure_one()
        Plan = self.env['sale.subscription.plan'].sudo()
        product = self.product_id
        if not (product and product.fitness_is_subscription_plan):
            return Plan.browse()
        # sudo throughout: a fitness manager is not a Sales user and cannot
        # read sale.subscription.plan. Selling what the studio authorises her
        # to sell should not require Sales rights, and without this every
        # membership sale raised AccessError on the plan's own fields.
        if self.plan_id:
            return self.plan_id.sudo()
        own = product.sudo().fitness_subscription_plan_id
        if own and own.sudo().active:
            return own.sudo()
        fallback = self.env.ref('sale_subscription.subscription_plan_month',
                                raise_if_not_found=False)
        return fallback.sudo() if fallback else Plan.browse()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Start from the real price, so the usual case is one click."""
        for wiz in self:
            if wiz.product_id:
                if (wiz.product_id.fitness_is_subscription_plan
                        and not wiz.plan_id):
                    wiz.plan_id = wiz._effective_plan()
                if not wiz.product_id.fitness_is_subscription_plan:
                    wiz.plan_id = False
                wiz.amount_paid = (
                    wiz.product_id.fitness_effective_price() * wiz._months())

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        """A longer commitment is a different price, and may drop the fee."""
        for wiz in self:
            if wiz.product_id and wiz.product_id.fitness_is_subscription_plan:
                wiz.amount_paid = (
                    wiz.product_id.fitness_effective_price() * wiz._months())

    @api.onchange('payment_method')
    def _onchange_payment_method(self):
        for wiz in self:
            if wiz.payment_method == 'free':
                wiz.amount_paid = 0.0
            elif wiz.product_id and not wiz.amount_paid:
                wiz.amount_paid = wiz.product_id.fitness_effective_price()

    def _price_to_charge(self):
        """The line's price_unit, so the order totals what was taken.

        The order records what actually happened, so a discounted sale is
        written at the discounted price rather than at the list price with the
        difference invisible. A goodwill grant is written at zero, which is
        what it was.

        The figure typed in is the money in the till, tax included. Turning
        that into a price_unit depends on how the product's tax is configured
        and this database has both kinds, so the product is asked rather than
        assumed - see fitness_price_unit_for_gross. Getting it wrong is
        silent: writing the gross under a tax-exclusive product made 75.00
        taken into an 86.25 order, and reversing the tax under a
        price-included one made 95.00 taken into a 78.51 order. Both were
        found by testing against real data rather than by reading the code.
        """
        self.ensure_one()
        if self.payment_method == 'free':
            return 0.0
        return self.product_id.fitness_price_unit_for_gross(
            self.amount_paid or 0.0, self.partner_id)

    def _invoice_cash_sale(self, order):
        """Delegates. The renewal path needs the same steps, and a second copy
        of "post it, take the cash, mail it" is how two ways of taking money
        come to disagree about what the student receives."""
        return order.fitness_invoice_cash_sale()

    def action_create_sale(self):
        self.ensure_one()
        if not (self.env.user.has_group(MANAGER_GROUP)
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only a studio manager can sell from the desk."))
        if self.payment_method == 'free' and not (self.reason or '').strip():
            raise UserError(_(
                "Say why this is being given for free. It is the only record "
                "anyone will have of it later."))
        if self.payment_method == 'cash' and (self.amount_paid or 0.0) <= 0.0:
            raise UserError(_(
                "Enter the cash taken, or switch to No charge (goodwill)."))

        product = self.product_id
        plan = self._effective_plan()
        # The same builder checkout uses, so the desk sells what the shop
        # sells: the matricula when the studio's two conditions are met, and
        # no months multiplier here because the figure below is the cash taken
        # for the whole sale, not a price per month.
        lines = product.fitness_order_line_vals(
            self.partner_id, plan=plan, total_price=self._price_to_charge())
        if not lines:
            raise UserError(_(
                "%(pack)s has no sellable variant, so it cannot be sold.",
                pack=product.display_name))

        vals = {
            'partner_id': self.partner_id.id,
            'order_line': [(0, 0, line) for line in lines],
        }
        # Set at create, never written afterwards alongside the lines. Writing
        # plan_id and order_line together discards an explicit price_unit -
        # that is how a quarterly membership at 585.00 came to bill 195.00
        # every three months on production. See the double-submit test in
        # tests/test_subscription_payment.py.
        if plan and 'plan_id' in self.env['sale.order']._fields:
            vals['plan_id'] = plan.id
        order = self.env['sale.order'].sudo().create(vals)
        order.write({'fitness_payment_method': self.payment_method})
        order.action_confirm()

        note = _(
            "Sold at the desk by %(who)s. Payment: %(method)s. "
            "Amount: %(amount)s.",
            who=self.env.user.name,
            method=dict(self._fields['payment_method'].selection).get(
                self.payment_method, self.payment_method),
            # What was put in the till, not the taxable base the line carries.
            amount="%.2f %s" % (
                0.0 if self.payment_method == 'free' else (self.amount_paid or 0.0),
                self.currency_id.name or ''),
        )
        if (self.reason or '').strip():
            note += "<br/>" + _("Reason: %(why)s", why=self.reason.strip())
        order.message_post(body=note)

        _logger.info(
            "[DESK SALE] %s sold %s to partner %s for %.2f taken (%s), "
            "order %s totalling %.2f",
            self.env.user.login, product.display_name, self.partner_id.id,
            0.0 if self.payment_method == 'free' else (self.amount_paid or 0.0),
            self.payment_method, order.name, order.amount_total)

        if self.payment_method == 'cash':
            self._invoice_cash_sale(order)

        # Opening the order is the nicer ending, but a fitness manager is not
        # necessarily a Sales user - on this database only the owner is - and
        # sending anybody else to a Sales Order form ends the sale on an
        # access error, with the sale itself having gone through perfectly.
        # So the redirect is offered only to someone who can actually read it.
        try:
            order.with_user(self.env.user).check_access('read')
        except AccessError:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'sticky': False,
                    'message': _(
                        "%(order)s created for %(who)s.",
                        order=order.name, who=self.partner_id.name),
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _("Desk sale: %(name)s", name=order.name),
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
        }
