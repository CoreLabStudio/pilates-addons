from odoo import models, fields, tools


class FitnessReportRetention(models.Model):
    _name = 'fitness.report.retention'
    _description = 'Monthly Retention & ARPU Report (SQL View)'
    _auto = False
    _rec_name = 'period_month'
    _order = 'period_month desc'

    period_month = fields.Date(string='Month', readonly=True)
    active_clients = fields.Integer(string='Active Clients', readonly=True,
        help='Unique clients with at least one booked/attended/no-show class in the month.')
    new_clients = fields.Integer(string='New Clients', readonly=True,
        help='Clients whose first confirmed sale order was in this month.')
    returning_clients = fields.Integer(string='Returning Clients', readonly=True,
        help='Active clients who were also active in the previous month.')
    retention_rate_pct = fields.Float(
        string='Retention %', readonly=True, digits=(5, 1),
        help='Returning clients / active clients × 100.',
    )
    period_revenue = fields.Float(
        string='Revenue excl. VAT', readonly=True, digits=(16, 2),
        help='Sum of amount_untaxed on confirmed sale orders in this month.',
    )
    arpu = fields.Float(
        string='ARPU', readonly=True, digits=(16, 2),
        help='Average Revenue Per User: period_revenue / active_clients.',
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS
            WITH monthly_active AS (
                SELECT
                    fb.student_id,
                    DATE_TRUNC('month', fb.class_start)::date AS activity_month
                FROM fitness_booking fb
                WHERE fb.state IN ('booked', 'attended', 'no_show')
                  AND fb.class_start IS NOT NULL
                GROUP BY fb.student_id, DATE_TRUNC('month', fb.class_start)
            ),
            client_first_month AS (
                SELECT
                    partner_id AS student_id,
                    DATE_TRUNC('month', MIN(date_order))::date AS first_order_month
                FROM sale_order
                WHERE state = 'sale'
                GROUP BY partner_id
            ),
            monthly_revenue AS (
                SELECT
                    DATE_TRUNC('month', date_order)::date AS order_month,
                    SUM(amount_untaxed)                   AS period_revenue
                FROM sale_order
                WHERE state = 'sale'
                GROUP BY DATE_TRUNC('month', date_order)
            )
            SELECT
                ROW_NUMBER() OVER (ORDER BY curr.activity_month)::integer    AS id,
                curr.activity_month                                           AS period_month,
                COUNT(DISTINCT curr.student_id)::integer                     AS active_clients,
                COUNT(DISTINCT CASE
                    WHEN cfm.first_order_month = curr.activity_month
                    THEN curr.student_id END)::integer                       AS new_clients,
                COUNT(DISTINCT CASE
                    WHEN prev.student_id IS NOT NULL
                    THEN curr.student_id END)::integer                       AS returning_clients,
                COALESCE(ROUND(
                    100.0
                    * COUNT(DISTINCT CASE WHEN prev.student_id IS NOT NULL
                                         THEN curr.student_id END)::numeric
                    / NULLIF(COUNT(DISTINCT curr.student_id), 0)
                , 1), 0.0)                                                   AS retention_rate_pct,
                COALESCE(MAX(rev.period_revenue), 0.0)                       AS period_revenue,
                COALESCE(ROUND(
                    MAX(rev.period_revenue)
                    / NULLIF(COUNT(DISTINCT curr.student_id), 0)
                , 2), 0.0)                                                   AS arpu
            FROM monthly_active curr
            LEFT JOIN monthly_active prev
                ON prev.student_id = curr.student_id
                AND prev.activity_month = (curr.activity_month - INTERVAL '1 month')::date
            LEFT JOIN client_first_month cfm
                ON cfm.student_id = curr.student_id
            LEFT JOIN monthly_revenue rev
                ON rev.order_month = curr.activity_month
            GROUP BY curr.activity_month
        """ % self._table)
