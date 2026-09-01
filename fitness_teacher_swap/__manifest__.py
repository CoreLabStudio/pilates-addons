{
    'name': 'Fitness Teacher Swap – Yoleyva Studio',
    'version': '19.0.1.2.6',
    'category': 'Services',
    'summary': 'Portal page letting a teacher reassign one of their own upcoming classes to another teacher',
    'author': 'Yoleyva Studio',
    'license': 'LGPL-3',
    'depends': [
        'portal',
        'fitness_core',
        'fitness_bookings',
        'fitness_notifications',
        'fitness_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_swap.xml',
        'views/portal_templates.xml',
        'views/swap_admin_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
