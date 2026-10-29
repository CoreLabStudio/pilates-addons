from odoo import models

from odoo.addons.fitness_core.models.studio_lang import recipient_lang

import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """Notify a student in-app when an invoice is issued to them.

    Previously the money side of the app was silent in both directions: a
    student was told nothing when an invoice was raised, and nobody was told
    when a student bought a package. This closes the student half; the admin
    half is raised from the portal checkout in fitness_portal.
    """
    _inherit = 'account.move'

    def _fitness_notify_invoice(self):
        Notif = self.env['fitness.notification'].sudo()
        studio = self.env.company.name or 'CoreLab'
        for move in self:
            if move.move_type != 'out_invoice' or move.state != 'posted':
                continue
            partner = move.partner_id
            if not partner:
                continue
            # Only students get portal notifications; other customers do not
            # use the app and would never see them.
            user = self.env['res.users'].sudo().search([
                ('partner_id', '=', partner.id),
            ], limit=1)
            if not user or not user.has_group('fitness_core.group_fitness_student'):
                continue
            # Notify in the recipient's own language, not the poster's.
            lang = recipient_lang(self.env, user)
            translate = self.with_context(lang=lang).env._
            title = translate('Invoice %(number)s received from %(studio)s') % {
                'number': move.name or '',
                'studio': studio,
            }
            # "Amount due" on an invoice she has already paid reads as a
            # second bill. Paid says so; only a real balance is "due".
            if move._fitness_invoice_is_paid():
                body = translate('Paid: %(amount)s') % {
                    'amount': self._fitness_format_amount(move),
                }
            else:
                body = translate('Amount due: %(amount)s') % {
                    'amount': self._fitness_format_amount(move),
                }
            # /my/invoices/<id> is the account module's portal view; the
            # notification is about a specific invoice, so it should open it
            # rather than dead-end.
            Notif._create_for_user(user.id, 'invoice_issued', title, body,
                                   action_url='/my/invoices/%d' % move.id)
            _logger.info('[NOTIFICATIONS] Invoice %s -> student %s', move.name, user.login)

    def _fitness_invoice_is_paid(self):
        """Has she already paid what this invoice asks for?

        Asked at posting, which comes before the payment entry on every
        path that takes money up front: the card or Bizum transaction is
        done before Odoo invoices it, and the desk takes the cash before
        the invoice is settled. So it is answered from how the money came,
        not only from the ledger: paid in the ledger, or a completed online
        payment behind the order. fitness_portal adds cash taken at the desk.
        """
        self.ensure_one()
        if self.payment_state in ('paid', 'in_payment'):
            return True
        orders = self.sudo().invoice_line_ids.sale_line_ids.order_id
        txs = orders.transaction_ids if 'transaction_ids' in orders._fields else orders.browse()
        return bool(txs.filtered(lambda t: t.state == 'done'))

    @staticmethod
    def _fitness_format_amount(move):
        symbol = move.currency_id.symbol if move.currency_id else ''
        return '%.2f %s' % (move.amount_total, symbol)

    def action_post(self):
        result = super().action_post()
        try:
            self._fitness_notify_invoice()
        except Exception:
            # Never let a notification failure block invoice posting.
            _logger.exception('[NOTIFICATIONS] invoice notification failed')
        return result
