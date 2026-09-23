{
    'name': 'Fitness Trial Requests – CoreLab Studio',
    'version': '19.0.1.5.22',
    'category': 'Services',
    'summary': 'Public trial-class request form (Barre & Reformer), admin review list, and automated EN/ES/CA emails',
    'author': 'CoreLab Studio',
    'license': 'LGPL-3',
    # fitness_bookings was always a real dependency - this module creates
    # fitness.booking records when a trial is approved - and is now also
    # extended here, so the load order has to be guaranteed.
    'depends': ['fitness_core', 'fitness_bookings', 'fitness_notifications', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'views/trial_request_views.xml',
        'views/portal_trial_templates.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
