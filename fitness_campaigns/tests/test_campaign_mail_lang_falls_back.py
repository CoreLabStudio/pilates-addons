# -*- coding: utf-8 -*-
"""The campaign invite survives a student with an inactive language.

The campaign already picks a deliverable language for the bell and the
send context (_deliverable_lang), but the template's own lang field was
{{ object.partner_id.lang }}, and a template's lang wins over the
context. Odoo refuses to render in a code that is not active ("Invalid
language code"), the send's try/except swallowed it, and she got no
email. The template now uses the answer's fitness_mail_lang: hers when
active, else the studio's.

The inactive code is written by SQL: the ORM will not store it, and will
not deactivate a language a partner holds.
"""
from odoo.tests import TransactionCase, tagged

INACTIVE = 'fr_FR'


@tagged('post_install', '-at_install')
class TestCampaignMailLangFallsBack(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_and_install_lang('es_ES')
        cls.survey = cls.env['survey.survey'].create({
            'title': 'ML How was your class?',
            'access_mode': 'public', 'is_attempts_limited': False})
        cls.env['survey.question'].create({
            'survey_id': cls.survey.id, 'title': 'Did you enjoy it?',
            'question_type': 'char_box', 'sequence': 1})

    def setUp(self):
        super().setUp()
        self.env.company.partner_id.lang = 'es_ES'
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', INACTIVE)])
        self.assertTrue(lang and not lang.active,
                        'fixture: %s must exist and be inactive' % INACTIVE)
        self.partner = self.env['res.partner'].create({
            'name': 'ML Campaign Student',
            'email': 'ml.campaign@example.invalid', 'lang': 'en_US'})
        self.answer = self.survey.sudo()._create_answer(
            partner=self.partner, check_attempts=False)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET lang = %s WHERE id = %s",
            (INACTIVE, self.partner.id))
        self.env.invalidate_all()
        self.assertEqual(self.answer.partner_id.lang, INACTIVE)

    def test_invite_renders_in_the_studio_language(self):
        template = self.env.ref(
            'fitness_campaigns.mail_template_campaign_invite')
        mail_id = template.sudo().send_mail(
            self.answer.id, force_send=False,
            email_values={'email_to': self.partner.email})
        mail = self.env['mail.mail'].sudo().browse(mail_id)
        self.assertTrue(mail.exists(), 'no mail was queued')
        body = str(mail.body_html)
        self.assertIn('Nos encantaría saber qué opinas', body)
        self.assertIn('Responder', body)
