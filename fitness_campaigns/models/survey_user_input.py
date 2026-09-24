# -*- coding: utf-8 -*-
from odoo import fields, models


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    # Which campaign minted this token. Without it a campaign cannot tell
    # its own answers from the ones Yoleyva collected by sharing the survey
    # link herself, and the response rate would count strangers.
    fitness_campaign_id = fields.Many2one(
        'fitness.campaign', string='Campaign', readonly=True, index=True,
        ondelete='set null')
