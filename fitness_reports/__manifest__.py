{
    'name': 'Fitness Reports – CoreLab Studio',
    'version': '19.0.2.4.7',
    'category': 'Fitness',
    'summary': 'Manager-only analytics: bookings, revenue, clients, class occupancy (pivot/graph/list)',
    'author': 'Core Lab Studio, S.L.',
    'license': 'LGPL-3',
    'depends': [
        'fitness_core',
        'fitness_bookings',
        'fitness_subscriptions',
        'fitness_packages',
        # For MORNING_ENDS_AT. The trial form has split the studio's day at
        # one hour since it was built; the attendance report reads the same
        # number rather than declaring a second one that could drift.
        'fitness_trials',
        # The CoreLab dashboard is a spreadsheet.dashboard record. The
        # framework was already installed on production; naming it here
        # means a fresh install gets it too, instead of failing to load
        # data/spreadsheet_dashboards.xml.
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/booking_report.xml',
        'views/revenue_report.xml',
        'views/class_report.xml',
        'views/client_report.xml',
        'views/class_summary_report.xml',
        'views/retention_report.xml',
        'views/attendance_daypart_report.xml',
        'data/spreadsheet_dashboards.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
