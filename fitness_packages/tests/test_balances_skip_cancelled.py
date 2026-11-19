# -*- coding: utf-8 -*-
"""Package Balances lists no line of a cancelled order.

A cancelled order's line keeps its counter ("3 remaining") although nothing
can spend it. The staff list showed it beside the real balances, so the
studio read credits that nobody holds. A confirmed order's line, spent or
not, expired or not, is listed exactly as before.
"""
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestBalancesSkipCancelled(TransactionCase):

    def _line(self, partner, cancel):
        tmpl = self.env['product.template'].create({
            'name': 'Bal pack %s' % cancel, 'list_price': 30.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 3,
            'fitness_validity_days': 14, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group',
        })
        order = self.env['sale.order'].sudo().create({'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1})
        order.with_context(skip_fitness_notification=True).action_confirm()
        if cancel:
            order.action_cancel()
        return order.order_line[:1]

    def test_cancelled_line_left_out_confirmed_line_kept(self):
        partner = self.env['res.partner'].create({'name': 'Bal student'})
        live = self._line(partner, cancel=False)
        gone = self._line(partner, cancel=True)
        self.assertEqual(gone.fitness_remaining_classes, 3, 'fixture: the cancelled line lost its counter')
        action = self.env.ref('fitness_packages.action_fitness_package_balances')
        shown = self.env['sale.order.line'].search(
            safe_eval(action.domain) + [('order_partner_id', '=', partner.id)])
        self.assertIn(live, shown, 'a confirmed pack fell out of Package Balances')
        self.assertNotIn(gone, shown, 'Package Balances listed a cancelled order\'s credits')
