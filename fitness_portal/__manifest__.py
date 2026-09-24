{
    'name': 'CoreLab Student Portal',
    'version': '19.0.1.25.0',
    'category': 'Services',
    'summary': 'Student-facing CoreLab portal: home, studio, packages, checkout',
    'author': 'Core Lab Studio, S.L.',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'portal',
        'sale',
        # Named directly by the desk wizard when it invoices a cash sale.
        # Present transitively through sale -> account_payment -> account,
        # but a module that references account.journal should say so.
        'account',
        'payment',
        'auth_signup',
        'fitness_core',
        'fitness_bookings',
        'fitness_packages',
        'fitness_subscriptions',
        'fitness_notifications',
        # The shop's trial cards link into this module's request form and
        # read fitness.trial.request to know whether one is already open.
        'fitness_trials',
        # Odoo's own Surveys app, for studio feedback and announcements.
        #
        # Declared here rather than kept out of the dependency chain, which
        # was the original plan. Installing it from a shell against the live
        # database fails: gamification, which survey depends on, adds a karma
        # column to res_users, and that ALTER TABLE needs an exclusive lock
        # every logged-in session is holding. It timed out on production.
        #
        # As a dependency it installs during the deploy instead, when
        # odoo.sh restarts the instance and nobody is holding the table.
        # The cost is that survey can no longer be uninstalled without
        # touching this manifest, which is worth less than it installing.
        'survey',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/ir.rule.xml',
        'views/studio_message_views.xml',
        'views/student_profile_simple.xml',
        'views/vip_filters.xml',
        'views/teacher_profile_simple.xml',
        'views/student_profile_views.xml',
        'views/desk_sale_wizard_views.xml',
        'views/make_student_views.xml',
        'views/cash_request_views.xml',
        'views/sale_order_renewal_views.xml',
        'views/package_line_views.xml',
        'views/portal_templates.xml',
        'views/portal_shell_override.xml',
        'views/login_override.xml',
        'views/payment_status_override.xml',
        'views/signup_templates.xml',
        'views/signup_consent.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
