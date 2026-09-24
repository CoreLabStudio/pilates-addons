{
    'name': 'Fitness Campaigns – CoreLab Studio',
    'version': '19.0.1.0.1',
    'category': 'Services',
    'summary': 'Send a survey Yoleyva built to a chosen group of students, '
               'by email and in the app, and read the answers',
    'author': 'CoreLab Studio',
    'license': 'LGPL-3',
    'depends': [
        # Odoo's own Surveys app does the questions, the answering and the
        # results. This module does not reimplement any of that - it decides
        # WHICH survey goes to WHICH students, and delivers it.
        'survey',
        'fitness_portal',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_campaign.xml',
        'views/fitness_campaign_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
