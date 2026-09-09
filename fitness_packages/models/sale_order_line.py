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
    # The discipline of THIS pool.
    #
    # It used to be related='product_id.fitness_class_type', which gives the
    # same answer for every line of a product - fine while a product meant
    # exactly one discipline. A combo sells two, as two lines against one
    # product, so the product can no longer answer it: the line carries its
    # own.
    #
    # Stored, computed with readonly=False, so existing lines keep reporting
    # their product's discipline with nothing to migrate, while a combo's
    # second line can be told it is the other one.
    fitness_class_type = fields.Selection([
        ('barre',    'Barre'),
        ('reformer', 'Reformer Pilates'),
        ('any',      'Any'),
    ], string="Class Type", store=True, readonly=False,
        compute='_compute_fitness_class_type',
        help="The discipline these credits may be spent on. Normally the "
             "product's own; on the second line of a combined package it is "
             "the second discipline.",
    )
    fitness_session_type = fields.Selection(
        related='product_id.fitness_session_type', store=False, string="Session Type",
    )

    fitness_is_secondary_pool = fields.Boolean(
        "Second Pool Line",
        default=False,
        copy=True,
        help="Marks the extra line a combined package adds to carry its second "
             "discipline's credits. It is a credit pool, not a second thing "
             "being sold: the whole price sits on the first line, so this one "
             "is always worth nothing.",
    )

    # price_unit and discount are STORED COMPUTES with readonly=False. A value
    # written at create is honoured, but nothing in the database remembers that
    # it was deliberate: on any later touch of a dependency - the pricelist,
    # the quantity, the product - Odoo recomputes both from the product and
    # overwrites them.
    #
    # For an ordinary line that is invisible, because the recomputed value is
    # the price it already had. For this one it was not: a 0.00 became the full
    # price and the membership was charged twice. Writing a 100% discount
    # instead failed the same way, because discount is recomputed too.
    #
    # So the value is not written and defended, it is computed. These overrides
    # make "nothing" the answer the recompute itself produces, which means
    # there is no longer a disagreement for a recompute to resolve wrongly.
    @api.depends('fitness_is_secondary_pool')
    def _compute_price_unit(self):
        secondary = self.filtered('fitness_is_secondary_pool')
        super(SaleOrderLine, self - secondary)._compute_price_unit()
        for line in secondary:
            line.price_unit = 0.0

    @api.depends('fitness_is_secondary_pool')
    def _compute_discount(self):
        secondary = self.filtered('fitness_is_secondary_pool')
        super(SaleOrderLine, self - secondary)._compute_discount()
        for line in secondary:
            line.discount = 0.0

    @api.depends('product_id')
    def _compute_fitness_class_type(self):
        for line in self:
            # Never overwrite a discipline that is already set. A combo's
            # second line is created carrying the secondary type, and
            # recomputing it on any later write would quietly move those
            # credits into the wrong pool.
            if not line.fitness_class_type:
                line.fitness_class_type = line.product_id.fitness_class_type

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

        # The LINE's discipline, not the product's. On a combined package the
        # product is both, and reading it here would let Barre credits pay for
        # a Reformer class and empty one pool into the other - which is the
        # single thing separate pools exist to prevent.
        pool_type = self.fitness_class_type or product.fitness_class_type
        if pool_type != 'any' and pool_type != event_studio:
            raise ValidationError(
                f"These credits are for {pool_type or 'unset'} classes and "
                f"cannot be used for a {event_studio or 'unset'} class."
            )
        if product.fitness_session_type != event_session:
            raise ValidationError(
                f"This package is for '{product.fitness_session_type}' sessions only; "
                f"the selected class is a '{event_session}' session."
            )
