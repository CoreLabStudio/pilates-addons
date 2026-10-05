# -*- coding: utf-8 -*-
"""The trial approval email states the cancellation rule.

"Tu clase de prueba en CoreLab esta confirmada" told her when to come and
nothing about what happens if she cannot. For a trial that matters more
than for a pack: cancelling inside the window spends the single free class
she gets, and only the studio can hand it back.

This template renders a fitness.trial.request, which has no cancellation
helpers of its own, so it reaches the booking model through the
environment. The tests check the number follows the setting, not that it
says six.
"""
from odoo.tests import TransactionCase, tagged

TEMPLATE = 'fitness_trials.mail_template_trial_scheduled'


@tagged("post_install", "-at_install")
class TestTrialEmailStatesThePolicy(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.template = self.env.ref(TEMPLATE)
        self.request = self.env['fitness.trial.request'].sudo().create({
            'name': 'Policy Trial', 'email': 'policy.trial@example.invalid',
            'class_interest': 'barre', 'status': 'pending'})

    def _render(self, lang):
        self.request.sudo().lang = lang
        return self.template.with_context(lang=lang)._render_field(
            'body_html', self.request.ids)[self.request.id]

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
            body = self._render(lang)
            early, late = halves[lang]
            self.assertIn(early, body,
                          "%s: the trial email is missing the rule" % lang)
            self.assertIn(late, body,
                          "%s: it does not state the late case" % lang)
            self.assertIn('6', body, "%s: no window stated" % lang)

    def test_it_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.cancellation_window_hours', '8')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)
        body = self._render('en_US')
        self.assertIn('8 hours', body,
                      "the trial email ignored the setting")
        self.assertNotIn('6 hours before the class', body)

    def test_no_hardcoded_number_in_the_template(self):
        """The source must not contain the figure at all."""
        import io
        from odoo.modules.module import get_module_path
        path = get_module_path('fitness_trials') + \
            '/data/mail_templates.xml'
        src = io.open(path, encoding='utf-8').read()
        for phrase in ('al menos 6 horas', 'almenys 6 hores',
                       'at least 6 hours'):
            self.assertNotIn(phrase, src,
                             "%r is hardcoded in the trial template" % phrase)

    def test_the_rest_of_the_email_is_untouched(self):
        body = self._render('en_US')
        self.assertIn('your trial class is confirmed', body.lower(),
                      "the confirmation line disappeared")
        self.assertIn('CoreLab Studio', body,
                      "the sign-off disappeared")
