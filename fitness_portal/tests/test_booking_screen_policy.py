# -*- coding: utf-8 -*-
"""The booking confirmation screen states the cancellation rule.

The student was told "Booked! Your spot is confirmed" and nothing about
what happens if she cannot come. The rule existed - in the Terms she
accepted at signup, and nowhere she would look again.

Driven over HTTP as a real non-admin student, because the sentence is
built in the controller and rendered by the template, and a model-level
call would prove neither. Redirects are followed and the language prefix
stripped before the landing path is reported.
"""
import re

from odoo.tests import HttpCase, tagged

LANG_PREFIX = re.compile(r'^/(?:es|ca|en)(?:_[A-Z]{2})?(?=/)')


@tagged("post_install", "-at_install")
class TestBookingScreenStatesThePolicy(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Policy Student', 'login': 'policy.student',
                'email': 'policy.student@example.invalid',
                'password': 'policy-pass-9134',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        self.env.registry.clear_cache()

    def _get(self, path, lang='en_US'):
        self.student.sudo().lang = lang
        self.env.registry.clear_cache()
        self.authenticate('policy.student', 'policy-pass-9134')
        return self.url_open(path).text

    def _langs(self):
        out = ['en_US']
        for code in ('es_ES', 'ca_ES'):
            if self.env['res.lang']._activate_lang(code):
                out.append(code)
        return out

    def test_the_booked_screen_states_the_rule_in_every_language(self):
        halves = {
            'en_US': ('at least', 'less than'),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._get('/my/studio?booked=1', lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "%s: the screen does not say how to keep the credit"
                          % lang)
            self.assertIn(late, body,
                          "%s: the screen does not state the late case" % lang)
            self.assertIn('6', body,
                          "%s: the screen does not state the window" % lang)

    def test_it_follows_the_setting_rather_than_a_hardcoded_six(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '12')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._get('/my/studio?booked=1')
        self.assertIn('12 hours', body,
                      "the screen ignored fitness.cancellation_window_hours")
        self.assertNotIn('6 hours before the class', body,
                         "the screen still promises the old window")

    def test_a_half_hour_window_is_not_shown_as_a_float(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '1.5')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._get('/my/studio?booked=1')
        self.assertIn('1.5 hours', body)
        self.assertNotIn('6.0', body)

    def test_the_confirmation_flash_is_not_shown_when_she_has_not_booked(self):
        """An addition to the confirmation, not a banner on every visit.

        Checked on the flash itself rather than on the page text. The cancel
        sheet also carries the sentence now, by design, and it ships in the
        markup of every studio page hidden until she taps Cancel - so the
        words being present in the HTML no longer means she is being shown
        them. This assertion used to pass for the wrong reason.
        """
        body = self._get('/my/studio')
        self.assertNotIn('mv-flash-ok', body,
                         "the booking confirmation flash is showing when she "
                         "has not just booked")

    def test_the_cancel_sheet_carries_the_same_sentence(self):
        """The sheet that asks "Cancel this class?" said it in its own words,
        with the figure written in. One sentence now, from the setting."""
        body = self._get('/my/studio')
        self.assertIn('mv-confirm-body', body, "the cancel sheet is missing")
        self.assertIn('recover your credit', body,
                      "the cancel sheet does not state the rule")
        self.assertNotIn('Inside that window the credit is used', body,
                         "the old sheet wording is still there")

    def test_the_rest_of_the_confirmation_is_untouched(self):
        body = self._get('/my/studio?booked=1')
        for expected in ('Booked!', 'Your spot is confirmed'):
            self.assertIn(expected, body,
                          "%r disappeared from the confirmation" % expected)

    def test_the_free_trial_confirmation_states_it_too(self):
        """A free trial is still a seat, and a late cancellation spends the
        one free class she gets - proven on trialprobe: the entitlement stays
        used unless the studio hands it back."""
        halves = {
            'en_US': ('at least', 'less than'),
            'es_ES': ('al menos', 'con menos de'),
            'ca_ES': ('almenys', 'amb menys de'),
        }
        for lang in self._langs():
            body = self._get('/my/packages?booked=1', lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "%s: the free-trial confirmation is missing the rule"
                          % lang)
            self.assertIn(late, body,
                          "%s: it does not state the late case" % lang)
            self.assertIn('6', body, "%s: no window stated" % lang)

    def test_the_free_trial_confirmation_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '9')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._get('/my/packages?booked=1')
        self.assertIn('9 hours', body)
        self.assertNotIn('6 hours before the class', body)

    # ── the places that already stated it, now sharing one sentence ──────
    def test_the_upcoming_class_lines_use_the_shared_sentence(self):
        """Two lines on the class page said "Cancel up to 6 hours before
        class to keep your credit" with the figure written in. They now read
        the same sentence as everywhere else, from the same setting."""
        booking = self.env['fitness.booking'].sudo().search([], limit=1)
        if not booking:
            self.skipTest("no booking to open a class page against")
        body = self._get('/my/classes/%d' % booking.calendar_event_id.id)
        self.assertNotIn('Cancel up to 6 hours before class', body,
                         "the old hardcoded line is still rendered")

    def test_no_hardcoded_window_remains_in_the_portal_templates(self):
        """The figure must not be written down anywhere these pages render."""
        import io as _io
        from odoo.modules.module import get_module_path
        src = _io.open(
            get_module_path('fitness_portal') +
            '/views/portal_templates.xml', encoding='utf-8').read()
        for phrase in ('Cancel up to 6 hours',
                       'Inside that window the credit is used'):
            self.assertNotIn(phrase, src,
                             "%r is still hardcoded in the templates" % phrase)
