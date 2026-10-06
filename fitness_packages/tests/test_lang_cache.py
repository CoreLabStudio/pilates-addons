# -*- coding: utf-8 -*-
"""Two computed labels here must not leak across languages.

seats_label on the add-student wizard and fitness_promo_summary on the
product are both non-stored computed fields whose value is a sentence
built with _(). Odoo partitions a computed field's cache only by the
context keys the field declares, so without depends_context=('lang',)
the first language to compute one of them in a transaction is served
to every later reader in that transaction.

fitness_promo_summary is the one a student can actually be shown the
wrong language of: the shop renders it, and one page served to a
Spanish reader would prime the cache for an English one in the same
request batch.

The same fault as fitness_subscriptions' fitness_fixed_slot_warning.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, freeze_time, tagged

from odoo.addons.fitness_core.models.studio_time import studio_today
from odoo.addons.fitness_core.tests.lang_cache_common import LangCacheMixin

MODULE = 'fitness_packages'

#: 00:30 in Madrid, 23:30 UTC on the day before.
#:
#: Pinned so the promotion this file builds is always the same promotion.
#: fitness_effective_price() resolves "today" with studio_today(), so a
#: window measured from the UTC date is a day away from the one the
#: product compares it against for the hour before midnight in Madrid.
#: The window here is wide enough that the day does not flip the answer,
#: but fitness_promo_summary renders its end date through format_date -
#: so the string this file compares across languages is a different
#: string every day until the clock is pinned.
PINNED_UTC = '2026-11-09 23:30:00'


@tagged("post_install", "-at_install")
@freeze_time(PINNED_UTC)
class TestPackagesLangCache(LangCacheMixin, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_languages()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Lang cache room", "classroom_type": "reformer",
            "capacity": 6})
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Lang cache class", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})

    # ── the wizard's seat count ─────────────────────────────────────────

    def _wizard(self):
        """The wizard as it opens from a class with room left in it.

        A capacity is set on purpose: with none, the compute takes the
        "N booked" branch instead, and both branches are translated but
        only one of them says anything about free seats.
        """
        start = fields.Datetime.now() + timedelta(days=14)
        event = self.env["calendar.event"].create({
            "name": "Lang cache class", "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "classroom_id": self.room.id,
            "is_fitness_class": True, "capacity": 6,
        })
        # student_id is required on the wizard, so it has to be set even
        # though the field under test only reports the seat count.
        student = self.env["res.partner"].create(
            {"name": "Lang cache seat student"})
        return self.env["fitness.add.student.wizard"].create(
            {"event_id": event.id, "student_id": student.id})

    def test_seats_label_does_not_inherit_the_other_language(self):
        self.assertDoesNotLeakLanguage(self._wizard(), 'seats_label', MODULE)

    # ── the product's promotion badge ───────────────────────────────────

    def _product(self, **vals):
        base = {
            "name": "Lang cache product", "type": "service",
            "list_price": 50.0, "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 5,
            "fitness_validity_days": 60,
            "fitness_class_type": "reformer",
            "fitness_session_type": "group",
        }
        base.update(vals)
        return self.env["product.template"].create(base)

    def test_promo_summary_does_not_inherit_the_other_language(self):
        """The ordinary case: no promotion, so the badge reads Full price."""
        self.assertDoesNotLeakLanguage(
            self._product(fitness_promo_mode='none'),
            'fitness_promo_summary', MODULE)

    def test_promo_summary_with_a_live_promotion_does_not_leak_either(self):
        """The other branch, because it is the one with a date in it.

        A running promotion renders its end date through format_date as
        well as its wording through _(), so it is language-dependent
        twice over and worth pinning separately.
        """
        today = studio_today()
        product = self._product(
            fitness_promo_mode='percent', fitness_promo_percent=20.0,
            fitness_promo_start=today - timedelta(days=1),
            fitness_promo_end=today + timedelta(days=30))
        self.assertDoesNotLeakLanguage(
            product, 'fitness_promo_summary', MODULE)
