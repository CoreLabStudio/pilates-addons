from odoo import models

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
            lang = user.lang or self.env.lang or 'en_US'
            translate = self.with_context(lang=lang).env._
            title = translate('Invoice %(number)s received from %(studio)s') % {
                'number': move.name or '',
                'studio': studio,
            }
            body = translate('Amount due: %(amount)s') % {
                'amount': self._fitness_format_amount(move),
            }
            # /my/invoices/<id> is the account module's portal view; the
            # notification is about a specific invoice, so it should open it
            # rather than dead-end.
            Notif._create_for_user(user.id, 'invoice_issued', title, body,
                                   action_url='/my/invoices/%d' % move.id)
            _logger.info('[NOTIFICATIONS] Invoice %s -> student %s', move.name, user.login)

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
