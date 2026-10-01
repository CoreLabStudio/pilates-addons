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

    # Three figures where there was one. "Cash taken" defaulted to the
    # membership alone, the registration fee was appended to the order
    # afterwards, and neither the form nor the manager ever saw it: Yoleyva
    # collected 145.00 against an order of 177.23 and reported the numbers
    # as being off, which they were - the till, the order and the invoice
    # disagreed by the fee. It is now shown, counted, and part of what she
    # is told to collect.
    membership_price = fields.Monetary(
        string='Package price', compute='_compute_normal_price',
        currency_field='currency_id',
        help="The pack or membership itself, for the period chosen, "
             "before the registration fee.")
    matricula_fee = fields.Monetary(
        string='Registration (one-off)', compute='_compute_normal_price',
        currency_field='currency_id',
        help="Charged on a student's first membership when the commitment "
             "is shorter than three months. Zero when it does not apply, "
             "and the line beneath says why.")
    matricula_note = fields.Char(
        string=' ', compute='_compute_normal_price',
        help="Why the registration line reads what it reads.")
    normal_price = fields.Monetary(
        string='Total to collect', compute='_compute_normal_price',
        currency_field='currency_id',
        help="The membership and the registration fee together - the whole "
             "sale, and what the order will come to.")
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

    # partner_id is in here because the registration fee depends on WHO is
    # buying - it is charged on a first membership and waived on a second -
    # so the total changes when the student does.
    #
    # payment_method is in here because a gift carries no fee at all. Left
    # out, switching Cash to Free kept the cached fee and the form went on
    # showing 39.00 on a giveaway.
    @api.depends('product_id', 'plan_id', 'partner_id', 'payment_method')
    def _compute_normal_price(self):
        for wiz in self:
            product = wiz.product_id
            wiz.is_membership = bool(
                product and product.fitness_is_subscription_plan)
            # Times the months the period covers, or a Trimestral shows one
            # month's price and the manager takes one month's money for a
            # three-month commitment.
            wiz.membership_price = (
                product.fitness_effective_price() * wiz._months()
                if product else 0.0)
            wiz.matricula_fee = wiz._matricula_fee()
            wiz.matricula_note = wiz._matricula_note()
            wiz.normal_price = wiz.membership_price + wiz.matricula_fee
            wiz.credits_granted = product.fitness_class_count if product else 0
            wiz.validity_days = product.fitness_validity_days if product else 0

    def _matricula_note(self):
        """Why the registration line reads what it reads.

        The form used to hide the fee when none was due, on the grounds
        that the total was then the membership and saying it twice was
        noise. That left a single figure with no way to tell whether the
        fee had been considered and waived or silently missed - which,
        after an afternoon of the two disagreeing, is the first thing
        anybody wants to know. So it is always shown, and always says
        why.
        """
        self.ensure_one()
        _ = self.env._
        product = self.product_id
        if not product:
            return ''
        if not product.fitness_is_subscription_plan:
            return _("Packs carry no registration fee.")
        if self.payment_method == 'free':
            return _("Nothing is charged on a gift, the fee included.")
        if not self.partner_id:
            return _("Choose the student: the fee depends on whether this "
                     "is her first membership.")
        months = self.env['product.template'].fitness_plan_months(
            self._effective_plan())
        waived_from = self.env['product.template'].MATRICULA_WAIVED_FROM_MONTHS
        if months >= waived_from:
            return _("Waived: %(months)s months or more.",
                     months=waived_from)
        if product.fitness_has_paid_membership_before(self.partner_id):
            return _("Waived: she has held a membership before. It is "
                     "charged once, on a first membership.")
        if not self.matricula_fee:
            return _("No registration product is set up, so none is "
                     "charged.")
        return _("Charged once, on a first membership under %(months)s "
                 "months.", months=waived_from)

    def _matricula_fee(self):
        """The registration fee this sale will carry, gross, or 0.00.

        Asked of the same method that actually builds the line, so the
        figure on the form and the figure on the order cannot disagree.
        Anything else is a second opinion about the studio's own rule.
        """
        self.ensure_one()
        # A gift is a gift. Nothing is charged for it, so nothing is
        # charged alongside it either - the shared line builder appends
        # the fee whenever the studio's rule says it is due, which on a
        # free first membership produced a 0.00 pack and a 39.00 order
        # with nobody to collect it from.
        if self.payment_method == 'free':
            return 0.0
        product = self.product_id
        if not (product and product.fitness_is_subscription_plan
                and self.partner_id):
            return 0.0
        matricula = product.fitness_matricula_due(
            self.partner_id, self._effective_plan())
        return matricula.fitness_effective_price() if matricula else 0.0

    def _matricula_variant_ids(self):
        """The variant ids of the registration product, or []."""
        self.ensure_one()
        product = self.product_id
        if not (product and product.fitness_is_subscription_plan):
            return []
        matricula = product.fitness_matricula_due(
            self.partner_id, self._effective_plan())
        return matricula.product_variant_ids.ids if matricula else []

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

    # Every one of these defaults to normal_price, which now INCLUDES the
    # registration fee. The figure the manager is shown is the figure she
    # collects and the figure the order comes to - the three used to differ
    # by the fee, which is how 145.00 was taken against a 177.23 order.
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
                wiz.amount_paid = wiz.normal_price

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        """A longer commitment is a different price, and drops the fee.

        Three months or more waives the registration fee outright, so
        switching Mensual to Trimestral has to move the total twice over -
        more months of membership, and no fee at all.
        """
        for wiz in self:
            if wiz.product_id and wiz.product_id.fitness_is_subscription_plan:
                wiz.amount_paid = wiz.normal_price

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Whether the fee applies depends on WHO is buying.

        It is charged on a first membership and waived on a second, so
        picking the student changes the total. Without this the form
        would show the fee for everybody and collect it from nobody, or
        the reverse.
        """
        for wiz in self:
            if wiz.product_id and wiz.payment_method == 'cash':
                wiz.amount_paid = wiz.normal_price

    @api.onchange('payment_method')
    def _onchange_payment_method(self):
        for wiz in self:
            if wiz.payment_method == 'free':
                wiz.amount_paid = 0.0
            elif wiz.product_id and not wiz.amount_paid:
                wiz.amount_paid = wiz.normal_price

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

        The figure typed in covers the WHOLE sale, registration fee
        included, because that is what the manager is told to collect and
        what the form now shows her. The fee is a fixed studio charge and
        prices itself, so it comes off the top and the membership takes
        the rest - and a discount she types therefore comes off the
        membership, not off the registration. The order then totals
        exactly the cash in the till, which is the whole point: it used
        to total the cash PLUS the fee, so 145.00 taken became a 177.23
        order and an invoice nobody could reconcile.
        """
        self.ensure_one()
        if self.payment_method == 'free':
            return 0.0
        membership_gross = (self.amount_paid or 0.0) - self._matricula_fee()
        return self.product_id.fitness_price_unit_for_gross(
            membership_gross, self.partner_id)

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
        # The fee prices itself and comes off the top, so a figure below it
        # would leave the membership at a negative price and the order
        # totalling less than the fee alone. Refused here rather than
        # silently clamped: a manager who types 30.00 against a 39.00
        # registration has made a mistake worth telling her about.
        fee = self._matricula_fee()
        if self.payment_method == 'cash' and fee \
                and (self.amount_paid or 0.0) < fee:
            raise UserError(_(
                "This sale carries a %(fee)s registration fee, so the cash "
                "taken cannot be less than that. The whole sale comes to "
                "%(total)s.",
                fee="%.2f" % fee, total="%.2f" % self.normal_price))

        product = self.product_id
        plan = self._effective_plan()
        # The same builder checkout uses, so the desk sells what the shop
        # sells: the matricula when the studio's two conditions are met, and
        # no months multiplier here because the figure below is the cash taken
        # for the whole sale, not a price per month.
        lines = product.fitness_order_line_vals(
            self.partner_id, plan=plan, total_price=self._price_to_charge())
        # A gift carries no registration fee. The shared builder adds one
        # whenever the studio's rule says it is due, which is right for a
        # sale and wrong for a giveaway: it produced a 0.00 membership
        # line beside a 39.00 fee, so an order that was supposed to cost
        # nothing came to 39.00 with no invoice and nobody to collect it.
        if self.payment_method == 'free':
            mat_ids = self._matricula_variant_ids()
            if mat_ids:
                lines = [l for l in lines
                         if l.get('product_id') not in mat_ids]
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

        # A fixed-class plan sold here arrives with no weekly hour, because
        # the hour is chosen in the app and this sale never went near it.
        # Placement will book nothing and say nothing, so this is said twice
        # on purpose: in the chatter, where it survives, and in the message
        # the manager is about to read - she may have no access to the order
        # itself and never see the chatter at all.
        slot_warning = order._fitness_fixed_slot_message()
        if slot_warning:
            order.message_post(body=slot_warning)

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
                    'type': 'warning' if slot_warning else 'success',
                    # Sticky when there is something to do about it: a
                    # message that fades is no use to somebody who has to act
                    # on it after the student has walked away.
                    'sticky': bool(slot_warning),
                    'message': _(
                        "%(order)s created for %(who)s.",
                        order=order.name, who=self.partner_id.name)
                    + ((' ' + slot_warning) if slot_warning else ''),
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
