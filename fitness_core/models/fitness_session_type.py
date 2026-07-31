from odoo import models, fields


class FitnessSessionType(models.Model):
    _name = 'fitness.session.type'
    _description = 'Session Type (Group, Private, Duo)'
    _order = 'sequence, name'

    name = fields.Char("Session Type", required=True, translate=True)
    code = fields.Char("Code", required=True, help="e.g. GROUP, PRIVATE, DUO")
    description = fields.Text("Description", translate=True)
    capacity_min = fields.Integer("Min Participants", default=1)
    capacity_max = fields.Integer("Max Participants", default=1)
    sequence = fields.Integer("Sequence", default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "Session Type code must be unique!",
    )
