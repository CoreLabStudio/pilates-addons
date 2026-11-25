# -*- coding: utf-8 -*-
"""The desk's contact: found by email, created by email, never duplicated.

Owner's rule (25 Nov 2026), for the Student field of Sell at the desk:

  * creating a new contact there with an email another contact already has
    is refused, and the message names that contact so staff can pick it;
  * picking an existing contact whose email also sits on another contact
    only warns, naming the other one. Duplicates already exist, and a block
    would strand a sale.

The field's quick create passes `fitness_desk_new_contact` in its context;
nothing else in the system is affected.
"""
from odoo import _, api, models, tools
from odoo.exceptions import UserError


class ResPartnerDeskContact(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _fitness_active_contacts_with_email(self, email):
        normalized = tools.email_normalize(email or '')
        if not normalized:
            return self.browse()
        return self.sudo().search([
            ('email_normalized', '=', normalized),
            ('is_company', '=', False),
        ])

    @api.model
    def name_create(self, name):
        if self.env.context.get('fitness_desk_new_contact'):
            _name, email = tools.parse_contact_from_email(name or '')
            same = self._fitness_active_contacts_with_email(email)
            if same:
                raise UserError(_(
                    "%(email)s is already the email of %(names)s. Pick that "
                    "contact in Student instead of creating a new one.",
                    email=tools.email_normalize(email),
                    names=', '.join(same.mapped('display_name'))))
        return super().name_create(name)


class DeskSaleWizardContact(models.TransientModel):
    _inherit = 'fitness.desk.sale.wizard'

    @api.onchange('partner_id')
    def _onchange_partner_shared_email(self):
        """Warn, never block, when her email is also on another contact."""
        partner = self.partner_id
        if not partner or not partner.email_normalized:
            return None
        others = partner._fitness_same_email_contacts()
        if not others:
            return None
        return {'warning': {
            'title': _("Same email on another contact"),
            'message': _(
                "%(email)s is also the email of %(names)s. Check that %(who)s "
                "is the right contact - the sale goes ahead either way.",
                email=partner.email_normalized,
                names=', '.join(others.mapped('display_name')),
                who=partner.display_name),
        }}
