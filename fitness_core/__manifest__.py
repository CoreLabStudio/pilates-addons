{
    'name': 'Fitness Core – Yoleyva Studio',
    'version': '19.0.2.6.13',
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
        # After menu_views.xml, not before it: this file hangs a menuitem off
        # menu_fitness_teachers_root, which menu_views.xml creates. Loading it
        # first works on an upgrade, where the menu is already in the database,
        # and fails on a fresh install with "External ID not found" - which is
        # exactly how odoo.sh builds a branch.
        'views/fitness_teacher_hours_views.xml',
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
    'post_init_hook': 'post_init_hook',
    'application': True,
    'auto_install': False,
}
