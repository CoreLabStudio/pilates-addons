{
    'name': 'Fitness Packages – CoreLab Studio',
    'version': '19.0.1.1.7',
    'category': 'Services',
    'summary': 'Class-pack products, credit balance tracking and validity management',
    'author': 'Core Lab Studio, S.L.',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'product',
        'fitness_core',
        'fitness_bookings',
    ],
    'data': [
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/menu.xml',
        'data/products.xml',
        'data/combo_products.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
