from odoo import models, fields, tools


class FitnessReportClass(models.Model):
    _name = 'fitness.report.class'
    _description = 'Class Summary Report (SQL View)'
    _auto = False
    _rec_name = 'event_id'
    _order = 'class_date desc'

    event_id = fields.Many2one('calendar.event', string='Class', readonly=True)
    class_date = fields.Date(string='Date', readonly=True)
    class_type_id = fields.Many2one('fitness.class.type', string='Class Type', readonly=True)
    teacher_user_id = fields.Many2one('res.users', string='Instructor', readonly=True)
    capacity = fields.Integer(string='Capacity', readonly=True)
    booked_count = fields.Integer(string='Booked Seats', readonly=True)
    attended_count = fields.Integer(string='Attended', readonly=True)
    no_show_count = fields.Integer(string='No-show', readonly=True)
    cancelled_count = fields.Integer(string='Cancelled', readonly=True)
    occupancy_pct = fields.Float(
        string='Occupancy %',
        readonly=True,
        digits=(5, 1),
        aggregator='avg',
    )
    attributed_revenue = fields.Float(
        string='Attributed Revenue (approx., may overlap)',
        readonly=True,
        digits=(16, 2),
        help=(
            'Sum of ex-IVA revenue (confirmed orders) from clients who attended '
            'this class. A client attending classes with multiple teachers is '
            'counted for each teacher — directional only, not a precise per-teacher P&L.'
        ),
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS
            SELECT
                ce.id,
                ce.id                                                       AS event_id,
                ce.start::date                                              AS class_date,
                ce.class_type_id,
                ce.user_id                                                  AS teacher_user_id,
                ce.capacity,
                COUNT(fb.id) FILTER (WHERE fb.state IN ('booked','attended'))  AS booked_count,
                COUNT(fb.id) FILTER (WHERE fb.state = 'attended')              AS attended_count,
                COUNT(fb.id) FILTER (WHERE fb.state = 'no_show')               AS no_show_count,
                COUNT(fb.id) FILTER (WHERE fb.state = 'cancelled')             AS cancelled_count,
                ROUND(
                    100.0 * COUNT(fb.id) FILTER (WHERE fb.state IN ('booked','attended'))
                    / NULLIF(ce.capacity, 0)
                , 1)                                                        AS occupancy_pct,
                COALESCE(ar.attributed_revenue, 0)                         AS attributed_revenue
            FROM calendar_event ce
            LEFT JOIN fitness_booking fb ON fb.calendar_event_id = ce.id
            LEFT JOIN (
                -- Revenue from attending clients per event (directional, may overlap across teachers)
                SELECT fb2.calendar_event_id,
                       SUM(so.amount_untaxed) AS attributed_revenue
                FROM fitness_booking fb2
                JOIN sale_order so ON so.partner_id = fb2.student_id AND so.state = 'sale'
                WHERE fb2.state = 'attended'
                GROUP BY fb2.calendar_event_id
            ) ar ON ar.calendar_event_id = ce.id
            WHERE ce.is_fitness_class = TRUE
            GROUP BY ce.id, ce.start, ce.class_type_id, ce.user_id,
                     ce.capacity, ar.attributed_revenue
        """ % self._table)
