from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    fitness_original_class_count = fields.Integer(
        "Classes Purchased",
        default=0,
        help="Total class credits when the package was confirmed.",
    )
    fitness_remaining_classes = fields.Integer(
        "Classes Remaining",
        default=0,
        help="Credits left. Decrements on booking, increments on cancellation >2h.",
    )
    fitness_validity_end_date = fields.Date(
        "Valid Until",
        help="Credits cannot be used after this date.",
    )
    fitness_is_expired = fields.Boolean(
        "Expired",
        compute='_compute_fitness_is_expired',
        help="True when today is past the validity end date.",
    )
    fitness_classes_used = fields.Integer(
        "Classes Used",
        compute='_compute_fitness_classes_used',
        help="Original count minus remaining.",
    )
    # Related fields so they can be shown in list views
    fitness_class_type = fields.Selection(
        related='product_id.fitness_class_type', store=False, string="Class Type",
    )
    fitness_session_type = fields.Selection(
        related='product_id.fitness_session_type', store=False, string="Session Type",
    )

    @api.depends('fitness_validity_end_date')
    def _compute_fitness_is_expired(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.fitness_validity_end_date:
                line.fitness_is_expired = line.fitness_validity_end_date < today
            else:
                line.fitness_is_expired = False

    @api.depends('fitness_original_class_count', 'fitness_remaining_classes')
    def _compute_fitness_classes_used(self):
        for line in self:
            line.fitness_classes_used = (
                line.fitness_original_class_count - line.fitness_remaining_classes
            )

    def validate_package_for_booking(self, calendar_event):
        """Called by fitness_booking before creating a booking. Raises on failure."""
        from odoo.exceptions import ValidationError
        if self.fitness_is_expired:
            raise ValidationError(
                f"Package expired on {self.fitness_validity_end_date}. "
                "Cannot use expired credits."
            )
        if self.fitness_remaining_classes <= 0:
            raise ValidationError(
                f"No class credits remaining on this package "
                f"(original: {self.fitness_original_class_count})."
            )

        product = self.product_id
        event_studio = calendar_event.class_type_id.classroom_type or calendar_event.classroom_id.classroom_type
        event_session = calendar_event.session_type

        if product.fitness_class_type != 'any' and product.fitness_class_type != event_studio:
            raise ValidationError(
                f"This package ({product.fitness_class_type or 'unset'} discipline) cannot be used "
                f"for a {event_studio or 'unset'} class."
            )
        if product.fitness_session_type != event_session:
            raise ValidationError(
                f"This package is for '{product.fitness_session_type}' sessions only; "
                f"the selected class is a '{event_session}' session."
            )
