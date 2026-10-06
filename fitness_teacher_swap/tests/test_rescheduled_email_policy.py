# -*- coding: utf-8 -*-
"""The studio-rescheduled email states the cancellation rule.

"The studio has moved one of your classes to a new time" hands her a seat
at an hour she did not choose. It already says her place and credit are
unchanged; it said nothing about what cancelling the new time would cost.

The teacher-swap email next door is deliberately left alone: the class
has not moved there, only who teaches it.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_bookings.tests.booking_fixture import BookingFixture

TEMPLATE = 'fitness_teacher_swap.mail_template_class_rescheduled'
SWAP = 'fitness_teacher_swap.mail_template_teacher_swap'


@tagged("post_install", "-at_install")
class TestRescheduledEmailStatesThePolicy(
        BookingFixture, TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        # Built, not borrowed: searching for any existing booking made
        # these four skip on every fresh database and run only on the
        # restore, which is not coverage.
        self.booking = self._a_booking()

    def _render(self, xmlid, lang):
        self.booking.student_id.sudo().lang = lang
        return self.env.ref(xmlid).with_context(lang=lang)._render_field(
            'body_html', self.booking.ids)[self.booking.id]

    def _langs(self):
        out = ['en_US']
        for code in ('es_ES', 'ca_ES'):
            if self.env['res.lang']._activate_lang(code):
                out.append(code)
        return out

    def test_every_language_states_the_rule(self):
        halves = {
            'en_US': ('at least', 'less than'),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._render(TEMPLATE, lang)
            early, late = halves[lang]
            self.assertIn(early, body, "%s: rule missing" % lang)
            self.assertIn(late, body, "%s: late case missing" % lang)
            self.assertIn('6', body, "%s: no window stated" % lang)

    def test_it_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '5')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._render(TEMPLATE, 'en_US')
        self.assertIn('5 hours', body, "the email ignored the setting")
        self.assertNotIn('6 hours before the class', body)

    def test_the_teacher_swap_email_is_deliberately_left_alone(self):
        """Only who teaches it changed, so the booking is the same booking."""
        body = self._render(SWAP, 'en_US')
        self.assertNotIn('recover your credit', body,
                         "the rule was added to the swap email as well")

    def test_the_rest_of_the_email_is_untouched(self):
        body = self._render(TEMPLATE, 'en_US')
        for expected in ('moved one of your classes',
                         'Your place is still booked',
                         'The CoreLab team'):
            self.assertIn(expected, body, "%r disappeared" % expected)
