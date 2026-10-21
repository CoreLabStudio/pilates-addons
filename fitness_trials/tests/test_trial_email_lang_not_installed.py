# -*- coding: utf-8 -*-
"""A trial email goes out even when her language is not installed.

The trial emails render in the request's language (the template's lang).
_trial_lang() returned es_ES, ca_ES or en_US without asking whether the
language was installed, and Odoo refuses to render in one it does not have:
on odoo.sh's main build - a fresh database without Spanish - every trial
email failed with "Invalid language code: es_ES", was caught, logged as a
warning, and never sent (21 Oct 2026, 22 tracebacks, merge 2 a1458ce).

The gate loads es and ca, which is why it never showed. Here Spanish and
Catalan are switched off for the test, as on that build.
"""
import logging

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTrialEmailLangNotInstalled(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        Lang = self.env['res.lang'].sudo().with_context(active_test=False)
        en = Lang.search([('code', '=', 'en_US')])
        en.active = True
        # Nobody may keep a language being switched off: move them to English.
        others = Lang.search([('code', 'in', ('es_ES', 'ca_ES')), ('active', '=', True)])
        if others:
            self.env['res.users'].sudo().with_context(active_test=False).search(
                [('lang', 'in', others.mapped('code'))]).write({'lang': 'en_US'})
            self.env['res.partner'].sudo().with_context(active_test=False).search(
                [('lang', 'in', others.mapped('code'))]).write({'lang': 'en_US'})
            others.write({'active': False})
        self.env.registry.clear_cache()
        self.assertNotIn('es_ES', dict(self.env['res.lang'].get_installed()),
                         'fixture: Spanish is still installed')

    def test_a_request_made_in_spanish_still_gets_its_email(self):
        logger = 'odoo.addons.fitness_trials.models.trial_request'
        with self.assertNoLogs(logger, level=logging.WARNING):
            req = self.env['fitness.trial.request'].sudo().create({
                'name': 'Sin Idioma', 'email': 'sin.idioma@example.invalid',
                'class_interest': 'reformer', 'status': 'pending', 'lang': 'es_ES'})
        self.assertIn(req.mail_lang, dict(self.env['res.lang'].get_installed()),
                      'the email would render in a language that is not installed')
        mails = self.env['mail.mail'].sudo().search([('email_to', 'ilike', 'sin.idioma@example.invalid')])
        self.assertTrue(mails, 'no email was queued for the request')
