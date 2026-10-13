# -*- coding: utf-8 -*-
"""A pack on a cancelled order is not hers on any student page.

After the hotfix the engine refused to spend a cancelled order's credit,
but three pages still read it as hers. Reproduced over HTTP as a student
whose only credit was a 5-class pack on a cancelled order:

  shop          the card tagged "Activo", its Buy button disabled
  product page  "Estado Activo - Restante 5 / 5 clases"
  schedule      "Reservar" offered; pressing it booked nothing and said
                "No active subscription or package covers this class
                type" in English to a Spanish student

All three now ask the shared spendable rule, and the refusal is in her
own language. Each case in es, ca and en, as the student over HTTP; the
negative is the same pack on a live order, which must still show.

Clock pinned.
"""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
import re

from odoo.tests import HttpCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
PASSWORD = 'cancelled-pages-Pw-26'
LANGS = ('es_ES', 'ca_ES', 'en_US')
REFUSAL = {
    'en_US': 'No active subscription or package covers this class type',
    'es_ES': 'Ninguna suscripción ni bono activo cubre este tipo de clase',
    'ca_ES': 'Cap subscripció ni bo actiu cobreix aquest tipus de classe',
}


@tagged('post_install', '-at_install')
class TestCancelledCreditPages(HttpCase):

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
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        # The free-trial offer closed before the pinned day, so a student
        # with nothing to pay with is refused rather than sent to the
        # trial form - which is the page's correct answer while it is open.
        ICP.set_param('fitness.trial_offer_end', '2026-10-16')
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'CP Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        self.pack = self.env['product.template'].create({
            'name': 'CP Reformer Pack 5', 'list_price': 60.0,
            'type': 'service', 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        start = PINNED + timedelta(days=2, hours=2)
        self.event = self.env['calendar.event'].sudo().create({
            'name': 'CP Reformer class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
            'capacity': 8, 'session_type': 'group'})
        self._seq = 0

    def _student(self, lang, cancelled):
        self._seq += 1
        login = 'cp.%d@example.invalid' % self._seq
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CP Student %d' % self._seq, 'login': login,
                'email': login, 'password': PASSWORD, 'lang': lang,
                'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])],
            })
        order = self.env['sale.order'].sudo().create(
            {'partner_id': user.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.with_context(skip_fitness_notification=True).action_confirm()
        if cancelled:
            order._action_cancel()
        self.assertEqual(order.order_line.fitness_remaining_classes, 5)
        self.authenticate(login, PASSWORD)
        return user

    def _card(self, html):
        i = html.find('aria-label="CP Reformer Pack 5"')
        self.assertGreater(i, -1, 'the pack is not in the shop at all')
        end = html.find('mv-pkg-card-link', i + 10)
        return html[i: end if end > 0 else i + 4000]

    def _book(self):
        page = self.url_open('/my/studio').text
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page) or \
            re.search(r'csrf_token["\']?\s*[:=]\s*["\']([^"\']+)', page)
        return self.url_open(
            '/my/classes/%d/book' % self.event.id,
            data={'csrf_token': token.group(1)}, allow_redirects=False)

    def _bookings(self, user):
        return self.env['fitness.booking'].sudo().search_count([
            ('student_id', '=', user.partner_id.id)])

    def test_a_cancelled_pack_is_not_hers_anywhere(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang, cancelled=True)
                shop = self.url_open('/my/packages?tab=packages').text
                self.assertNotIn('mv-card-tag-active', self._card(shop),
                                 'shop: tagged Active')
                detail = self.url_open(
                    '/my/packages/%d' % self.pack.id).text
                self.assertNotIn('mv-card-tag-active', detail,
                                 'product page: shown as hers')
                studio = self.url_open('/my/studio').text
                self.assertNotIn('/my/classes/%d/book' % self.event.id,
                                 studio, 'schedule: Reservar offered')
                res = self._book()
                error = parse_qs(urlparse(
                    res.headers.get('Location', '')).query).get(
                        'error', [''])[0]
                self.assertIn(REFUSAL[lang], error,
                              'refusal not in her language: %r (went to %s)'
                              % (error, res.headers.get('Location')))
                self.assertEqual(self._bookings(user), 0)

    def test_a_live_pack_still_shows_and_books(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                user = self._student(lang, cancelled=False)
                shop = self.url_open('/my/packages?tab=packages').text
                self.assertIn('mv-card-tag-active', self._card(shop))
                detail = self.url_open(
                    '/my/packages/%d' % self.pack.id).text
                self.assertIn('mv-card-tag-active', detail)
                self.assertIn('/my/classes/%d/book' % self.event.id,
                              self.url_open('/my/studio').text)
                self._book()
                self.assertEqual(self._bookings(user), 1)
