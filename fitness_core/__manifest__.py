{
    'name': 'Fitness Core – Yoleyva Studio',
    'version': '19.0.1.9.2',
    'category': 'Services',
    'summary': 'Core models for Yoleyva Pilates & Barre Studio',
    'author': 'Yoleyva Studio',
    'license': 'LGPL-3',
    'depends': ['base', 'calendar', 'payment'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/fitness_classroom_views.xml',
        'views/fitness_class_category_views.xml',
        'views/fitness_class_type_views.xml',
        'views/fitness_session_type_views.xml',
        'views/calendar_event_views.xml',
        'views/fitness_news_views.xml',
        'views/fitness_dashboard_views.xml',
        'views/fitness_teacher_admin_views.xml',
        # menu_views.xml defines menu_fitness_classes_root, which the two
        # files below attach their menu items to. It has to load first or a
        # fresh install fails on a missing parent; an upgrade hides this
        # because the menu already exists in the database.
        'views/menu_views.xml',
        'views/fitness_class_schedule_views.xml',
        'views/fitness_closure_day_views.xml',
        'data/payment_method_bizum.xml',
        'data/demo_classrooms.xml',
        'data/demo_session_types.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'fitness_core/static/src/css/corelab_backend.css',
        ],
        'web.assets_frontend': [
            'fitness_core/static/src/css/corelab.css',
            'fitness_core/static/src/js/corelab.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
