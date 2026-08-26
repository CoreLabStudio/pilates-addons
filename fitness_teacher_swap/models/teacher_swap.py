from odoo import models, fields


class FitnessTeacherSwap(models.Model):
    _name = 'fitness.teacher.swap'
    _description = 'Teacher Swap Record'
    _order = 'create_date desc'
    _rec_name = 'class_name'

    class_name = fields.Char(string='Class', readonly=True)
    calendar_event_id = fields.Many2one(
        'calendar.event', string='Class Event',
        ondelete='set null', readonly=True,
    )
    class_start = fields.Datetime(string='Class Date / Time', readonly=True)
    class_type_id = fields.Many2one(
        'fitness.class.type', string='Class Type', readonly=True,
    )
    original_teacher_id = fields.Many2one(
        'res.users', string='From', required=True,
        ondelete='restrict', readonly=True,
    )
    new_teacher_id = fields.Many2one(
        'res.users', string='To', required=True,
        ondelete='restrict', readonly=True,
    )
    reason = fields.Text(string='Reason')
    initiated_by = fields.Selection([
        ('admin', 'Admin Backend'),
        ('teacher', 'Teacher Portal'),
    ], string='Source', required=True, default='admin', readonly=True)
