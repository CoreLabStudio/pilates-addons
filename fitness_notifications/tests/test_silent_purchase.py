# -*- coding: utf-8 -*-
"""Confirming an order honours skip_fitness_notification, on every channel.

Four notification paths honoured the flag; sale_order.action_confirm did
not. Confirming an order with skip_fitness_notification=True still rang
the bell and pushed to her phone, which is why nothing that creates a
credit on a student's behalf could be done quietly.

Counted here on all three channels - bell, mail, push - with the real
push sender (web_push.send) replaced by a recorder, a VAPID keypair set
and a registered device, so a push that would have left is counted
rather than skipped for some other reason. The negative is the same
purchase without the flag: one bell, one push.

Clock pinned, language explicit.
"""
from datetime import datetime

from odoo.tests import TransactionCase, common, tagged

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)

PINNED = datetime(2026, 11, 4, 8, 0, 0)
NEUTRALIZED = 'database.is_neutralized'


@tagged('post_install', '-at_install')
class TestSilentPurchase(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_PUBLIC, 'pub-for-test')
        Param.set_param(PARAM_PRIVATE, 'priv-for-test')
        Param.set_param(NEUTRALIZED, 'False')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        self.pushed = []
        real_send = web_push.send

        def recorder(endpoint, *args, **kwargs):
            self.pushed.append(endpoint)
            return 201, ''

        web_push.send = recorder

        def restore():
            web_push.send = real_send
        self.addCleanup(restore)

        self.pack = self.env['product.template'].create({
            'name': 'SL Pack 5', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
        })
        self.plan = self.env['product.template'].create({
            'name': 'SL Reformer 1 a week', 'list_price': 60.0,
            'type': 'service', 'sale_ok': True,
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'reformer', 'fitness_session_type': 'group',
            'weekly_class_allowance': 1,
        })
        self._seq = 0

    def _student(self):
        self._seq += 1
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'SL Student %d' % self._seq,
                'login': 'sl.%d@example.invalid' % self._seq,
                'email': 'sl.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            })
        self.env['fitness.push.subscription']._register_device(
            user.id, 'https://push.example.invalid/sl%d' % self._seq,
            'pub', 'auth')
        return user

    def _order(self, user, product):
        vals = {'partner_id': user.partner_id.id}
        if product == self.plan:
            vals['plan_id'] = self.env.ref(
                'sale_subscription.subscription_plan_month').id
        order = self.env['sale.order'].sudo().create(vals)
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': product.list_price,
            'fitness_class_type': 'reformer',
        })
        return order

    def _channels(self, user):
        return (
            self.env['fitness.notification'].sudo().search_count(
                [('user_id', '=', user.id)]),
            self.env['mail.mail'].sudo().search_count(
                [('recipient_ids', 'in', user.partner_id.ids)]),
            len(self.pushed),
        )

    def _confirm(self, product, silent):
        user = self._student()
        order = self._order(user, product)
        before = self._channels(user)
        ctx = {'skip_fitness_notification': True} if silent else {}
        order.with_context(**ctx).action_confirm()
        self.assertEqual(order.state, 'sale')
        after = self._channels(user)
        return tuple(a - b for a, b in zip(after, before)), order

    def test_a_silent_pack_purchase_is_silent_everywhere(self):
        (bells, mails, pushes), order = self._confirm(self.pack, silent=True)
        self.assertEqual((bells, mails, pushes), (0, 0, 0),
                         'bells, mails, pushes under the flag')
        self.assertEqual(order.order_line.fitness_remaining_classes, 5,
                         'silence must not cost her the credit')

    def test_a_silent_membership_purchase_is_silent_everywhere(self):
        (bells, mails, pushes), _order = self._confirm(self.plan, silent=True)
        self.assertEqual((bells, mails, pushes), (0, 0, 0))

    def test_without_the_flag_she_hears_once(self):
        for product in (self.pack, self.plan):
            with self.subTest(product=product.name):
                (bells, mails, pushes), _order = self._confirm(
                    product, silent=False)
                self.assertEqual(bells, 1)
                self.assertEqual(pushes, 1)
                self.pushed.clear()
