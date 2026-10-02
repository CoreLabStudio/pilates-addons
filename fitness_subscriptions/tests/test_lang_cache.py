# -*- coding: utf-8 -*-
"""The fixed-slot warning must not leak across languages.

This is the field the whole depends_context problem was found on, and
until now it was the one field with no test for it. Its existing
tests, in fitness_portal, assert on the WORDS of the warning; they
caught the bug by accident, on the upgrade shape, because the
restore's users are Spanish and the sentence had just been
translated. On an English-only database they pass whether the
attribute is there or not, so they are not a guard against this
coming back.

This one is: it fakes a Spanish translation, computes the warning in
Spanish, and then reads it in English inside the same transaction.
Without depends_context=('lang',) the English read is handed the
Spanish value out of the cache.

See fitness_core/tests/lang_cache_common.py for why the translation
is faked rather than taken from the .po.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_core.tests.lang_cache_common import LangCacheMixin

MODULE = 'fitness_subscriptions'


@tagged("post_install", "-at_install")
class TestFixedSlotWarningLangCache(LangCacheMixin, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_languages()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.plan = cls.env.ref("sale_subscription.subscription_plan_month")
        cls.product = cls.env["product.template"].create({
            "name": "Lang cache fixed plan", "type": "service",
            "list_price": 90.0, "sale_ok": True, "recurring_invoice": True,
            "fitness_is_subscription_plan": True,
            "fitness_subscription_plan_id": cls.plan.id,
            "fitness_is_clase_fija": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": 1,
        })
        cls.partner = cls.env["res.partner"].create(
            {"name": "Lang cache fixed student"})

    def _owing_an_hour(self):
        """A paid fixed-class membership with no weekly hour chosen.

        That is the only state in which the warning says anything, so
        it is the only one worth reading it in.
        """
        order = self.env["sale.order"].sudo().create({
            "partner_id": self.partner.id, "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_ids[:1].id,
                "product_uom_qty": 1})],
        })
        order.action_confirm()
        self.env.invalidate_all()
        return order

    def test_the_warning_does_not_inherit_the_other_language(self):
        order = self._owing_an_hour()
        self.assertTrue(
            order.fitness_needs_fixed_slot,
            "fixture wrong: the membership owes an hour and does not say so")
        self.assertDoesNotLeakLanguage(
            order, 'fitness_fixed_slot_warning', MODULE)

    def test_reading_the_same_language_twice_is_still_cached(self):
        """The fix must partition the cache, not switch it off."""
        order = self._owing_an_hour()
        first = order.with_context(lang='en_US').fitness_fixed_slot_warning
        second = order.with_context(lang='en_US').fitness_fixed_slot_warning
        self.assertEqual(
            first, second,
            "the same language read twice gave two different answers")
