# -*- coding: utf-8 -*-
"""Before she taps Yes, she is told THIS cancellation costs her the credit.

She can now cancel inside the window, which is right - the seat gets
freed and the Terms already said what it costs. But the confirmation
sheet showed only the general rule, in the same grey as everything else,
identically on every booking. A student reading "you must cancel at least
six hours before" at 07:40 about an 08:00 class has to do the arithmetic
herself, in a hurry, on a phone.

What she sees is driven over HTTP as a real non-admin student, because
the sentence is built in the controller and revealed by template markup,
and neither a model test nor a controller test would prove it reached the
page.

Spanish and Catalan go through the catalogue, for the reason set out in
translation_check.

NO RULE CHANGES HERE. The warning describes what already happens.
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_portal.tests.translation_check import (
    TranslationCheck,
)

#: the page that lists her booked classes, each with a cancel form.
#: /my/schedule redirects here; the list is the view=schedule branch of
#: portal_student_studio, and the default branch has no cancel forms at
#: all - which is how the first version of this file passed nothing.
SCHEDULE = '/my/studio?view=schedule'

WARNING = ("This class starts in less than %(hours)s hours. If you cancel "
           "now you will not get your credit back.")


@tagged("post_install", "-at_install")
class TestCancelWarnsAboutTheCredit(TranslationCheck, HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.window = self.env['fitness.booking'].sudo(
            )._cancellation_window_hours()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Warn Student', 'login': 'warn.student',
                'email': 'warn.student@example.invalid',
                'password': 'warn-pass-7752', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        self.class_type = self.env['fitness.class.type'].sudo().create({
            'name': 'Warn Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        pack = self.env['product.template'].sudo().create({
            'name': 'Warn pack 10', 'list_price': 200.0, 'type': 'service',
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

    def _booking(self, hours_ahead):
        start = fields.Datetime.now() + timedelta(hours=hours_ahead)
        event = self.env['calendar.event'].sudo().create({
            'name': 'Warn class %+d' % hours_ahead, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group'})
        return self.env['fitness.booking'].sudo().create({
            'student_id': self.student.partner_id.id,
            'calendar_event_id': event.id})

    def _page(self, path=SCHEDULE):
        self.authenticate('warn.student', 'warn-pass-7752')
        return self.url_open(path).text

    # == the flag, which is what the markup carries ==================
    def test_a_booking_inside_the_window_forfeits(self):
        self.assertTrue(self._booking(self.window - 2).fitness_cancel_forfeits)

    def test_a_booking_in_good_time_does_not(self):
        self.assertFalse(self._booking(self.window + 6).fitness_cancel_forfeits)

    def test_the_boundary_belongs_to_the_forfeit_side(self):
        """Exactly at the window, action_cancel does not return the credit
        - hours_until <= window - so the warning must agree with it.
        Disagreeing by one side of an inequality is how a student is told
        she keeps a credit she then loses.
        """
        # Booked well ahead and then moved onto the boundary:
        # _validate_new_booking refuses a class at or before now, so it
        # cannot be created there.
        booking = self._booking(self.window + 10)
        booking.calendar_event_id.sudo().write({
            'start': fields.Datetime.now() + timedelta(hours=self.window)})
        booking.invalidate_recordset()
        self.assertTrue(booking.fitness_cancel_forfeits)

    def test_a_class_that_has_started_does_not_warn(self):
        """She is refused outright, with its own message. Warning her
        about a credit here would answer a question she is not asking."""
        booking = self._booking(2)
        booking.calendar_event_id.sudo().write({
            'start': fields.Datetime.now() - timedelta(hours=1)})
        booking.invalidate_recordset()
        self.assertFalse(booking.fitness_cancel_forfeits)

    def test_a_cancelled_booking_does_not_warn(self):
        booking = self._booking(self.window - 2)
        booking.with_user(self.student).action_cancel()
        booking.invalidate_recordset()
        self.assertFalse(booking.fitness_cancel_forfeits)

    def test_it_follows_the_setting(self):
        booking = self._booking(self.window + 6)
        self.assertFalse(booking.fitness_cancel_forfeits)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', str(self.window + 12))
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        booking.invalidate_recordset()
        self.assertTrue(
            booking.fitness_cancel_forfeits,
            "the warning ignored fitness.cancellation_window_hours, so a "
            "studio that widens its window warns nobody")

    # == what she actually sees =======================================
    def test_the_sheet_warns_her(self):
        self._booking(self.window - 2)
        body = self._page()
        self.assertIn(
            'you will not get your credit back', body,
            "the sheet does not say she will lose the credit, so she has to "
            "do the arithmetic herself on a phone")

    def test_the_form_carries_the_flag_for_the_sheet_to_read(self):
        """One sheet serves every card in her list, so the decision has to
        travel on the form, not on the page."""
        self._booking(self.window - 2)
        self.assertIn('data-forfeit="1"', self._page())

    def test_a_booking_in_good_time_carries_a_zero(self):
        self._booking(self.window + 6)
        body = self._page()
        self.assertIn('data-forfeit="0"', body)
        self.assertNotIn(
            'data-forfeit="1"', body,
            "a booking she can still cancel for free is marked as a "
            "forfeit, so she is frightened out of cancelling at all")

    def test_both_bookings_on_one_page_are_marked_differently(self):
        """The real case: two classes in her list, one late and one not.
        A page-level flag would get one of them wrong."""
        self._booking(self.window - 2)
        self._booking(self.window + 30)
        body = self._page()
        self.assertIn('data-forfeit="1"', body)
        self.assertIn(
            'data-forfeit="0"', body,
            "both cards were marked the same, so the sheet warns about the "
            "wrong class")

    def test_the_warning_ships_hidden(self):
        """It is in the markup of every page, revealed by the script. If it
        shipped visible, every student would be warned on every page."""
        self._booking(self.window + 30)
        body = self._page()
        tag = re.search(r'<p[^>]*id="mv-cancel-forfeit"[^>]*>', body)
        self.assertTrue(tag, "the forfeit warning is not on the page at all")
        self.assertIn(
            'hidden', tag.group(0),
            "the forfeit warning does not ship hidden, so every student is "
            "warned about every class: %s" % tag.group(0))

    def test_the_general_rule_is_still_there_too(self):
        """The warning is an addition, not a replacement: one states what
        it costs her here, the other states the rule."""
        self._booking(self.window - 2)
        body = self._page()
        self.assertIn('mv-confirm-body', body)
        self.assertIn('recover your credit', body)

    def test_the_warning_is_a_block_element(self):
        """A lone inline span is folded into its parent's term and the bare
        translation never matches - four bugs and counting."""
        self._booking(self.window - 2)
        self.assertNotIn(
            '<span class="mv-confirm-warning"', self._page(),
            "the warning is an inline span, so its translation will not "
            "match and she gets it in English")

    def test_the_number_is_not_written_into_the_sentence(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '12')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        self._booking(6)
        body = self._page()
        self.assertIn('less than 12 hours', body)
        self.assertNotIn(
            'starts in less than 6 hours', body,
            "the warning still promises the old window")

    # == Spanish and Catalan =========================================
    def test_the_warning_is_translated(self):
        self.assert_translated('fitness_portal', WARNING)

    def test_the_translations_keep_the_placeholder(self):
        """%(hours)s dropped from a translation is not a wording choice:
        the sentence would promise nothing and the format would raise."""
        from odoo.addons.fitness_portal.tests.translation_check import (
            LANGS, catalogue,
        )
        for lang, filename in sorted(LANGS.items()):
            msgstr = catalogue('fitness_portal', filename)[WARNING][0]
            self.assertIn(
                '%(hours)s', msgstr,
                "%s drops %%(hours)s from the warning, so it states no "
                "window at all" % lang)

    def test_the_already_started_refusal_is_translated_too(self):
        """It shipped in English in the first commit of this batch."""
        self.assert_translated(
            'fitness_bookings',
            "%(klass)s has already started, so it can no longer be "
            "cancelled. Speak to the studio.")
