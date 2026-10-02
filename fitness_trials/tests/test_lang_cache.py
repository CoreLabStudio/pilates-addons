# -*- coding: utf-8 -*-
"""The four trial warnings must not leak across languages.

duplicate_warning, trial_used_warning, phone_match_warning and
occurrence_fill are non-stored computed fields whose value is a
sentence built with _(). Odoo partitions a computed field's cache only
by the context keys the field declares, so without
depends_context=('lang',) the first language to compute one of them
inside a transaction is handed to every later reader in it.

These three warnings sit side by side on the same form, and the list
view computes them for a whole page of requests at once - which is
exactly the shape that makes a per-transaction cache leak visible:
one Spanish request in the list and the rest read Spanish too.

The same fault as fitness_subscriptions' fitness_fixed_slot_warning.

Phone numbers are checked against the database before use, as the
other tests here do: the production restore carries real students with
real numbers, and an invented one that happens to be theirs would
flag, or fail to flag, for reasons unrelated to what is tested.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_core.tests.lang_cache_common import LangCacheMixin

MODULE = 'fitness_trials'


@tagged("post_install", "-at_install")
class TestTrialWarningsLangCache(LangCacheMixin, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_languages()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        # The offer has a deadline and these fixtures need it open. Pinned
        # rather than left to the calendar, which is how several tests in
        # this module started failing on a date instead of on their subject.
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        cls.TR = cls.env["fitness.trial.request"].sudo()
        cls.trial_product = cls.TR._all_trial_products()[:1]

        taken = set()
        for partner in cls.env["res.partner"].sudo().with_context(
                active_test=False).search([("phone", "!=", False)]):
            taken.add(cls.TR._phone_key(partner.phone))
        taken.discard("")
        cls._taken_numbers = taken

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Lang cache trial room", "classroom_type": "reformer",
            "capacity": 6})
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Lang cache trial class", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})

    # ── fixtures ────────────────────────────────────────────────────────

    def _free_number(self):
        """Nine digits nobody on this database is already using."""
        n = 613000000
        while str(n) in self._taken_numbers:
            n += 1
        self._taken_numbers.add(str(n))
        return str(n)

    def _partner(self, suffix, phone=False):
        return self.env["res.partner"].create({
            "name": "Lang cache %s" % suffix,
            "email": "langcache.%s@example.invalid" % suffix,
            "phone": phone,
        })

    def _spend_her_trial(self, partner):
        """A spent trial is a confirmed order for a trial product at zero."""
        order = self.env["sale.order"].sudo().create(
            {"partner_id": partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.trial_product.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 0.0,
        })
        order.action_confirm()
        self.env.flush_all()
        return order

    def _request(self, **vals):
        base = {
            "name": "Lang cache request",
            "email": "langcache.req@example.invalid",
            "class_interest": "reformer",
            "status": "pending",
            "lang": "en_US",
        }
        base.update(vals)
        req = self.TR.create(base)
        self.env.invalidate_all()
        return req

    def _event(self, capacity=6):
        start = fields.Datetime.now() + timedelta(days=10)
        return self.env["calendar.event"].sudo().create({
            "name": "Lang cache trial slot", "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "classroom_id": self.room.id,
            "is_fitness_class": True, "capacity": capacity,
        })

    # ── 1. two open requests under one address ──────────────────────────

    def test_duplicate_warning_does_not_inherit_the_other_language(self):
        email = "langcache.dup@example.invalid"
        self._request(email=email, name="Lang cache dup one")
        req = self._request(email=email, name="Lang cache dup two")

        self.assertTrue(
            req.duplicate_warning,
            "fixture wrong: two open requests on one address and no warning")
        self.assertDoesNotLeakLanguage(req, 'duplicate_warning', MODULE)

    # ── 2. she has already had her free trial ───────────────────────────

    def test_trial_used_warning_does_not_inherit_the_other_language(self):
        partner = self._partner("spent")
        self._spend_her_trial(partner)
        req = self._request(
            email=partner.email, name=partner.name, partner_id=partner.id)

        self.assertTrue(
            req.trial_used_warning,
            "fixture wrong: her trial is spent and nothing says so")
        self.assertDoesNotLeakLanguage(req, 'trial_used_warning', MODULE)

    # ── 3. recognised by her phone, under a new address ─────────────────

    def test_phone_match_warning_does_not_inherit_the_other_language(self):
        phone = self._free_number()
        partner = self._partner("phone", phone=phone)
        self._spend_her_trial(partner)
        # A public submission: new address, no partner attached, same number.
        req = self._request(
            email="langcache.stranger@example.invalid",
            name="Someone Else", phone=phone)
        req.partner_id = False
        self.env.invalidate_all()

        self.assertTrue(
            req.phone_match_warning,
            "fixture wrong: the number belongs to a student whose trial is "
            "spent and nothing matched it")
        self.assertDoesNotLeakLanguage(req, 'phone_match_warning', MODULE)

    # ── 4. how full the chosen slot is ──────────────────────────────────

    def test_occurrence_fill_does_not_inherit_the_other_language(self):
        req = self._request(occurrence_id=self._event().id)

        self.assertTrue(
            req.occurrence_fill,
            "fixture wrong: a slot is chosen and its fill reads empty")
        self.assertDoesNotLeakLanguage(req, 'occurrence_fill', MODULE)

    def test_occurrence_fill_on_a_slot_with_no_capacity_also_holds(self):
        """The other branch: no capacity takes a different sentence."""
        req = self._request(occurrence_id=self._event(capacity=0).id)

        self.assertTrue(req.occurrence_fill, "fixture wrong: reads empty")
        self.assertDoesNotLeakLanguage(req, 'occurrence_fill', MODULE)
