from odoo import models, fields, api


class FitnessClassType(models.Model):
    _name = 'fitness.class.type'
    _description = 'Fitness Class Type'
    _order = 'classroom_type, name'

    name = fields.Char("Class Name", required=True, translate=True)
    classroom_type = fields.Selection([
        ('barre', 'Barre'),
        ('reformer', 'Reformer Pilates'),
    ], string="Studio Type", required=True)
    classroom_id = fields.Many2one(
        'fitness.classroom',
        "Default Classroom",
    )
    duration = fields.Integer("Duration (min)", required=True, default=45)
    level = fields.Selection([
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('intermediate_advanced', 'Intermediate / Advanced'),
        ('advanced', 'Advanced'),
        ('all', 'All Levels'),
    ], string="Level", required=True)
    intensity = fields.Selection([
        ('low', 'Low'),
        ('low_moderate', 'Low-Moderate'),
        ('moderate', 'Moderate'),
        ('moderate_high', 'Moderate-High'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string="Intensity")
    session_type = fields.Selection([
        ('group', 'Group'),
        ('private', 'Private (1-on-1)'),
        ('duo', 'Duo (2 people)'),
    ], string="Session Type", default='group', required=True)
    max_capacity = fields.Integer(
        "Max Capacity",
        compute='_compute_max_capacity',
        store=True,
        help="Derived from session type and classroom. "
             "Private = 1, Duo = 2, Group = classroom capacity.",
    )
    equipment = fields.Char("Equipment / Props")
    description = fields.Text("Description", translate=True)
    image_1920 = fields.Image("Photo", max_width=1920, max_height=1920)
    image_512  = fields.Image("Photo (512)", related='image_1920', max_width=512, max_height=512, store=True, readonly=True)
    active = fields.Boolean(default=True)
    color = fields.Integer("Color Index")

    @api.depends('classroom_id', 'classroom_id.capacity', 'session_type')
    def _compute_max_capacity(self):
        for rec in self:
            if rec.session_type == 'private':
                rec.max_capacity = 1
            elif rec.session_type == 'duo':
                rec.max_capacity = 2
            elif rec.classroom_id:
                rec.max_capacity = rec.classroom_id.capacity
            else:
                rec.max_capacity = 0
