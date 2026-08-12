from odoo import models, fields, tools


class FitnessReportClient(models.Model):
    _name = 'fitness.report.client'
    _description = 'Client Report (SQL View)'
    _auto = False
    _rec_name = 'partner_id'
    _order = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Client', readonly=True)
    is_active_client = fields.Boolean(string='Active Client', readonly=True)
    is_churned = fields.Boolean(
        string='Churned',
        readonly=True,
        help='True when the client has no active credits/subscription AND no class activity in the last 60 days.',
    )
    first_order_date = fields.Date(string='First Order', readonly=True)
    total_revenue = fields.Float(
        string='Revenue ex-IVA',
        readonly=True,
        digits=(16, 2),
    )
    attended_classes = fields.Integer(string='Attended Classes', readonly=True)
    avg_classes_per_month = fields.Float(
        string='Avg Classes / Month',
        readonly=True,
        digits=(5, 1),
        help='Attended classes divided by the number of months since the first order (minimum 1).',
    )
    last_attended_date = fields.Datetime(string='Last Attended', readonly=True)
    days_inactive = fields.Integer(
        string='Days Inactive',
        readonly=True,
        help='Days since last booked/attended/no-show class. 9999 = no booking history.',
    )
    active_subscriptions = fields.Integer(string='Active Subscriptions', readonly=True)
    active_package_credits = fields.Integer(string='Pack Credits', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS
            SELECT
                p.id,
                p.id                                         AS partner_id,
                orders.first_order_date,
                COALESCE(orders.total_revenue, 0)            AS total_revenue,
                COALESCE(att.attended_classes, 0)            AS attended_classes,
                ROUND(
                    COALESCE(att.attended_classes, 0)::numeric
                    / GREATEST(
                        DATE_PART('year',  AGE(CURRENT_DATE, orders.first_order_date)) * 12
                        + DATE_PART('month', AGE(CURRENT_DATE, orders.first_order_date))
                        + 1,
                        1
                    )::numeric,
                    1
                )                                            AS avg_classes_per_month,
                att.last_attended_date,
                CASE
                    WHEN activity.last_activity_date IS NOT NULL
                    THEN (CURRENT_DATE - activity.last_activity_date::date)
                    ELSE 9999
                END::integer                                 AS days_inactive,
                COALESCE(sub.active_subscriptions, 0)        AS active_subscriptions,
                COALESCE(pkg.active_package_credits, 0)      AS active_package_credits,
                (COALESCE(sub.active_subscriptions, 0) > 0
                 OR COALESCE(pkg.active_package_credits, 0) > 0
                )                                            AS is_active_client,
                (
                    (activity.last_activity_date IS NULL
                     OR (CURRENT_DATE - activity.last_activity_date::date) > 60)
                    AND COALESCE(sub.active_subscriptions, 0) = 0
                    AND COALESCE(pkg.active_package_credits, 0) = 0
                )                                            AS is_churned
            FROM res_partner p
            JOIN (
                -- Fitness clients: has at least one confirmed package order OR any booking
                SELECT partner_id AS pid
                FROM sale_order
                WHERE state = 'sale' AND fitness_is_package = TRUE
                UNION
                SELECT student_id AS pid
                FROM fitness_booking
            ) act ON act.pid = p.id
            LEFT JOIN (
                SELECT partner_id,
                       MIN(date_order)::date  AS first_order_date,
                       SUM(amount_untaxed)    AS total_revenue
                FROM sale_order
                WHERE state = 'sale'
                GROUP BY partner_id
            ) orders ON orders.partner_id = p.id
            LEFT JOIN (
                SELECT student_id,
                       COUNT(*)          AS attended_classes,
                       MAX(class_start)  AS last_attended_date
                FROM fitness_booking
                WHERE state = 'attended'
                GROUP BY student_id
            ) att ON att.student_id = p.id
            LEFT JOIN (
                SELECT student_id,
                       MAX(class_start) AS last_activity_date
                FROM fitness_booking
                WHERE state IN ('booked', 'attended', 'no_show')
                GROUP BY student_id
            ) activity ON activity.student_id = p.id
            LEFT JOIN (
                SELECT partner_id, COUNT(*) AS active_subscriptions
                FROM sale_order
                WHERE is_subscription = TRUE AND subscription_state = '3_progress'
                GROUP BY partner_id
            ) sub ON sub.partner_id = p.id
            LEFT JOIN (
                SELECT so2.partner_id,
                       SUM(sol.fitness_remaining_classes) AS active_package_credits
                FROM sale_order_line sol
                JOIN sale_order so2 ON so2.id = sol.order_id
                WHERE sol.fitness_remaining_classes > 0
                  AND (sol.fitness_validity_end_date IS NULL
                       OR sol.fitness_validity_end_date >= CURRENT_DATE)
                  AND so2.state = 'sale'
                  AND so2.fitness_is_package = TRUE
                GROUP BY so2.partner_id
            ) pkg ON pkg.partner_id = p.id
        """ % self._table)
