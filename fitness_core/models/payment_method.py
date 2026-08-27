import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    @api.model
    def _corelab_ensure_bizum_stripe(self):
        """Re-assert the Bizum/Stripe link so it survives module upgrades.

        Odoo 19's payment_stripe does not list 'bizum' in its
        DEFAULT_PAYMENT_METHOD_CODES, so Odoo never links the two by itself and
        never re-links them. If Stripe is dropped from Bizum's provider_ids, the
        studio's other three Bizum providers (Adyen, Redsys, Worldline) are all
        disabled, so _deactivate_unsupported_payment_methods archives Bizum too.
        Nothing errors: the option just stops appearing at checkout.

        Both fields have to be re-asserted, and the order matters.
        payment.method.write() runs its "needs a partner in crime" check against
        provider_ids as they stand *before* the write applies, so activating and
        linking in one write raises UserError in exactly the broken state this
        method exists to repair. Hence two writes, link first.

        Activation is skipped rather than forced when Stripe is disabled, which
        is the state a fresh production database is in before anyone enters the
        Stripe credentials. Forcing it there would raise that same UserError and
        abort the module upgrade.
        """
        bizum = self.env.ref('payment.payment_method_bizum', raise_if_not_found=False)
        stripe = self.env.ref('payment.payment_provider_stripe', raise_if_not_found=False)
        if not bizum or not stripe:
            _logger.warning(
                "CoreLab: cannot link Bizum to Stripe, records missing (bizum=%s, stripe=%s).",
                bool(bizum), bool(stripe),
            )
            return

        bizum = bizum.sudo().with_context(active_test=False)

        if stripe not in bizum.provider_ids:
            bizum.write({'provider_ids': [fields.Command.link(stripe.id)]})
            _logger.info("CoreLab: re-linked Bizum to the Stripe payment provider.")

        if not bizum.active:
            if stripe.state == 'disabled':
                _logger.warning(
                    "CoreLab: Bizum left archived because the Stripe provider is disabled."
                    " Enable Stripe, then upgrade fitness_core to finish enabling Bizum."
                )
            else:
                bizum.write({'active': True})
                _logger.info("CoreLab: re-enabled the Bizum payment method.")
