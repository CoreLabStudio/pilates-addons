import logging
from datetime import timedelta

from odoo import api, models, fields, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# How long the studio gives a student to turn up with the money. Nothing
# expires on its own - an unpaid request simply stays on the studio's list,
# because deciding it is too late is the studio's call and not a cron's.
CASH_WINDOW_HOURS = 24


class SaleOrder(models.Model):
    """Records what the student chose in the portal checkout's Payment step.

    Purely a record of the student's declared intent — no payment is taken
    online. The studio reconciles the Bizum / bank transfer manually, exactly
    as it did before this step existed.
    """
    _inherit = 'sale.order'

    fitness_payment_method = fields.Selection([
        ('stripe', 'Stripe (Online)'),
        ('bizum', 'Bizum'),
        ('transfer', 'Bank Transfer'),
        # Taken in person at the desk. This used to mean the money was
        # already in the till before the order was written, so a cash order
        # was not waiting on anybody. It now also covers a student asking in
        # the portal to pay cash, which is the opposite: nothing is hers
        # until somebody at the desk says the money arrived. The two are told
        # apart by fitness_cash_requested_on, not by the method.
        ('cash', 'Cash (at the studio)'),
        # Not a method so much as the absence of one: the order came to zero,
        # so nothing was charged and no provider was involved. Recorded rather
        # than left blank so a free order is tellable from one whose method was
        # never set, which is what the unpaid-confirmation guard keys on.
        ('free', 'Free (no payment)'),
    ], string="Portal Payment Method", copy=False,
        help="Payment method the student selected during portal checkout.")

    fitness_terms_accepted_on = fields.Datetime(
        "Terms Accepted On", copy=False, readonly=True,
        help="When the student ticked 'I agree to the Terms and Conditions' "
             "during portal checkout.",
    )

    # ── A student asking to pay cash ───────────────────────────────────────
    #
    # She chooses Cash in the portal and the order stops there: draft, no
    # credits, nothing bookable. It becomes real only when somebody at the
    # desk confirms the money arrived. Holding it as a draft order rather
    # than a separate request model is deliberate - the thing she asked for
    # is already described perfectly by the order lines, and approving it has
    # to run the same confirmation an online purchase runs, not a parallel
    # one that drifts.
    fitness_cash_requested_on = fields.Datetime(
        "Cash Requested On", copy=False, readonly=True,
        help="When the student asked to pay this order in cash at the "
             "studio. Set only by the portal; a desk sale leaves it empty.",
    )
    fitness_cash_approved_on = fields.Datetime(
        "Cash Approved On", copy=False, readonly=True,
        help="When the studio confirmed the cash was received.",
    )
    fitness_cash_approved_by = fields.Many2one(
        'res.users', "Cash Approved By", copy=False, readonly=True,
    )
    fitness_cash_pending = fields.Boolean(
        "Waiting For Cash", compute='_compute_fitness_cash_pending',
        store=True,
        help="A student has asked to pay cash and has not yet been "
             "confirmed as having paid.",
    )
    fitness_cash_deadline = fields.Datetime(
        "Pay By", compute='_compute_fitness_cash_pending', store=True,
        help="24 hours after the request. Shown to the student and used to "
             "sort the studio's list; nothing expires on its own.",
    )

    @api.depends('fitness_cash_requested_on', 'fitness_cash_approved_on',
                 'state')
    def _compute_fitness_cash_pending(self):
        for order in self:
            asked = order.fitness_cash_requested_on
            order.fitness_cash_pending = bool(
                asked and not order.fitness_cash_approved_on
                and order.state in ('draft', 'sent'))
            order.fitness_cash_deadline = (
                asked + timedelta(hours=CASH_WINDOW_HOURS) if asked else False)

    def action_fitness_decline_cash(self):
        """She did not come with the money. Close the request.

        A separate action rather than the generic Cancel, because the studio
        needs to be able to say so: the reason is written to the chatter and
        the student is told, so a request that quietly vanished can never be
        confused with one nobody acted on.

        The order is cancelled rather than deleted. It is the record of what
        she asked for, and deleting it would leave the studio unable to say
        whether a request had ever existed.
        """
        if not (self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user._is_admin()):
            raise AccessError(self.env._(
                "Only studio managers can decline a cash payment."))

        reason = (self.env.context.get('fitness_decline_reason') or '').strip()
        for order in self.sudo():
            if not order.fitness_cash_requested_on:
                raise UserError(self.env._(
                    "%(name)s is not a cash request.", name=order.name))
            if order.fitness_cash_approved_on:
                raise UserError(self.env._(
                    "%(name)s was already approved and cannot be declined.",
                    name=order.name))

            order._action_cancel()
            order.message_post(body=self.env._(
                "Cash request declined by %(user)s.%(why)s",
                user=self.env.user.name,
                why=(" %s" % reason) if reason else ""))

            # Tell her, in her own language. A request that disappears with
            # no word is worse than a refusal: she turns up expecting a class
            # she no longer has.
            user = order.partner_id.user_ids[:1]
            if user:
                translate = self.env(context=dict(
                    self.env.context, lang=user.lang or 'es_ES'))._
                line = order.order_line[:1]
                what = line.product_id.display_name if line else order.name
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'cash_requested',
                    translate('Your cash payment was not completed'),
                    translate(
                        'We did not receive payment for %(product)s, so the '
                        'order has been closed. Come to the studio or order '
                        'again in the app whenever you are ready.',
                        product=what),
                    action_url='/my/packages',
                )
            _logger.info("[CASH] %s declined by %s", order.name,
                         self.env.user.name)
        return True

    def action_fitness_approve_cash(self):
        """The money arrived. Make the purchase real.

        Runs the same two steps the portal runs when a card payment
        succeeds - action_confirm(), then tell the studio - so a cash
        purchase and an online one leave the student in exactly the same
        place: same credits, same validity, same matricula rules, same
        invoice, same notification. Anything done differently here is a
        difference she would eventually find.
        """
        # Gate explicitly, then read through sudo. A fitness manager cannot
        # read sale.order at all - group_fitness_manager grants nothing on
        # it - so without the sudo this fails on the very first field access,
        # for exactly the people the button is for. Without the explicit
        # check, the sudo would then let anybody who can reach the method
        # approve their own order.
        if not (self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user._is_admin()):
            raise AccessError(self.env._(
                "Only studio managers can approve a cash payment."))

        for order in self.sudo():
            if not order.fitness_cash_requested_on:
                raise UserError(self.env._(
                    "%(name)s is not a cash request.", name=order.name))
            if order.fitness_cash_approved_on:
                raise UserError(self.env._(
                    "%(name)s has already been approved.", name=order.name))
            if order.state not in ('draft', 'sent'):
                raise UserError(self.env._(
                    "%(name)s is already confirmed.", name=order.name))

            order_sudo = order
            order_sudo.write({
                'fitness_cash_approved_on': fields.Datetime.now(),
                'fitness_cash_approved_by': self.env.user.id,
            })
            order_sudo.action_confirm()
            # The invoice, settled in cash and mailed - the same three steps
            # a desk sale takes, because the money arrived the same way.
            try:
                invoice = order_sudo.fitness_invoice_cash_sale()
                if invoice:
                    order_sudo.fitness_settle_invoice_in_cash(invoice)
                    order_sudo.fitness_email_invoice(invoice)
            except Exception:
                # An invoicing problem must not un-sell the class she has
                # just paid for in front of somebody. The purchase stands and
                # the studio is told.
                _logger.exception(
                    "[CASH] %s confirmed but could not be invoiced",
                    order.name)
            order_sudo.message_post(body=self.env._(
                "Cash received and approved by %(user)s.",
                user=self.env.user.name))
            _logger.info("[CASH] %s approved by %s (requested %s)",
                         order.name, self.env.user.name,
                         order.fitness_cash_requested_on)
        return True


    # ── Taking cash: invoice it, settle it, send it ────────────────────────
    #
    # Moved off the desk wizard so the renewal path can use the same steps.
    # Two ways of taking money at the desk must not end up disagreeing about
    # what the student receives - one invoice, one payment entry, one email,
    # whichever screen the manager was on.
    def fitness_invoice_cash_sale(self):
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
        invoice = self._create_invoices()
        if not invoice:
            _logger.warning(
                "[CASH] %s produced no invoice - nothing to post", self.name)
            return invoice
        invoice.action_post()
        _logger.info("[CASH] invoice %s posted for order %s (%.2f)",
                     invoice.name, self.name, invoice.amount_total)
        self.fitness_settle_invoice_in_cash(invoice)
        return invoice

    def fitness_settle_invoice_in_cash(self, invoice):
        """Mail a posted invoice and settle it from the cash drawer.

        Split out from the sale above because a renewal arrives here with its
        invoice already made - Odoo's own recurring machinery raises it - and
        only these two steps are left. One implementation, so a first sale and
        a renewal cannot come to disagree about what the student receives.
        """
        self.ensure_one()
        if not invoice or invoice.state != 'posted':
            return invoice
        self.fitness_email_invoice(invoice)

        # sudo throughout: a fitness manager is not an accounting user and
        # cannot read a journal, let alone register a payment. Taking cash is
        # something the studio authorises her to do; the entry that follows is
        # a consequence of it, not a second permission she has to hold.
        journal = self.env['account.journal'].sudo().search([
            ('type', '=', 'cash'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            _logger.warning(
                "[CASH] no cash journal on %s, so invoice %s is posted "
                "but unpaid - the money was taken, the entry is not made",
                self.company_id.name, invoice.name)
            return invoice
        try:
            self.env['account.payment.register'].sudo().with_context(
                active_model='account.move', active_ids=invoice.ids,
            ).create({'journal_id': journal.id}).action_create_payments()
            _logger.info("[CASH] invoice %s paid from %s",
                         invoice.name, journal.name)
        except Exception:
            # The sale and its invoice are real whatever happens here; losing
            # them to a payment-registration problem would be the worse trade.
            _logger.exception(
                "[CASH] could not register the cash payment for %s",
                invoice.name)
        return invoice

    def fitness_email_invoice(self, invoice):
        """Mail the invoice, the way an online purchase mails it.

        Posting does not send anything. Online, the mail comes from
        sale's `send_invoice_cron`, and that cron searches **payment
        transactions**:

            self.search([('state', '=', 'done'),
                         ('is_post_processed', '=', True), ...])._send_invoice()

        A cash sale has no transaction, so it can never be selected - not on
        posting and not later. f34c389 said posting "is what mails it, through
        the action_post override in fitness_notifications"; that override
        creates an in-app notification, not an email. So the cash buyer got a
        correct invoice she was never sent, which is the inconsistency that
        commit set out to remove, one step further along.

        Sent here through the same helper and the same configured template the
        online path uses, so there is one invoice mail in the system rather
        than a second one that drifts. Never allowed to raise: the money is in
        the till and the invoice is posted, and a mail-server problem must not
        undo either.
        """
        if not invoice or invoice.state != 'posted':
            return
        try:
            to_send = invoice.filtered(
                lambda i: not i.is_move_sent and i._is_ready_to_be_sent())
            if not to_send:
                _logger.info("[CASH] invoice %s was already sent",
                             invoice.name)
                return

            # Some students have no email address at all - see
            # RUNBOOK-students-without-email.md. That is a supported state,
            # not a broken contact, and it is handled here rather than left
            # to account.move.send, which drops the mail silently further
            # down and leaves this method claiming it sent one.
            #
            # is_move_sent is deliberately not set for them. Marking an
            # invoice sent when nothing was sent means that if she gives us
            # an address later, this invoice is skipped for ever on the
            # grounds that it already went out.
            unreachable = to_send.filtered(lambda i: not i.partner_id.email)
            if unreachable:
                _logger.info(
                    "[CASH] invoice %s not emailed - %s has no email "
                    "address; hand her a printed copy",
                    invoice.name, invoice.partner_id.display_name)
                to_send -= unreachable
            if not to_send:
                return
            send_context = {'allow_raising': False, 'allow_fallback_pdf': True}
            template_id = self.env['ir.config_parameter'].sudo().get_param(
                'sale.default_invoice_email_template', False)
            if template_id:
                template = self.env['mail.template'].sudo().browse(
                    int(template_id))
                if template.exists():
                    send_context['mail_template'] = template
            to_send.is_move_sent = True
            self.env['account.move.send'].sudo()._generate_and_send_invoices(
                to_send, **send_context)
            _logger.info("[CASH] invoice %s emailed to %s",
                         invoice.name, invoice.partner_id.email or '(no email)')
        except Exception:
            _logger.exception(
                "[CASH] could not email invoice %s - it is posted and "
                "the sale stands", invoice.name)


    # ── Renewing a membership from the desk, in cash ───────────────────────
    #
    # Here and not in fitness_subscriptions: it calls the cash methods
    # above, and fitness_subscriptions does not depend on this module -
    # the dependency runs the other way. It would have worked with both
    # installed and broken fitness_subscriptions on its own.

    def action_fitness_renew_cash(self, new_plan=None):
        """Take the next period's money in cash, on the plan she is already on.

        Odoo renews a subscription by invoicing its next period and moving
        next_invoice_date forward; _create_recurring_invoice() is that
        machinery. Called on a recordset it narrows to those ids and drops the
        `next_invoice_date <= today` filter the cron applies, so the studio
        can take the money on the day or a little before it - which is when a
        student standing at the desk actually pays.

        Deliberately NOT a new order. A renewal is the same membership
        continuing: a second order per renewal would give her a pile of
        subscriptions instead of one plan with a history, and the weekly
        allowance is read off the subscription she is on.

        Changing the commitment - Mensual to Trimestral - is a different act
        and does not come through here; that is prepare_renewal_order(), which
        raises a renewal quotation that can carry a different plan.
        """
        self.ensure_one()
        if not (self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only a studio manager can renew a membership."))
        # Everything below reads and writes through sudo. A fitness manager
        # cannot read sale.order at all - Odoo reserves it for Sales and
        # Accounting groups - so even `self.is_subscription` raises AccessError
        # for her. It did not show up at first because the tests had the
        # values in ORM cache from creating them as admin; the moment a test
        # invalidated the cache, every read failed. Taking payment for a
        # membership is something the studio authorises her to do; reading the
        # order behind it is a consequence of that, not a second permission
        # she has to hold.
        order = self.sudo()
        if not order.is_subscription:
            raise UserError(_(
                "%(name)s is not a membership, so there is nothing to renew.",
                name=order.name))
        if order.subscription_state != '3_progress':
            raise UserError(_(
                "%(name)s is not running, so it cannot be renewed. Reopen it "
                "first.", name=order.name))

        if new_plan and new_plan.id != order.plan_id.id:
            return order._fitness_renew_cash_on_a_new_plan(new_plan)

        before = order.next_invoice_date
        # NOT _create_recurring_invoice(). That is the cron's machinery, and
        # _get_subscriptions_to_invoice() - its own docstring says "remove
        # subscriptions that should send a reminder instead of invoicing" -
        # drops any member with no saved card and full prepayment. Odoo mails
        # her a payment link instead. That is exactly the member who pays
        # cash: three of this studio's four hold no token, and calling it here
        # returned an empty recordset for every one of them.
        #
        # So the line is invoiced directly and the period is advanced through
        # _update_next_invoice_date(), which is the studio's own override -
        # it resets the weekly counter, carries floating credits forward, sets
        # the new period's start and re-places the Clase Fija. Renewing
        # without it would leave her period bookkeeping on the old cycle.
        invoice = order._create_invoices()
        if not invoice:
            raise UserError(_(
                "Odoo raised no invoice for %(name)s, so nothing was "
                "renewed and no money has been recorded. Its next billing "
                "date is %(date)s.",
                name=order.name, date=before or _("not set")))

        # The same three steps the desk already takes for a cash sale: post
        # it, settle it from the cash journal, email it. One implementation,
        # so a renewal and a first sale cannot come to disagree about what the
        # student receives.
        invoice = invoice.sudo()
        if invoice.state == 'draft':
            invoice.action_post()
        # The invoice covers the period being paid for, so it is raised first
        # and the clock moved afterwards.
        order._update_next_invoice_date()
        order.fitness_settle_invoice_in_cash(invoice)

        order.invalidate_recordset(['next_invoice_date'])
        _logger.info(
            "[RENEWAL] %s renewed in cash by %s: invoice %s, next billing "
            "%s -> %s", order.name, self.env.user.login, invoice.name,
            before, order.next_invoice_date)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': False,
                'title': _("Membership renewed"),
                'message': _(
                    "%(who)s is paid up to %(date)s. Invoice %(inv)s was "
                    "sent to her.",
                    who=order.partner_id.name,
                    date=order.next_invoice_date or '-',
                    inv=invoice.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


    def _fitness_renew_cash_on_a_new_plan(self, new_plan):
        """Renew onto a different commitment - Mensual to Trimestral.

        Not the same act as renewing in place. The plan is what she is
        committed to, so changing it starts a new contract rather than
        extending the old one, and Odoo models that as a renewal quotation:
        _create_renew_upsell_order('2_renewal') raises one that begins the day
        the current period ends, linked back to what it replaces.

        Odoo refuses to raise one before the first period has been invoiced -
        "you can not upsell or renew a subscription that has not been invoiced
        yet" - which is right: there is nothing to renew from. Surfaced as a
        sentence about her membership rather than the raw ValidationError.

        The price is rebuilt for the new commitment, because a Trimestral is
        three months charged at once, and the matricula is asked again on the
        new plan - a three-month commitment waives it.
        """
        self.ensure_one()
        # Called with a sudo'd record by action_fitness_renew_cash, because a
        # fitness manager cannot read sale.order. Re-sudoed here so a future
        # caller cannot reintroduce that fault by reaching it another way.
        self = self.sudo()
        if self.start_date == self.next_invoice_date:
            raise UserError(_(
                "%(name)s has not been billed for its first period yet, so "
                "there is nothing to renew from. Renew it on its current "
                "plan first, or change the plan on the membership itself.",
                name=self.name))

        # fitness_subscription_product_id is the VARIANT - it is set from
        # order_line.product_id - and the purchase rules live on the template.
        variant = self.fitness_subscription_product_id
        if not variant:
            raise UserError(_(
                "%(name)s carries no membership product, so its plan cannot "
                "be changed.", name=self.name))
        product = variant.product_tmpl_id

        digest = self._get_order_digest(
            origin='renewal', lang=self.partner_id.lang or self.env.user.lang)
        quotation = self.sudo()._create_renew_upsell_order('2_renewal', digest)

        # Plan first, then the lines - never together. Writing plan_id beside
        # order_line discards an explicit price_unit, which is how a quarterly
        # membership at 585.00 came to bill 195.00 on production.
        quotation.write({'plan_id': new_plan.id})
        quotation.flush_recordset()
        lines = product.sudo().fitness_order_line_vals(
            self.partner_id, plan=new_plan)
        quotation.write({'order_line': [(5, 0, 0)] + [(0, 0, v) for v in lines]})
        quotation.action_confirm()

        invoice = quotation.sudo()._create_invoices()
        if not invoice:
            raise UserError(_(
                "The new commitment %(q)s was created but nothing could be "
                "invoiced, so no money has been recorded.", q=quotation.name))
        invoice = invoice.sudo()
        if invoice.state == 'draft':
            invoice.action_post()
        quotation.sudo()._update_next_invoice_date()
        quotation.sudo().fitness_settle_invoice_in_cash(invoice)

        _logger.info(
            "[RENEWAL] %s renewed in cash onto %s as %s by %s (invoice %s)",
            self.name, new_plan.display_name, quotation.name,
            self.env.user.login, invoice.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': False,
                'title': _("Membership renewed on a new plan"),
                'message': _(
                    "%(who)s is now on %(plan)s as %(q)s. Invoice %(inv)s was "
                    "sent to her.",
                    who=self.partner_id.name, plan=new_plan.display_name,
                    q=quotation.name, inv=invoice.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SaleOrderLine(models.Model):
    """How a pack was paid for, readable from the pack itself.

    The payment method is recorded on the order, but the studio reads the
    balances list, which is lines - so answering "did she pay cash for this
    one" meant opening the order. Lives here rather than in fitness_packages
    because the field it mirrors is defined in this module.
    """
    _inherit = 'sale.order.line'

    fitness_payment_method = fields.Selection(
        related='order_id.fitness_payment_method', string='Paid By',
        readonly=True)
