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

CREATING THE CONTACT. A Fitness Studio Manager does not hold Odoo's
"Contact Creation" right, and is not given it (owner, 25 Nov 2026): that
would let her create and edit any contact anywhere. The desk instead
creates the student through fitness_desk_create_student, the one narrow
way in: callable by the manager group (and the system administrator)
only, writing exactly name, email and phone and nothing else, after the
shared-email refusal. A direct create of a contact by the same manager is
still refused by Odoo, as before.
"""
from lxml import etree

from odoo import _, api, models, tools
from odoo.exceptions import AccessError, UserError

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
DESK_CONTACT_FIELDS = ('name', 'email', 'phone')


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
    def fitness_desk_create_student(self, name, email=None, phone=None):
        """Create a student contact from the desk. Returns the new contact.

        Managers only. Writes name, email and phone - DESK_CONTACT_FIELDS -
        and nothing else, so the elevated create cannot be used to set any
        other field of a contact.
        """
        user = self.env.user
        if not (user.has_group(MANAGER_GROUP) or user.has_group('base.group_system')):
            raise AccessError(_("Only a studio manager can create a student from the desk."))
        name = (name or '').strip()
        email = tools.email_normalize(email or '') or False
        if not name and not email:
            raise UserError(_("Give the student a name or an email address."))
        same = self._fitness_active_contacts_with_email(email)
        if same:
            raise UserError(_(
                "%(email)s is already the email of %(names)s. Pick that "
                "contact in Student instead of creating a new one.",
                email=email, names=', '.join(same.mapped('display_name'))))
        vals = {'name': name or email, 'email': email, 'phone': (phone or '').strip() or False}
        assert set(vals) == set(DESK_CONTACT_FIELDS)
        # No default_* from the caller's context: under sudo they would set
        # fields this method does not allow.
        ctx = {k: v for k, v in self.env.context.items() if not k.startswith('default_')}
        return self.sudo().with_context(ctx, fitness_desk_new_contact=False).create(vals).sudo(False)

    @api.model
    def name_create(self, name):
        if self.env.context.get('fitness_desk_new_contact'):
            parsed_name, email = tools.parse_contact_from_email(name or '')
            partner = self.with_context(fitness_desk_new_contact=False).fitness_desk_create_student(
                parsed_name, email=email)
            return partner.id, partner.display_name
        return super().name_create(name)


class DeskSaleWizardContact(models.TransientModel):
    _inherit = 'fitness.desk.sale.wizard'

    @api.model
    def get_views(self, views, options=None):
        """Offer "Create" in the Student field to a manager.

        Odoo marks every relational field can_create="False" for a user who
        cannot create the target model (ir_ui_view, model_access_rights), so
        the web client hid the quick create and the narrow way in
        (fitness_desk_create_student, reached through name_create with this
        field's context) could not be used from the screen at all. Only this
        field, on this dialog, for a manager: everywhere else a manager still
        cannot create a contact.
        """
        res = super().get_views(views, options)
        user = self.env.user
        if not (user.has_group(MANAGER_GROUP) or user.has_group('base.group_system')):
            return res
        for view in res.get('views', {}).values():
            arch = view.get('arch')
            if not arch or 'fitness_desk_new_contact' not in arch:
                continue
            tree = etree.fromstring(arch)
            for node in tree.xpath("//field[@name='partner_id'][contains(@context, 'fitness_desk_new_contact')]"):
                node.set('can_create', 'True')
            view['arch'] = etree.tostring(tree, encoding='unicode')
        return res

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
