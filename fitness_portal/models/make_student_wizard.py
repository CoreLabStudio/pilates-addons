# -*- coding: utf-8 -*-
"""Turn a back-office contact into a student, in one button.

A contact created at the desk is not a student. "Student" means a user
carrying group_fitness_student, and until now that group was only ever
granted by self-signup. So a walk-in entered by hand had no login, did not
appear as a student, and had to be finished off through Settings > Users -
which is how Eli's setup ended up being done by hand, twice.

The part that made the manual route fail is the login. Odoo's own Grant
Portal Access wizard derives it from the email:

    # portal/wizard/portal_wizard.py
    'email': email_normalize(self.email),
    'login': email_normalize(self.email),

so a contact with no email produces no login, and login is required. Some
students genuinely have no email address - see
RUNBOOK-students-without-email.md - and they are exactly the ones a manager
enters by hand. This wizard suggests a username instead, so no address has
to be invented to get past a form.
"""

import logging
import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

STUDENT_GROUP = 'fitness_core.group_fitness_student'


def _slugify_name(name):
    """"Núria Mundó Guixà" -> "nuria.mundo" - a login a person can be told.

    Accents are stripped rather than kept: the studio reads this down a
    phone line, and a login someone cannot type is worse than a plain one.
    Two parts only, because a four-part Catalan name makes an unusable
    login and the number suffix already settles collisions.
    """
    plain = unicodedata.normalize('NFKD', name or '')
    plain = plain.encode('ascii', 'ignore').decode('ascii').lower()
    parts = [p for p in re.split(r'[^a-z0-9]+', plain) if p]
    return '.'.join(parts[:2]) or 'student'


class FitnessMakeStudentWizard(models.TransientModel):
    _name = 'fitness.make.student.wizard'
    _description = 'Make This Person a Student'

    partner_id = fields.Many2one(
        'res.partner', string='Contact', required=True, readonly=True)
    partner_name = fields.Char(related='partner_id.name', readonly=True)
    partner_email = fields.Char(related='partner_id.email', readonly=True)

    login = fields.Char(
        string='Login', required=True,
        help="What she types to sign in. A username when she has no email "
             "address, so nothing has to be invented to create the account.")
    password = fields.Char(
        string='Password', required=True,
        help="Give this to her directly. She can change it once she is in.")
    lang = fields.Selection(
        selection='_lang_selection', string='Language', default='es_ES',
        required=True)

    existing_user_id = fields.Many2one(
        'res.users', compute='_compute_existing', string='Existing Account')
    already_student = fields.Boolean(compute='_compute_existing')
    warning = fields.Char(compute='_compute_existing')

    @api.model
    def _lang_selection(self):
        return [(l.code, l.name)
                for l in self.env['res.lang'].sudo().search([])]

    @api.depends('partner_id')
    def _compute_existing(self):
        student_group = self.env.ref(STUDENT_GROUP, raise_if_not_found=False)
        for rec in self:
            user = self.env['res.users'].sudo().with_context(
                active_test=False).search(
                    [('partner_id', '=', rec.partner_id.id)], limit=1)
            rec.existing_user_id = user
            rec.already_student = bool(
                user and student_group and student_group in user.group_ids)
            if rec.already_student:
                rec.warning = self.env._(
                    "%(name)s already has a student account (%(login)s).",
                    name=rec.partner_id.name, login=user.login)
            elif user:
                rec.warning = self.env._(
                    "%(name)s already has an account (%(login)s). This will "
                    "add the student role to it rather than make a second "
                    "one.", name=rec.partner_id.name, login=user.login)
            else:
                rec.warning = False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_id = res.get('partner_id') or self.env.context.get('active_id')
        if not partner_id:
            return res
        partner = self.env['res.partner'].browse(partner_id)
        res['partner_id'] = partner.id
        res.setdefault('lang', partner.lang or 'es_ES')
        # Her own address when she has one - that is the login she will
        # expect. A username only when there is nothing to use.
        res.setdefault('login', partner.email and partner.email.strip()
                       or self._suggest_login(partner.name))
        return res

    @api.model
    def _suggest_login(self, name):
        """A free login built from the name, with a number only if needed."""
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        base = _slugify_name(name)
        if not Users.search_count([('login', '=', base)]):
            return base
        for n in range(2, 100):
            candidate = '%s%s' % (base, n)
            if not Users.search_count([('login', '=', candidate)]):
                return candidate
        return base

    @api.constrains('login')
    def _check_login_free(self):
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        for rec in self:
            clash = Users.search(
                [('login', '=ilike', (rec.login or '').strip())], limit=1)
            if clash and clash != rec.existing_user_id:
                raise ValidationError(self.env._(
                    "The login %(login)s is already used by %(name)s. "
                    "Choose another one.",
                    login=rec.login, name=clash.name))

    def action_make_student(self):
        self.ensure_one()

        # Checked before any sudo: creating logins is a manager's job, and a
        # student who reached this method some other way must not be able to
        # grant herself an account.
        if not (self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user._is_admin()):
            raise UserError(self.env._(
                "Only a studio manager can create a student account."))

        partner = self.partner_id
        login = (self.login or '').strip()
        if not login:
            raise UserError(self.env._("A login is required."))

        portal = self.env.ref('base.group_portal')
        student = self.env.ref(STUDENT_GROUP, raise_if_not_found=False)
        if not student:
            raise UserError(self.env._(
                "The student group is missing from this database."))

        user = self.existing_user_id
        if user:
            # Adding the role to an account she already has, rather than a
            # second account on the same person.
            user.sudo().write({
                'group_ids': [(4, portal.id), (4, student.id)],
                'active': True,
            })
            if self.password:
                user.sudo().write({'password': self.password})
            _logger.info("[STUDENT] %s given the student role on %s",
                         partner.display_name, user.login)
        else:
            # No 'name' and no 'email' in these values. res.users _inherits
            # from res.partner, so any partner field passed alongside an
            # explicit partner_id is written through to - or worse, used to
            # build - a partner, and the account ends up attached to one
            # that is not the contact the manager was looking at. The
            # contact already carries her name and whatever address she has;
            # nothing here needs to restate them.
            user = self.env['res.users'].sudo().with_context(
                no_reset_password=True).create({
                    'login': login,
                    'password': self.password,
                    'lang': self.lang,
                    'partner_id': partner.id,
                    'group_ids': [(6, 0, [portal.id, student.id])],
                })
            if user.partner_id != partner:
                raise UserError(self.env._(
                    "The account was created against the wrong contact. "
                    "Nothing has been saved."))
            _logger.info("[STUDENT] created %s for %s (email=%s)",
                         login, partner.display_name,
                         partner.email or 'none')

        partner.sudo().message_post(body=self.env._(
            "Made a student by %(user)s. Login: %(login)s",
            user=self.env.user.name, login=user.login))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users',
            'res_id': user.id,
            'view_mode': 'form',
            'target': 'current',
        }
