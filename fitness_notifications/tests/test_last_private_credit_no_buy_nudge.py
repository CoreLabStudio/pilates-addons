# -*- coding: utf-8 -*-
"""Her last credit on a private class is announced without a buy nudge.

When a studio-booked private class used her last credit she was told
"You have used your last credit. Visit Packages to purchase more." The
studio arranges private classes, so sending her off to buy one does not
fit. She is still told the credit is gone; the nudge is dropped. A group
class is unchanged.

Every language the studio writes in, clock pinned.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)

PRIVATE = {
    'en_US': 'You have used your last credit.',
    'es_ES': 'Has usado tu último crédito.',
    'ca_ES': 'Has usat el teu últim crèdit.',
}
GROUP = {
    'en_US': 'You have used your last credit. Visit Packages to purchase more.',
    'es_ES': 'Has usado tu último crédito. Visita Bonos para comprar más.',
    'ca_ES': 'Has usat el teu últim crèdit. Visita Bons per comprar-ne més.',
}


@tagged('post_install', '-at_install')
class TestLastPrivateCreditNoBuyNudge(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.types = {
            session: self.env['fitness.class.type'].create({
                'name': 'LP Reformer %s' % session,
                'classroom_type': 'reformer', 'duration': 50,
                'level': 'all', 'session_type': session})
            for session in ('group', 'private')}
        self._seq = 0

    def _student(self, lang):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'LP Student %d' % self._seq,
                'login': 'lp.%d@example.invalid' % self._seq,
                'email': 'lp.%d@example.invalid' % self._seq,
                'lang': lang, 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            }).partner_id

    def _last_credit(self, partner, session):
        self._seq += 1
        tmpl = self.env['product.template'].create({
            'name': 'LP %s single (%d)' % (session, self._seq),
            'list_price': 40.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 1,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': session,
        })
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer',
        })
        order.with_context(skip_fitness_notification=True).action_confirm()
        line = order.order_line[:1]
        start = PINNED + timedelta(days=1, hours=2 + self._seq)
        event = self.env['calendar.event'].sudo().create({
            'name': 'LP class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[session].id,
            'is_fitness_class': True, 'capacity': 1 if session == 'private'
            else 6, 'session_type': session,
        })
        # Booked by the studio, as every private class is.
        self.env['fitness.booking'].sudo().create({
            'student_id': partner.id, 'calendar_event_id': event.id,
            'package_order_line_id': line.id,
        })
        self.assertEqual(line.fitness_remaining_classes, 0,
                         'fixture: the last credit was not spent')
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', 'in', partner.user_ids.ids),
            ('notification_type', '=', 'credit_zero')])
        self.assertEqual(len(bell), 1, 'no "no credits" bell at all')
        return bell

    def test_private_class_says_last_credit_without_the_buy_nudge(self):
        for lang, expected in PRIVATE.items():
            with self.subTest(lang=lang):
                bell = self._last_credit(self._student(lang), 'private')
                self.assertEqual(bell.body, expected)

    def test_group_class_still_points_her_to_packages(self):
        for lang, expected in GROUP.items():
            with self.subTest(lang=lang):
                bell = self._last_credit(self._student(lang), 'group')
                self.assertEqual(bell.body, expected)
