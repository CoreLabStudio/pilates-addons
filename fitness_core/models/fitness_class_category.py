from odoo import models, fields


class FitnessClassCategory(models.Model):
    _name = 'fitness.class.category'
    _description = 'Class Category'
    _order = 'name'

    name = fields.Char('Name', required=True, translate=True)
    image_1920 = fields.Image('Image', max_width=1920, max_height=1920)
    image_512 = fields.Image(
        'Image (512)', related='image_1920',
        max_width=512, max_height=512, store=True, readonly=True,
    )
