{
    'name': 'Fitness Trial Requests – CoreLab Studio',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': 'Public trial-class request form, admin review list, and automated EN/ES/CA emails',
    'author': 'CoreLab Studio',
    'license': 'LGPL-3',
    'depends': ['fitness_core', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'views/trial_request_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
