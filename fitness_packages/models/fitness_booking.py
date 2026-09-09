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

    # ─── The one booking allowed past the seven-day window ─────────────

    TRIAL_XMLIDS = ('fitness_packages.product_barre_trial',
                    'fitness_packages.product_reformer_trial')

    def _skip_booking_window(self, vals, student, event):
        """A student's first booking, paid for by their free trial.

        Three conditions, all read from the booking rather than sent with it.
        The third is what keeps this tight: by the time validation runs the
        payment source has already been chosen and written into vals, so this
        can ask which line is paying and exempt only a booking actually
        charged to a trial credit. An ordinary paid booking cannot satisfy it,
        whatever it sends, so the window still applies everywhere else.
        """
        if super()._skip_booking_window(vals, student, event):
            return True

        line_id = vals.get('package_order_line_id')
        if not line_id:
            return False

        trials = self.env['product.template'].browse()
        for xmlid in self.TRIAL_XMLIDS:
            product = self.env.ref(xmlid, raise_if_not_found=False)
            if product:
                trials |= product.sudo()
        if not trials:
            return False

        line = self.env['sale.order.line'].sudo().browse(line_id)
        if line.product_id.product_tmpl_id.id not in trials.ids:
            return False

        # Nothing about booking history. A trial credit pays for exactly one
        # class whoever holds it, so "this booking is charged to a trial line"
        # is the whole rule - and it is read off the source the server chose,
        # never off anything the student sent.
        _logger.info(
            "[TRIAL] Booking for student=%s paid by trial line %s - "
            "seven-day window waived", student.id, line_id)
        return True

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
