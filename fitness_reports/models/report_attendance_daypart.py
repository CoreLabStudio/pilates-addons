from odoo import models, fields, tools

from odoo.addons.fitness_trials.models.trial_request import (
    FitnessTrialRequest,
)

# ── The boundary between morning and evening ───────────────────────────────
#
# Borrowed, not declared. fitness.trial.request has carried this since the
# trial form was built - "Before this hour, in the studio's clock, a class
# counts as morning. One number, so the form, the stored preference and the
# studio's own list all cut the day in the same place" - and it is 14, not
# the 12 this report was first specified with.
#
# The difference is the 13:00 lunch class, the only slot that moves between
# them, and it is the whole substance of the question. Two numbers would
# have meant the trial form telling a student her 13:00 preference is a
# morning class while this report filed the same class as evening.
#
# That is the shape of fault this studio has paid for twice already: the
# free trial's deadline read in two places, one of which closed the offer;
# and the public timetable kept by hand beside the one in Odoo. So there is
# one number, it lives on the model that had it first, and moving it moves
# the report and the trial form together.
MORNING_ENDS_AT = FitnessTrialRequest.MORNING_ENDS_AT

# calendar_event.start is stored UTC and the studio reads a Madrid clock.
# Bucketing on the raw column would move classes across the boundary for half
# the year, because Spain is UTC+2 in summer and UTC+1 in winter. The
# conversion below goes through the tz database, so the October changeover
# is handled rather than approximated - the website carried the opposite
# mistake for months, every class listed an hour late, and the comment that
# asserted "Europe/Madrid" is what stopped anyone checking.
STUDIO_TZ = 'Europe/Madrid'


class FitnessReportAttendanceDaypart(models.Model):
    """One row per booking on a class that actually ran.

    The grain is the BOOKING, not the class - fitness.report.class is one
    row per event and answers "how full was this class". This answers "when
    do people come", so a class with six students is six rows.

    "Actually ran" is the same test the instructor report uses: not
    archived, not cancelled, and already finished. Archived classes matter:
    they are raw SQL, Odoo's active_test never reaches them, and on the
    production restore they were over a third of every row.
    """

    _name = 'fitness.report.attendance.daypart'
    _description = 'Attendance by Time of Day (SQL View)'
    _auto = False
    _rec_name = 'booking_id'
    _order = 'class_date desc'

    booking_id = fields.Many2one('fitness.booking', string='Booking', readonly=True)
    student_id = fields.Many2one('res.partner', string='Student', readonly=True)
    event_id = fields.Many2one('calendar.event', string='Class', readonly=True)
    class_date = fields.Date(string='Date', readonly=True)
    class_type_id = fields.Many2one(
        'fitness.class.type', string='Class Type', readonly=True)
    discipline = fields.Selection(
        [('barre', 'Barre'), ('reformer', 'Reformer'),
         ('any', 'Any'), ('', 'Unset')],
        string='Room', readonly=True,
        help="Barre or Reformer - the studio's two rooms, which is the "
             "'class type' split the report is usually read by.")

    local_hour = fields.Integer(
        string='Hour (Madrid)', readonly=True,
        help="The hour the class started on a Madrid clock, not UTC.")
    daypart = fields.Selection(
        [('morning', 'Morning'), ('evening', 'Evening')],
        string='Time of Day', readonly=True,
        help="Morning is anything starting before %d:00 Madrid time; "
             "evening is %d:00 onward. The same two words, and the same "
             "boundary, the trial form asks students to choose between."
             % (MORNING_ENDS_AT, MORNING_ENDS_AT))

    booking_state = fields.Selection(
        [('booked', 'Booked'), ('attended', 'Attended'),
         ('no_show', 'No-show')],
        string='Booking Status', readonly=True)

    paid_membership = fields.Boolean(
        string='Paid for a Membership', readonly=True,
        help="This student has bought a membership at some point - a "
             "recurring plan, not a pack of classes.")
    paid_pack = fields.Boolean(
        string='Paid for a Pack', readonly=True,
        help="This student has bought a pack of classes at some point. "
             "Independent of the membership flag: somebody who has bought "
             "both is true for both, so the two do not add up to the "
             "paying total.")
    is_paying = fields.Boolean(
        string='Paying Student', readonly=True,
        help="This student has at least one confirmed order carrying a pack "
             "or a membership line above zero euros. The amount is what "
             "makes it a purchase: a free trial IS a package on this "
             "system, so asking only whether she owns one would count every "
             "trial visitor as a paying client. Gifts are zero too, and are "
             "excluded by the same test.")

    # Two measures rather than one, so a pivot can show both without being
    # filtered twice. A seat that was held and not turned up to is still
    # demand for that hour, which is what the timetable question is about;
    # whether she came is a different question and gets its own column.
    attendance_count = fields.Integer(
        string='Seats Held', readonly=True, aggregator='sum',
        help="Every booking that was not cancelled on a class that ran, "
             "including no-shows: the seat was taken and nobody else could "
             "have it.")
    attended_count = fields.Integer(
        string='Attended', readonly=True, aggregator='sum',
        help="Only the bookings marked attended.")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW {table} AS
            SELECT
                fb.id                                           AS id,
                fb.id                                           AS booking_id,
                fb.student_id,
                ce.id                                           AS event_id,
                (ce.start AT TIME ZONE 'UTC'
                          AT TIME ZONE %(tz)s)::date            AS class_date,
                EXTRACT(HOUR FROM (ce.start AT TIME ZONE 'UTC'
                          AT TIME ZONE %(tz)s))::int            AS local_hour,
                CASE
                    WHEN EXTRACT(HOUR FROM (ce.start AT TIME ZONE 'UTC'
                              AT TIME ZONE %(tz)s)) < %(cutoff)s
                    THEN 'morning' ELSE 'evening'
                END                                             AS daypart,
                ce.class_type_id,
                COALESCE(ct.classroom_type, '')                 AS discipline,
                fb.state                                        AS booking_state,
                1                                               AS attendance_count,
                CASE WHEN fb.state = 'attended' THEN 1 ELSE 0 END
                                                                AS attended_count,
                -- Has she ever paid for a membership?
                --
                -- price_subtotal > 0 is the whole point, in all three of
                -- these. A free trial carries fitness_is_package, so "owns
                -- a package" is true for somebody who has never paid the
                -- studio anything; a gifted class is zero for the same
                -- reason. What separates a client from a visitor is money.
                EXISTS (
                    SELECT 1
                    FROM sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id
                    JOIN product_product pp  ON pp.id = sol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE so.partner_id = fb.student_id
                      AND so.state IN ('sale', 'done')
                      AND pt.fitness_is_subscription_plan = TRUE
                      AND sol.price_subtotal > 0
                )                                               AS paid_membership,
                -- ... and for a pack? Asked separately, because somebody
                -- who has bought both belongs in both answers.
                EXISTS (
                    SELECT 1
                    FROM sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id
                    JOIN product_product pp  ON pp.id = sol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE so.partner_id = fb.student_id
                      AND so.state IN ('sale', 'done')
                      AND pt.fitness_is_package = TRUE
                      AND sol.price_subtotal > 0
                )                                               AS paid_pack,
                EXISTS (
                    SELECT 1
                    FROM sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id
                    JOIN product_product pp  ON pp.id = sol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE so.partner_id = fb.student_id
                      AND so.state IN ('sale', 'done')
                      AND (pt.fitness_is_package = TRUE
                           OR pt.fitness_is_subscription_plan = TRUE)
                      AND sol.price_subtotal > 0
                )                                               AS is_paying
            FROM fitness_booking fb
            JOIN calendar_event ce      ON ce.id = fb.calendar_event_id
            LEFT JOIN fitness_class_type ct ON ct.id = ce.class_type_id
            WHERE ce.is_fitness_class = TRUE
              -- Same three tests as fitness.report.class's did_run: a class
              -- the studio took off the timetable was taught by nobody, a
              -- cancelled one did not happen, and one that has not finished
              -- cannot be attendance yet.
              AND ce.active = TRUE
              AND ce.class_state <> 'cancelled'
              AND ce.stop < now()
              -- A cancelled booking is a seat given back. She was not there.
              AND fb.state IN ('booked', 'attended', 'no_show')
        """.format(table=self._table), {
            'tz': STUDIO_TZ,
            'cutoff': MORNING_ENDS_AT,
        })
