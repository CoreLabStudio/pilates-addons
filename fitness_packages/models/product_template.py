from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fitness_is_package = fields.Boolean(
        "Is Fitness Package",
        default=False,
        help="Enable for class-pack products. Activates credit tracking on sale order lines.",
    )
    fitness_class_count = fields.Integer(
        "Classes in Pack",
        default=1,
        help="Number of class credits granted when this product is sold.",
    )
    fitness_validity_days = fields.Integer(
        "Validity (days)",
        default=15,
        help="Credits expire this many days after the sale order is confirmed.",
    )
    fitness_class_type = fields.Selection([
        ('barre',    'Barre'),
        ('reformer', 'Reformer Pilates'),
        ('any',      'Any'),
    ], string="Class Type", default='any',
        help="Restricts which studio type the credits can be used for.",
    )
    fitness_session_type = fields.Selection([
        ('group',   'Group'),
        ('private', 'Private (1-on-1)'),
        ('duo',     'Duo (2 people)'),
    ], string="Session Type", default='group',
        help="Restricts which session type the credits can be used for.",
    )
