from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    consent_terms_date = fields.Datetime(string='Terms Accepted On', readonly=True)
    consent_marketing = fields.Boolean(string='Marketing Email Consent', default=False)
    consent_marketing_date = fields.Datetime(string='Marketing Consent On', readonly=True)
