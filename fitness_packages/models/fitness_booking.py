from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class FitnessBookingPackage(models.Model):
    """Extends fitness.booking to integrate class-pack credit management."""
    _inherit = 'fitness.booking'

    # ─── Validation: called inside super().create() ────────────────────────────

    def _validate_new_booking(self, vals):
        super()._validate_new_booking(vals)
        line_id = vals.get('package_order_line_id')
        if not line_id:
            return
        line = self.env['sale.order.line'].browse(line_id)
        event = self.env['calendar.event'].browse(vals['calendar_event_id'])
        line.validate_package_for_booking(event)
        _logger.info("[PACKAGE] ✓ Package credit valid (%d remaining)", line.fitness_remaining_classes)

    # ─── Deduct credit after booking is created ────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        bookings = super().create(vals_list)
        for booking in bookings:
            if booking.package_order_line_id:
                # sudo(): sale.order.line write is internal bookkeeping; portal
                # users do not have write on sale.order.line (same pattern as
                # sub.sudo() in fitness_subscriptions for floating credits).
                line_sudo = booking.package_order_line_id.sudo()
                line_sudo.fitness_remaining_classes -= 1
                _logger.info(
                    "[PACKAGE] Deducted 1 credit from line %d → %d remaining",
                    booking.package_order_line_id.id,
                    line_sudo.fitness_remaining_classes,
                )
        return bookings

    # ─── Restore credit on cancellation >2 h ──────────────────────────────────

    def action_cancel(self):
        # Snapshot package lines BEFORE super sets credit_returned
        pkg_map = {
            b.id: b.package_order_line_id
            for b in self
            if b.package_order_line_id
        }
        super().action_cancel()
        for booking in self:
            line = pkg_map.get(booking.id)
            if line and booking.credit_returned:
                line_sudo = line.sudo()
                line_sudo.fitness_remaining_classes += 1
                _logger.info(
                    "[PACKAGE] Restored 1 credit to line %d → %d remaining",
                    line.id, line_sudo.fitness_remaining_classes,
                )
