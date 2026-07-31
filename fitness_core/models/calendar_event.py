from odoo import models, fields, api


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    is_fitness_class = fields.Boolean("Is Fitness Class", default=False)
    classroom_id = fields.Many2one('fitness.classroom', "Classroom")
    class_type_id = fields.Many2one(
        'fitness.class.type',
        "Class Type",
    )
    session_type = fields.Selection([
        ('group', 'Group'),
        ('private', 'Private (1-on-1)'),
        ('duo', 'Duo (2 people)'),
    ], string="Session Type", default='group')
    capacity = fields.Integer(
        "Capacity",
        compute='_compute_capacity',
        store=True,
        readonly=False,
        help="Computed from class type / classroom but can be overridden for a specific session.",
    )
    booked_seats = fields.Integer(
        "Booked Seats",
        default=0,
        readonly=True,
        help="Maintained by the fitness_bookings module.",
    )
    available_seats = fields.Integer(
        "Available Seats",
        compute='_compute_available_seats',
    )

    @api.depends(
        'classroom_id', 'classroom_id.capacity',
        'class_type_id', 'class_type_id.max_capacity',
        'session_type',
    )
    def _compute_capacity(self):
        for event in self:
            if event.session_type == 'private':
                event.capacity = 1
            elif event.session_type == 'duo':
                event.capacity = 2
            elif event.class_type_id and event.class_type_id.max_capacity:
                event.capacity = event.class_type_id.max_capacity
            elif event.classroom_id:
                event.capacity = event.classroom_id.capacity
            else:
                event.capacity = 0

    @api.depends('capacity', 'booked_seats')
    def _compute_available_seats(self):
        for event in self:
            event.available_seats = max(0, event.capacity - event.booked_seats)

    @api.onchange('class_type_id')
    def _onchange_class_type_id(self):
        if self.class_type_id:
            if not self.classroom_id:
                self.classroom_id = self.class_type_id.classroom_id
            self.session_type = self.class_type_id.session_type
            if not self.name:
                self.name = self.class_type_id.name
