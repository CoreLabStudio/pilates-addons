# -*- coding: utf-8 -*-
"""The automatic join, driven through the real verification endpoint.

Everything else about this feature is tested at the model. This file
exists because the rule that matters most - a duplicate is joined ONLY
when she proves the address is hers, by following OUR single-use link -
lives in the control flow of one HTTP endpoint, and a model test cannot
see it.

The distinction is not academic. /corelab/verify-email accepts two
tokens. Ours is minted by fitness.email.verification._issue, emailed to
her, and spent on use. Odoo's signup token is also minted whenever a
manager grants portal access from the back office, and a link a manager
can paste anywhere says nothing about who reads that mailbox. Joining
on the second would mean a studio admin could fuse two customer records
by sending somebody a welcome email.

Reverting the guard that separates them broke no test until this file
was written.
"""
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_portal.models.res_partner_duplicate import (
    AUTOJOIN_PARAM,
)

STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestVerificationJoinHttp(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.Log = self.env['fitness.duplicate.join.log'].sudo()
        self.Verif = self.env['fitness.email.verification'].sudo()
        # /corelab/verify-email reads an mv_lang cookie and defaults to
        # es_ES, then calls request.update_context(lang=...). env.lang
        # RAISES "Invalid language code" for a language that is not
        # active, so on a fresh install - where es_ES exists but is
        # inactive - the endpoint answers 422 and verification is
        # impossible. Production has Spanish active, so this is latent
        # there; it is activated here so these tests exercise the join
        # rather than that fault. See the release notes.
        self.env['res.lang'].sudo()._activate_lang('es_ES')

    # -- fixtures ----------------------------------------------------
    def _pair(self, tag, name='Marta Munoz'):
        """A desk contact holding only a trial, plus an UNVERIFIED signup.

        Unverified means the account does not yet carry
        group_fitness_student - that group is what verify_email grants,
        so holding it already would mean she had been through this door
        before.
        """
        email = 'vj.%s@example.invalid' % tag
        desk = self.env['res.partner'].sudo().create(
            {'name': name, 'email': email})
        self.env['fitness.trial.request'].sudo().create({
            'name': name, 'email': email, 'partner_id': desk.id})
        user = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': name, 'login': email, 'email': email,
                'password': 'vj-pw-123456',
                'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        self.assertFalse(
            user.has_group(STUDENT_GROUP),
            "the fixture account is already verified, so this proves "
            "nothing about verification")
        return desk, user

    def _our_token(self, user):
        return self.Verif._issue(user)

    def _odoo_signup_token(self, user):
        """Odoo's own signup token - what a back-office grant mints.

        res.partner.signup_token was removed in Odoo 19; the token is
        generated on demand by _generate_signup_token() once
        signup_prepare() has set a signup_type.
        """
        partner = user.partner_id.sudo()
        partner.signup_prepare()
        partner.invalidate_recordset()
        return partner._generate_signup_token()

    def _visit(self, token):
        self.env.flush_all()
        return self.url_open('/corelab/verify-email?token=%s' % token,
                             timeout=30)

    def _joined(self, desk, user):
        """Did the two contacts become one, with the desk one surviving?"""
        user.invalidate_recordset()
        return bool(desk.exists()) and user.partner_id.id == desk.id

    # == 1. our token, switch on -> it joins =========================
    def test_our_token_joins_the_duplicate(self):
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        desk, user = self._pair('ourtoken')
        new_partner = user.partner_id
        token = self._our_token(user)

        res = self._visit(token)
        self.assertEqual(res.status_code, 200)

        self.assertTrue(
            self._joined(desk, user),
            "following her own verification link did not join the "
            "duplicate, so she signs in to an empty account")
        self.assertFalse(
            new_partner.exists(),
            "the second contact is still there after the join")
        self.assertTrue(
            user.has_group(STUDENT_GROUP),
            "verification did not grant the student group")

        row = self.Log.search([('merged_ref', '=', new_partner.id)])
        self.assertTrue(row, "the join left no audit record")
        self.assertTrue(
            row.was_automatic,
            "a join the system made on its own is recorded as a manual "
            "merge, so the audit cannot tell them apart")
        self.assertFalse(row.merged_by_id)
        self.assertEqual(row.survivor_id, desk)
        self.assertEqual(
            row.trials_moved, 0,
            "the audit counts what moved OFF the contact that was "
            "deleted. The desk contact holds the history and is chosen "
            "as the survivor, so nothing moves and the counts are zero "
            "- the record's value here is the names and the old id, not "
            "the tallies. A non-zero count would mean the LOGIN side "
            "held the history and the survivor choice had gone the "
            "other way.")
        self.assertEqual(
            self.env['fitness.trial.request'].sudo().search_count(
                [('partner_id', '=', desk.id)]), 1,
            "her trial no longer hangs off the surviving contact, so the "
            "history this join exists to rescue has been lost")

    # == 2. Odoo's signup token -> never joins =======================
    def test_odoos_signup_token_never_joins_with_the_switch_on(self):
        """A manager's grant is not her proving anything."""
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        desk, user = self._pair('signupon')
        new_partner = user.partner_id
        before = self.Log.search_count([])

        res = self._visit(self._odoo_signup_token(user))
        self.assertEqual(res.status_code, 200)

        self.assertTrue(
            new_partner.exists() and desk.exists(),
            "Odoo's signup token joined two contacts. A manager granting "
            "portal access would silently merge customer records.")
        self.assertEqual(self.Log.search_count([]), before,
                         "a join was recorded for a signup-token visit")

    def test_odoos_signup_token_never_joins_with_the_switch_off(self):
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '0')
        desk, user = self._pair('signupoff')
        new_partner = user.partner_id
        self._visit(self._odoo_signup_token(user))
        self.assertTrue(new_partner.exists() and desk.exists())

    # == 3. our token, switch off -> nothing joins ===================
    def test_our_token_does_nothing_while_the_switch_is_off(self):
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '0')
        desk, user = self._pair('switchoff')
        new_partner = user.partner_id
        before = self.Log.search_count([])

        res = self._visit(self._our_token(user))
        self.assertEqual(res.status_code, 200)

        self.assertTrue(
            new_partner.exists() and desk.exists(),
            "the duplicate was joined while the feature was switched "
            "off, so shipping it off does not make it safe")
        self.assertEqual(self.Log.search_count([]), before)
        self.assertTrue(
            user.has_group(STUDENT_GROUP),
            "verification itself must still work with the switch off")

    # == 4. the back office never joins ==============================
    def test_the_back_office_student_grant_never_joins(self):
        """Granting the student role is a studio decision about access.

        It says nothing about who controls the mailbox, so it must not
        drag a merge along with it - even with the switch on.
        """
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        desk, user = self._pair('backoffice')
        new_partner = user.partner_id
        before = self.Log.search_count([])

        user.sudo().write(
            {'group_ids': [(4, self.env.ref(STUDENT_GROUP).id)]})
        user.partner_id.sudo().signup_cancel()

        self.assertTrue(
            new_partner.exists() and desk.exists(),
            "granting the student group from the back office joined two "
            "contacts")
        self.assertEqual(self.Log.search_count([]), before)
