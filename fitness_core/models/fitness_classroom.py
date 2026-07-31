from odoo import models, fields


class FitnessClassroom(models.Model):
    _name = 'fitness.classroom'
    _description = 'Fitness Classroom'
    _order = 'name'

    name = fields.Char("Name", required=True)
    classroom_type = fields.Selection([
        ('barre', 'Barre Studio'),
        ('reformer', 'Reformer Pilates'),
    ], string="Type", required=True)
    capacity = fields.Integer(
        "Capacity",
        required=True,
        default=1,
        help="Maximum number of students per class session.",
    )
    fixed_capacity = fields.Boolean(
        "Fixed Capacity",
        default=False,
        help="When enabled, the capacity is determined by physical equipment "
             "(e.g. 6 reformer machines) and cannot be changed per session.",
    )
    equipment = fields.Text("Equipment")
    description = fields.Text("Description")
    active = fields.Boolean(default=True)
    color = fields.Integer("Color Index")
