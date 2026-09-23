# -*- coding: utf-8 -*-
"""One purchase, one notification.

A combined pack is one product sold as two order lines - a Barre pool and a
Reformer pool, one price. The confirmation looped over the lines, and both
lines carry the same product name, so the student was told the identical
thing twice for a single purchase: "2 Barre + 2 Reformer al mes confirmada",
then again.

Found by buying one at the desk and reading what arrived, not by a test.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseNotificationIsOnePerOrder(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env["res.users"].create({
            "name": "Notif Student",
            "login": "notif.purchase@example.invalid",
            "email": "notif.purchase@example.invalid",
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])],
        })
        cls.partner = cls.student.partner_id

    def _pack(self, secondary=None):
        return self.env["product.template"].create({
            "name": "Notif pack",
            "list_price": 95.0,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_count": 2,
            "fitness_validity_days": 30,
            "fitness_class_type": "barre",
            "fitness_secondary_class_type": secondary,
            "fitness_secondary_class_count": 2 if secondary else 0,
            "fitness_session_type": "group",
        })

    def _confirm(self, pack):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, v)
                           for v in pack.fitness_sale_line_vals(pack.list_price)],
        })
        order.action_confirm()
        return order

    def _notifs(self):
        return self.env["fitness.notification"].sudo().search([
            ("user_id", "=", self.student.id),
            ("notification_type", "=", "purchase_completed"),
        ])

    def test_a_combined_pack_tells_her_once(self):
        """Two pools, one purchase, one message."""
        pack = self._pack(secondary="reformer")
        order = self._confirm(pack)

        self.assertEqual(
            len(order.order_line.filtered(
                lambda l: l.product_id.fitness_is_package)), 2,
            "fixture is wrong: this pack is not two lines, so the duplicate "
            "it guards against could not happen")
        self.assertEqual(
            len(self._notifs()), 1,
            "a combined pack told the student the same thing twice")

    def test_a_single_pack_still_tells_her(self):
        """The fix must not silence the ordinary case."""
        self._confirm(self._pack())
        self.assertEqual(len(self._notifs()), 1)

    def test_the_credits_named_are_the_credits_she_has(self):
        """Summed across both pools, not one pool reported twice."""
        pack = self._pack(secondary="reformer")
        order = self._confirm(pack)
        total = sum(int(l.fitness_remaining_classes or 0)
                    for l in order.order_line
                    if l.product_id.fitness_is_package)

        notif = self._notifs()
        self.assertEqual(len(notif), 1)
        self.assertIn(
            str(total), notif.body or "",
            "the message does not name the number of credits she actually has")
