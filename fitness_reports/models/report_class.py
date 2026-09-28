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
    duration_hours = fields.Float(
        string='Hours',
        readonly=True,
        digits=(16, 2),
        help=(
            'Scheduled length of the class, from its start and stop, not the '
            'class type nominal duration - the two can differ once a '
            'class has been edited, and what the instructor stood in the '
            'room for is the span that was actually booked.'
        ),
    )
    class_state = fields.Selection(
        [('scheduled', 'Scheduled'), ('cancelled', 'Cancelled')],
        string='Class Status', readonly=True,
    )
    did_run = fields.Boolean(
        string='Ran',
        readonly=True,
        help=(
            'The class was not cancelled and has already finished. A class '
            'that ran with nobody in it still counts - the instructor was '
            'there.'
        ),
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
                EXTRACT(EPOCH FROM (ce.stop - ce.start)) / 3600.0           AS duration_hours,
                ce.class_state,
                (ce.class_state <> 'cancelled' AND ce.stop < now())         AS did_run,
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
              -- Archived classes were being counted. This is raw SQL, so
              -- Odoo's active_test never reached it: on the production
              -- restore the view returned 959 rows of which 404 were
              -- archived, well over a third of every figure the studio
              -- read. An archived
              -- class is one the studio took off the timetable, and nobody
              -- taught it.
              AND ce.active = TRUE
            GROUP BY ce.id, ce.start, ce.stop, ce.class_type_id, ce.user_id,
                     ce.capacity, ce.class_state, ce.active,
                     ar.attributed_revenue
        """ % self._table)
