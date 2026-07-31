from odoo import models, fields


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    booking_ids = fields.One2many(
        'fitness.booking', 'calendar_event_id',
        string="Bookings",
    )
