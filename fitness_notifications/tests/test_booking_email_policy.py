# -*- coding: utf-8 -*-
"""The confirmation email has to say what happens if she cancels.

It listed the class, the time, the room and the credits left, and said
nothing at all about the cancellation window - so the one rule that costs
a student a credit was the one thing the email never mentioned. She had
to find it in the app, or discover it afterwards.

The window is a system parameter, so the tests check the email follows it
rather than checking for the number six. A studio that changes the setting
and finds its emails still promising the old number would be worse off
than before.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_bookings.tests.booking_fixture import BookingFixture

TEMPLATE = 'fitness_notifications.mail_template_booking_confirmation'
REMINDER = 'fitness_notifications.mail_template_class_reminder'
MOVED = 'fitness_notifications.mail_template_booking_moved'


@tagged("post_install", "-at_install")
class TestBookingEmailMentionsTheCancellationPolicy(
        BookingFixture, TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.template = self.env.ref(TEMPLATE)
        # Built here, not borrowed from the database. Searching for any
        # existing booking meant these eleven tests skipped on every fresh
        # database and only ran on the restore - and a skip is an untested
        # line, not a pass. They were written to protect wording the studio
        # cares about, so they have to run everywhere.
        self.booking = self._a_booking()


    def _render(self, lang):
        self.booking.student_id.sudo().lang = lang
        return self.template.with_context(lang=lang)._render_field(
            'body_html', self.booking.ids)[self.booking.id]

    def _langs(self):
        """Only the languages actually installed here."""
        out = ['en_US']
        for code in ('es_ES', 'ca_ES'):
            if self.env['res.lang']._activate_lang(code):
                out.append(code)
        return out

    #: The phrasing the Terms themselves use. "Dentro de ese plazo el credito
    #: se consume" was the first attempt and reads backwards in Spanish - it
    #: can be taken as "if you cancel in time the credit is used" - so the
    #: late case now names the window explicitly, as section 4 of the Terms
    #: does.
    GONE = ('Dentro de ese plazo', "Dins d'aquest termini", 'Inside that window')

    def test_every_language_states_both_halves_of_the_rule(self):
        halves = {
            'en_US': ('at least', "less than"),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._render(lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "the %s email does not say how to keep the credit"
                          % lang)
            self.assertIn(late, body,
                          "the %s email does not state the late case" % lang)
            self.assertIn('6', body,
                          "the %s email does not state the window" % lang)

    def test_the_sentence_that_reads_backwards_is_gone(self):
        for lang in self._langs():
            body = self._render(lang)
            for phrase in self.GONE:
                self.assertNotIn(
                    phrase, body,
                    "the %s email still carries %r, which reads backwards"
                    % (lang, phrase))

    def test_it_follows_the_setting_rather_than_a_hardcoded_six(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '12')
        self.env.registry.clear_cache()
        body = self._render('en_US')
        self.assertIn('12 hours', body,
                      "the email ignored fitness.cancellation_window_hours")
        self.assertNotIn('6 hours', body,
                         "the email still promises the old window")
        self.addCleanup(self.env.registry.clear_cache)

    def test_a_half_hour_window_is_not_shown_as_a_float(self):
        """1.5 stays 1.5; 6.0 must not reach a student as '6.0'."""
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '1.5')
        self.env.registry.clear_cache()
        body = self._render('en_US')
        self.assertIn('1.5 hours', body)
        self.assertNotIn('6.0', body)
        self.addCleanup(self.env.registry.clear_cache)

    def test_the_rest_of_the_email_is_untouched(self):
        """The policy is an addition, not a rewrite."""
        body = self._render('en_US')
        for expected in ('Your booking is confirmed', 'Class:', 'Date/Time:',
                         'Classroom:', 'Instructor:', 'See you soon'):
            self.assertIn(expected, body,
                          "%r disappeared from the confirmation" % expected)

    # ── the reminder, which shows the same specific booked class ─────────
    def _render_reminder(self, lang):
        self.booking.student_id.sudo().lang = lang
        tmpl = self.env.ref(REMINDER)
        return tmpl.with_context(lang=lang)._render_field(
            'body_html', self.booking.ids)[self.booking.id]

    def test_the_reminder_states_the_rule_in_every_language(self):
        halves = {
            'en_US': ('at least', 'less than'),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._render_reminder(lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "%s: the reminder is missing the rule" % lang)
            self.assertIn(late, body,
                          "%s: it does not state the late case" % lang)
            self.assertIn('6', body, "%s: no window stated" % lang)

    def test_the_reminder_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '4')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._render_reminder('en_US')
        self.assertIn('4 hours', body, "the reminder ignored the setting")
        self.assertNotIn('6 hours before the class', body)

    def test_the_rest_of_the_reminder_is_untouched(self):
        body = self._render_reminder('en_US')
        for expected in ('Reminder', 'See you there'):
            self.assertIn(expected, body,
                          "%r disappeared from the reminder" % expected)

    # ── the moved-class email: a different class, still one she holds ────
    def _render_moved(self, lang):
        self.booking.student_id.sudo().lang = lang
        tmpl = self.env.ref(MOVED)
        return tmpl.with_context(lang=lang)._render_field(
            'body_html', self.booking.ids)[self.booking.id]

    def test_the_moved_email_states_the_rule_in_every_language(self):
        halves = {
            'en_US': ('at least', 'less than'),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._render_moved(lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "%s: the moved email is missing the rule" % lang)
            self.assertIn(late, body,
                          "%s: it does not state the late case" % lang)
            self.assertIn('6', body, "%s: no window stated" % lang)

    def test_the_moved_email_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '3')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._render_moved('en_US')
        self.assertIn('3 hours', body, "the moved email ignored the setting")
        self.assertNotIn('6 hours before the class', body)

    def test_the_rest_of_the_moved_email_is_untouched(self):
        body = self._render_moved('en_US')
        for expected in ('We have moved your booking',
                         'Your credit has not changed'):
            self.assertIn(expected, body,
                          "%r disappeared from the moved email" % expected)
