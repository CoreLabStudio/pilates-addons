# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.fitness_core.models.studio_lang import recipient_lang


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    # Which campaign minted this token. Without it a campaign cannot tell
    # its own answers from the ones Yoleyva collected by sharing the survey
    # link herself, and the response rate would count strangers.
    fitness_campaign_id = fields.Many2one(
        'fitness.campaign', string='Campaign', readonly=True, index=True,
        ondelete='set null')

    # The language the invite is written in. The template used to say
    # {{ object.partner_id.lang }}, and a template's lang wins over the
    # send context, so the campaign's own _deliverable_lang never reached
    # the email: a student carrying a deactivated language raised "Invalid
    # language code", the send swallowed it and she got nothing. Hers when
    # it is active, else the studio's.
    fitness_mail_lang = fields.Char(
        "Mail Language", compute='_compute_fitness_mail_lang')

    @api.depends('partner_id.lang')
    def _compute_fitness_mail_lang(self):
        for answer in self:
            answer.fitness_mail_lang = recipient_lang(
                self.env, answer.partner_id)
