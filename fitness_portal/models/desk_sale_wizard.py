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
        domain=[('fitness_is_package', '=', True)],
        help="The pack or class being sold. Only packs appear here: a "
             "membership renews itself every month, and cash does not.")

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

    @api.depends('product_id')
    def _compute_normal_price(self):
        for wiz in self:
            product = wiz.product_id
            wiz.normal_price = (
                product.fitness_effective_price() if product else 0.0)
            wiz.credits_granted = product.fitness_class_count if product else 0
            wiz.validity_days = product.fitness_validity_days if product else 0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Start from the real price, so the usual case is one click."""
        for wiz in self:
            if wiz.product_id:
                wiz.amount_paid = wiz.product_id.fitness_effective_price()

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
        """A cash sale gets the same invoice an online one gets.

        Every paying order on this system is invoiced - all three of them, by
        Odoo's own hook: a completed payment transaction calls
        _invoice_sale_orders, which creates the invoice, and posting it is
        what mails it to the student, through the action_post override in
        fitness_notifications. Cash has no transaction, so none of that fires,
        and a desk sale would have been the first paying customer to receive
        no invoice - the exact inconsistency this wizard exists to avoid.

        Done unconditionally rather than behind sale.automatic_invoice, which
        gates the online path. That setting exists because a transaction may
        not have completed; cash has, by definition - the money is in the till
        before the order is written.

        Payment is registered only into a cash journal. Posting cash into the
        bank journal would say the money is in the bank when it is in a
        drawer, and a wrong entry is worse than a missing one: the invoice
        stands either way, and an unpaid invoice is a thing the studio can
        settle, where a misfiled one has to be found first.
        """
        invoice = order._create_invoices()
        if not invoice:
            _logger.warning(
                "[DESK SALE] %s produced no invoice - nothing to post", order.name)
            return invoice
        invoice.action_post()
        _logger.info("[DESK SALE] invoice %s posted for order %s (%.2f)",
                     invoice.name, order.name, invoice.amount_total)

        # sudo throughout: a fitness manager is not an accounting user and
        # cannot read a journal, let alone register a payment. Taking cash is
        # something the studio authorises her to do; the entry that follows is
        # a consequence of it, not a second permission she has to hold.
        journal = self.env['account.journal'].sudo().search([
            ('type', '=', 'cash'),
            ('company_id', '=', order.company_id.id),
        ], limit=1)
        if not journal:
            _logger.warning(
                "[DESK SALE] no cash journal on %s, so invoice %s is posted "
                "but unpaid - the money was taken, the entry is not made",
                order.company_id.name, invoice.name)
            return invoice
        try:
            self.env['account.payment.register'].sudo().with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({'journal_id': journal.id}).action_create_payments()
            _logger.info("[DESK SALE] invoice %s paid from %s",
                         invoice.name, journal.name)
        except Exception:
            # The sale and its invoice are real whatever happens here; losing
            # them to a payment-registration problem would be the worse trade.
            _logger.exception(
                "[DESK SALE] could not register the cash payment for %s",
                invoice.name)
        return invoice

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
        lines = product.fitness_sale_line_vals(self._price_to_charge())
        if not lines:
            raise UserError(_(
                "%(pack)s has no sellable variant, so it cannot be sold.",
                pack=product.display_name))

        order = self.env['sale.order'].sudo().create({
            'partner_id': self.partner_id.id,
            'order_line': [(0, 0, vals) for vals in lines],
        })
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
