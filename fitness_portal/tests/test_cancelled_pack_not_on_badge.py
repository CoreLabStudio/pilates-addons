# -*- coding: utf-8 -*-
"""The credit badge on the profile hub never shows a cancelled order's pack.

The badge shows the pack with credits left that expires first. It read the
line's counter whatever the order's state, so a student whose Barre pack was
cancelled and replaced by a Reformer one was shown "3 / 3" from the cancelled
pack, because it happened to expire a day sooner.

Dates are relative to today with whole days of margin either side, so the
test does not depend on the hour it runs or on a clock change.
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

BADGE = re.compile(r'class="mv-credit-count"[^>]*>([^<]*)<')


@tagged('post_install', '-at_install')
class TestCancelledPackNotOnBadge(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # an unclaimed free trial is itself a credit; keep the badge about packs
        cls.env['ir.config_parameter'].sudo().set_param('fitness.trial_offer_end', '2000-01-01')
        cls.password = 'badge-test-pw-1'
        cls._seq = 0

    def _student(self):
        type(self)._seq += 1
        return self.env['res.users'].create({
            'name': 'Badge Student %d' % self._seq,
            'login': 'badge.%d@example.invalid' % self._seq,
            'password': self.password, 'lang': 'en_US', 'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('fitness_core.group_fitness_student').id,
            ])],
        })

    def _pack(self, partner, count, room, days, cancel=False):
        type(self)._seq += 1
        tmpl = self.env['product.template'].create({
            'name': 'Badge %s %d (%d)' % (room, count, self._seq),
            'list_price': 10.0 * count, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': count,
            'fitness_validity_days': 14, 'fitness_class_type': room,
            'fitness_session_type': 'group',
        })
        order = self.env['sale.order'].sudo().create({'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': room,
        })
        order.with_context(skip_fitness_notification=True).action_confirm()
        order.order_line[:1].fitness_validity_end_date = fields.Date.today() + timedelta(days=days)
        if cancel:
            order.action_cancel()
        return order

    def _badge(self, user):
        self.env.flush_all()
        self.authenticate(user.login, self.password)
        res = self.url_open('/my')
        self.assertEqual(res.status_code, 200)
        self.assertIn('mv-profile-hub', res.text, 'the profile hub did not render')
        m = BADGE.search(res.text)
        return m.group(1).strip() if m else None

    def test_badge_shows_the_live_pack_not_the_cancelled_one(self):
        user = self._student()
        self._pack(user.partner_id, 3, 'barre', 5, cancel=True)
        self._pack(user.partner_id, 2, 'reformer', 10)
        self.assertEqual(self._badge(user), '2 / 2',
                         'the badge showed the cancelled pack')

    def test_no_badge_when_the_only_pack_is_cancelled(self):
        user = self._student()
        self._pack(user.partner_id, 3, 'barre', 5, cancel=True)
        self.assertIsNone(self._badge(user),
                          'a badge for credits on a cancelled order')

    def test_live_pack_still_shown(self):
        user = self._student()
        self._pack(user.partner_id, 3, 'barre', 5)
        self.assertEqual(self._badge(user), '3 / 3')
