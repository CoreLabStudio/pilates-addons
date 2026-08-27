"""Stop a student paying twice for the same order.

Odoo's `/my/orders/<id>/transaction` route (sale.controllers.portal.PaymentPortal)
validates only the access token and the partner. It does not check whether the
order has already been paid, so a second POST creates a second payment intent and
charges the card again.

That is not theoretical: order S00177 (EUR 181.50) carries two distinct successful
Stripe charges, pi_3U8EC2... at 06:50:44 and pi_3U8EDk... at 06:52:30, two minutes
apart. The student was charged twice for one order.

The existing guard in `packages_stripe_pay` only covers rendering the payment page,
so a tab left open, a back-button, or a double submit walks straight past it. The
block has to sit on the route that actually creates the transaction.

Two conditions are refused:

1. The order is already fully paid (`_is_paid()`, the same helper Odoo itself uses
   to decide which orders to invoice).
2. A transaction for this order is already pending / authorized / done. This closes
   the narrower race where a second submit arrives before the first has settled, at
   which point `_is_paid()` is not yet true.
"""

import logging
from datetime import timedelta

from odoo import _, fields
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.sale.controllers.portal import PaymentPortal

_logger = logging.getLogger(__name__)

# A transaction in any of these states means money is already committed or moving.
BLOCKING_TX_STATES = ('pending', 'authorized', 'done')

# 'pending' is not always temporary. Bizum sits pending while the customer
# authorises on their banking app, and an abandoned authorisation never
# resolves. Blocking on it forever would lock the order, so a pending
# transaction only blocks while it is recent enough to still be in flight.
# 'authorized' and 'done' mean money really is committed and never expire.
PENDING_GRACE_MINUTES = 30


class FitnessPaymentPortal(PaymentPortal):

    def portal_order_transaction(self, order_id, access_token, **kwargs):
        order_sudo = request.env['sale.order'].sudo().browse(order_id).exists()

        if order_sudo:
            if order_sudo.state not in ('draft', 'sent') and order_sudo._is_paid():
                _logger.warning(
                    "Blocked duplicate payment: order %s is already paid "
                    "(paid=%s of %s).",
                    order_sudo.name, order_sudo.amount_paid, order_sudo.amount_total,
                )
                raise ValidationError(_(
                    "This order has already been paid. You have not been charged again."
                ))

            cutoff = fields.Datetime.now() - timedelta(minutes=PENDING_GRACE_MINUTES)
            in_flight = order_sudo.transaction_ids.filtered(
                lambda tx: (
                    tx.state in ('authorized', 'done')
                    or (tx.state == 'pending'
                        and (tx.last_state_change or tx.create_date or cutoff) >= cutoff)
                )
            )
            if in_flight:
                _logger.warning(
                    "Blocked duplicate payment: order %s already has transaction(s) %s "
                    "in state(s) %s.",
                    order_sudo.name, in_flight.mapped('reference'),
                    in_flight.mapped('state'),
                )
                raise ValidationError(_(
                    "A payment for this order is already being processed. "
                    "Please wait a moment before trying again - you have not been "
                    "charged twice."
                ))

        return super().portal_order_transaction(order_id, access_token, **kwargs)
