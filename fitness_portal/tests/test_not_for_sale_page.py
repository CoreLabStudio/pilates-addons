# -*- coding: utf-8 -*-
"""The page of a product the studio does not sell.

Independent QA typed /my/packages/26 to /29 - the free classes the desk
gives - and got a product page: "1 class, 15 days, Price FREE, [Book]".
The button did nothing; the student was offered something that was not
there. Nothing in the shop links to these pages; a kept or shared link
is enough.

Now: a student who holds a live one sees what it covers, the classes
left, the valid-until date and "Book a class", which takes her to her
schedule for that discipline. Anybody else - never had it, used it up,
or holds it only on a cancelled order - gets a 404. Pages of products
the studio sells are not touched.

Over HTTP as the student, in es, ca and en, each installed explicitly;
the clock is pinned.
"""
from datetime import datetime

from odoo.tests import HttpCase, common, tagged

PINNED = datetime(2026, 10, 12, 9, 0, 0)
PASSWORD = 'not-for-sale-Pw-26'
SAID = {
    'en_US': ('Book a class', 'Covers', 'Barre · Group classes'),
    'es_ES': ('Reservar una clase', 'Cubre', 'Barre · Clases en grupo'),
    'ca_ES': ('Reserva una classe', 'Cobreix', 'Barre · Classes en grup'),
}


@tagged('post_install', '-at_install')
class TestNotForSalePage(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.free = self.env['product.template'].create({
            'name': 'NFS Free Barre class', 'list_price': 0.0,
            'type': 'service', 'sale_ok': False,
            'fitness_is_package': True, 'fitness_class_count': 1,
            'fitness_validity_days': 15, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})
        self.pack = self.env['product.template'].create({
            'name': 'NFS Barre pack 5', 'list_price': 60.0,
            'type': 'service', 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})
        self._seq = 0

    def _student(self, lang='en_US'):
        self._seq += 1
        login = 'nfs.%d@example.invalid' % self._seq
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'NFS Student %d' % self._seq, 'login': login,
                'email': login, 'password': PASSWORD, 'lang': lang,
                'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])],
            })
        self.authenticate(login, PASSWORD)
        return user

    def _give(self, user, product):
        order = self.env['sale.order'].sudo().create({
            'partner_id': user.partner_id.id,
            'order_line': [(0, 0, {
                'product_id': product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': product.list_price})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order.order_line[:1]

    def _page(self, product):
        # Followed: a Spanish or Catalan student is first sent to the
        # language-prefixed address. What is judged is where she lands.
        return self.url_open('/my/packages/%d' % product.id)

    def test_without_one_there_is_no_such_page(self):
        for lang in SAID:
            with self.subTest(lang=lang):
                self._student(lang)
                res = self._page(self.free)
                self.assertEqual(res.status_code, 404)
                self.assertNotIn('book-free', res.text)

    def test_the_studios_own_free_classes_too(self):
        """QA's exact case: the free classes this database ships."""
        self._student()
        for xmlid in ('fitness_packages.product_courtesy_barre',
                      'fitness_packages.product_courtesy_reformer'):
            product = self.env.ref(xmlid, raise_if_not_found=False)
            if not product:
                continue
            with self.subTest(xmlid=xmlid):
                self.assertFalse(product.sale_ok)
                self.assertEqual(self._page(product).status_code, 404)

    def test_holding_one_shows_it_and_where_to_use_it(self):
        for lang, (book, covers, what) in SAID.items():
            with self.subTest(lang=lang):
                user = self._student(lang)
                line = self._give(user, self.free)
                res = self._page(self.free)
                self.assertEqual(res.status_code, 200)
                html = res.text
                self.assertIn(book, html)
                self.assertIn(covers, html)
                self.assertIn(what, html)
                self.assertIn('href="/my/studio?discipline=barre"', html)
                self.assertIn(line.order_id.name, html)
                self.assertIn('mv-card-tag-active', html)
                self.assertNotIn('book-free', html,
                                 'still offers to book it for free')
                self.assertNotIn('/checkout', html)
                if lang != 'en_US':
                    self.assertNotIn('Book a class', html)

    def test_used_up_or_cancelled_is_not_held(self):
        user = self._student()
        line = self._give(user, self.free)
        line.fitness_remaining_classes = 0
        self.assertEqual(self._page(self.free).status_code, 404)
        line = self._give(user, self.free)
        line.order_id._action_cancel()
        self.assertEqual(self._page(self.free).status_code, 404)

    def test_the_shop_does_not_link_to_it(self):
        user = self._student()
        self._give(user, self.free)
        for tab in ('', '?tab=packages', '?tab=classes'):
            with self.subTest(tab=tab):
                html = self.url_open('/my/packages%s' % tab).text
                self.assertNotIn('/my/packages/%d"' % self.free.id, html)
                self.assertNotIn('/my/packages/%d?' % self.free.id, html)

    def test_a_page_for_sale_is_as_it_was(self):
        user = self._student()
        res = self._page(self.pack)
        self.assertEqual(res.status_code, 200)
        self.assertIn('/my/packages/%d/checkout' % self.pack.id, res.text)
        self.assertNotIn('mv-book-held', res.text)
        self._give(user, self.pack)
        res = self._page(self.pack)
        self.assertIn('mv-card-tag-active', res.text)
        self.assertNotIn('mv-book-held', res.text)
        self.assertNotIn('discipline=barre', res.text)
