# -*- coding: utf-8 -*-
"""Her own history names all three outcomes of a cancellation.

It used to say "Credit returned", or nothing at all. Nothing is exactly
the case she rings the studio about - she cancelled late, the credit is
gone, and the app declines to mention it. And once the studio gives a
credit back as a goodwill exception, the row she is looking at has to say
so, or she rings again.

What she SEES is driven over HTTP as a real non-admin student, because
the badges are template text and a model-level assertion would prove
nothing about the page.

Spanish and Catalan are asserted against the catalogues rather than over
HTTP, and the reason is in translation_check: a fresh install carries
en_US alone, and activating a language inside a test does not import the
modules' .po into the views' arch_db - so a template term renders in
English on a gate database however correct the translation is. The
binding is checked too, which is the part that actually goes wrong here.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_portal.tests.translation_check import (
    TranslationCheck,
)

HISTORY = '/my/history'


@tagged("post_install", "-at_install")
class TestHistorySaysWhatHappened(TranslationCheck, HttpCase):

    longMessage = False

    RETURNED = 'Credit returned'
    KEPT = 'Credit kept'
    GIVEN = 'Credit given back'

    def setUp(self):
        super().setUp()
        self.window = self.env['fitness.booking'].sudo(
            )._cancellation_window_hours()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'History Student', 'login': 'history.student',
                'email': 'history.student@example.invalid',
                'password': 'history-pass-4471',
                'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        self.class_type = self.env['fitness.class.type'].sudo().create({
            'name': 'Hist Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        pack = self.env['product.template'].sudo().create({
            'name': 'Hist pack 10', 'list_price': 200.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 10,
            'fitness_validity_days': 180, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student.partner_id.id,
            'order_line': [(0, 0, {
                'product_id': pack.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 200.0,
                'fitness_class_type': 'reformer'})]})
        order.action_confirm()
        self.env.registry.clear_cache()

    def _cancelled(self, hours_before):
        """A booking cancelled that many hours before its start.

        The class stays in the future: /my/history's domain takes every
        cancelled booking whatever its date, and moving the event
        afterwards would only be exercising the move guards.
        """
        start = fields.Datetime.now() + timedelta(hours=hours_before)
        event = self.env['calendar.event'].sudo().create({
            'name': 'Hist class %+d' % hours_before, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group'})
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': self.student.partner_id.id,
            'calendar_event_id': event.id})
        booking.with_user(self.student).action_cancel()
        return booking

    def _manager(self):
        return self.env['res.users'].sudo().create({
            'name': 'Hist Manager', 'login': 'hist.manager@example.invalid',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('fitness_core.group_fitness_manager').id])]})

    def _page(self):
        self.authenticate('history.student', 'history-pass-4471')
        return self.url_open(HISTORY).text

    # == the case the feature exists for =============================
    def test_a_late_cancellation_says_the_credit_was_kept(self):
        self._cancelled(self.window - 2)
        body = self._page()
        self.assertIn(
            self.KEPT, body,
            "her history says nothing about the credit she lost, so she has "
            "to ring the studio to find out")

    def test_a_cancellation_in_good_time_still_says_returned(self):
        """Not a change. It must keep working."""
        booking = self._cancelled(self.window + 6)
        self.assertTrue(booking.credit_returned)
        body = self._page()
        self.assertIn(self.RETURNED, body)
        self.assertNotIn(
            self.KEPT, body,
            "a refunded cancellation is shown as having kept the credit")

    def test_the_forgiven_case_reads_as_given_back_not_as_kept(self):
        booking = self._cancelled(self.window - 2)
        booking.with_user(self._manager())._give_credit_back("She was ill.")

        body = self._page()
        self.assertIn(
            self.GIVEN, body,
            "the studio gave the credit back and her history still does not "
            "say so")
        self.assertNotIn(
            self.KEPT, body,
            "her history still says the credit was kept after the studio "
            "gave it back, so she rings again")

    def test_only_one_of_the_three_is_ever_shown(self):
        """They are a t-if/t-elif/t-else chain, so two on one row would
        mean the chain has been broken into separate conditions."""
        self._cancelled(self.window - 2)
        body = self._page()
        shown = [w for w in (self.RETURNED, self.KEPT, self.GIVEN)
                 if w in body]
        self.assertEqual(
            shown, [self.KEPT],
            "the row shows %s instead of exactly one outcome" % shown)

    def test_the_badge_is_a_block_element(self):
        """A lone inline span is folded into its parent's term, and the
        bare translation then never matches - four bugs and counting."""
        self._cancelled(self.window - 2)
        body = self._page()
        self.assertIn('mv-badge-nocredit', body)
        self.assertNotIn(
            '<span class="mv-badge-nocredit"', body,
            "the badge is an inline span, so its translation will not match")

    # == Spanish and Catalan =========================================
    def test_the_two_new_badges_are_translated_and_bound(self):
        self.assert_translated('fitness_portal', self.KEPT)
        self.assert_translated('fitness_portal', self.GIVEN)

    def test_a_kept_credit_does_not_read_as_a_returned_one(self):
        """The forfeit badge and the refund badge must not land on the
        same words in any language, or the badge tells her nothing."""
        from odoo.addons.fitness_portal.tests.translation_check import (
            LANGS, catalogue,
        )
        for lang, filename in sorted(LANGS.items()):
            cat = catalogue('fitness_portal', filename)
            kept = cat[self.KEPT][0].strip()
            returned = cat[self.RETURNED][0].strip()
            given = cat[self.GIVEN][0].strip()
            self.assertNotEqual(
                kept, returned,
                "%s: a kept credit and a returned one say the same thing: %r"
                % (lang, kept))
            self.assertNotEqual(
                kept, given,
                "%s: a kept credit and a credit given back say the same "
                "thing: %r" % (lang, kept))
            self.assertNotIn(
                returned, kept,
                "%s: %r contains %r, so a substring check on either screen "
                "matches the wrong one" % (lang, kept, returned))
