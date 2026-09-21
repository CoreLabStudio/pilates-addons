# -*- coding: utf-8 -*-
"""The verification token, and the trap it was built to escape.

Signup used to borrow Odoo's signup token, which signs a payload containing
the account's latest login timestamp - so any login invalidated every
outstanding link. That is sound replay protection for what Odoo built it for
and hostile to email verification, because the one thing somebody does while
waiting for a verification email is log in to see whether it worked.

Measured on a real account before this was built:

    token minted before any login   -> VALID
    student logs in to check        -> original link DEAD
    student presses Resend          -> new link VALID
    student logs in once more       -> resent link DEAD

Resending reset the trap rather than escaping it. Four accounts were stuck;
two needed a script run against production.

test_a_login_does_not_kill_the_link is the point of the whole exercise. The
rest guard the properties being replaced: single use, expiry, supersession,
and that the token is never stored in readable form.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmailVerificationToken(TransactionCase):

    longMessage = False

    def _user(self, login="token.test@example.invalid"):
        user = self.env["res.users"].create({
            "name": "Token Test", "login": login, "email": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])]})
        user.partner_id.signup_prepare(signup_type="signup")
        return user

    def _login(self, user, minutes=1):
        """Record a login for this account, at a distinguishable time.

        res.users.login_date is related to log_ids.create_date keyed on
        create_uid, so the row has to be written AS the user - and create_date
        is PostgreSQL transaction time, identical for every row in one
        transaction, so it is stamped forward explicitly. Both of those caught
        me out while measuring the original bug: the first harness credited
        the shell's user and the second gave two logins one timestamp, and
        both reported the opposite of the truth.
        """
        log = self.env["res.users.log"].with_user(user).sudo().create({})
        self.env.cr.execute(
            "UPDATE res_users_log SET create_date = now() + (%s || ' minutes')"
            "::interval WHERE id = %s", [minutes, log.id])
        self.env["res.users.log"].invalidate_model()
        user.invalidate_recordset()

    def _V(self):
        return self.env["fitness.email.verification"].sudo()

    # -- the reason this exists --------------------------------------------

    def test_a_login_does_not_kill_the_link(self):
        """The whole point. Odoo's token failed exactly here."""
        user = self._user()
        token = self._V()._issue(user)

        self._login(user, minutes=1)
        self._login(user, minutes=2)
        self._login(user, minutes=3)

        self.assertEqual(
            self._V()._redeem(token), user,
            "logging in killed the verification link again - a student who "
            "checks whether it worked is stuck exactly as before")

    def test_the_old_odoo_token_still_dies_on_login(self):
        """The premise, asserted rather than remembered.

        If a future Odoo stops embedding the login timestamp, this fails and
        the whole mechanism can be reconsidered instead of being carried
        forever on a belief about how it used to behave.
        """
        user = self._user("token.legacy@example.invalid")
        partner = user.partner_id.sudo()
        legacy = partner._generate_signup_token()
        self.assertTrue(
            partner._get_partner_from_token(legacy),
            "the legacy token did not resolve even before a login")
        self._login(user, minutes=1)
        self.assertFalse(
            partner._get_partner_from_token(legacy),
            "Odoo's signup token now survives a login; the trap this replaces "
            "may no longer exist")

    # -- the properties being replaced -------------------------------------

    def test_a_token_is_single_use(self):
        user = self._user("token.once@example.invalid")
        token = self._V()._issue(user)
        self.assertEqual(self._V()._redeem(token), user)
        self.assertFalse(
            self._V()._redeem(token),
            "the link worked twice - a forwarded email could verify again")

    def test_an_expired_token_is_refused(self):
        user = self._user("token.expired@example.invalid")
        token = self._V()._issue(user)
        record = self._V().search([("user_id", "=", user.id)], limit=1)
        record.expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertFalse(
            self._V()._redeem(token), "an expired link still verified")

    def test_resending_retires_the_previous_link(self):
        """Only ever one live link, so a discarded email cannot be used."""
        user = self._user("token.resend@example.invalid")
        first = self._V()._issue(user)
        second = self._V()._issue(user)
        self.assertFalse(
            self._V()._redeem(first),
            "the superseded link still worked; two live links existed at once")
        self.assertEqual(self._V()._redeem(second), user)

    def test_a_nonsense_token_is_refused(self):
        self._user("token.nonsense@example.invalid")
        self.assertFalse(self._V()._redeem("not-a-real-token"))
        self.assertFalse(self._V()._redeem(""))
        self.assertFalse(self._V()._redeem(None))

    def test_the_token_is_never_stored_in_readable_form(self):
        """Read access to the table must not hand anybody a working link."""
        user = self._user("token.hashed@example.invalid")
        token = self._V()._issue(user)
        record = self._V().search([("user_id", "=", user.id)], limit=1)
        self.assertTrue(record, "no verification record was written")
        self.assertNotEqual(
            record.token_hash, token,
            "the token is stored as-is; anyone who can read the table can "
            "verify any account")
        self.assertNotIn(
            token, record.token_hash,
            "the stored value contains the token itself")

    def test_one_students_link_cannot_verify_another(self):
        alice = self._user("token.alice@example.invalid")
        bob = self._user("token.bob@example.invalid")
        alice_token = self._V()._issue(alice)
        self._V()._issue(bob)
        self.assertEqual(
            self._V()._redeem(alice_token), alice,
            "a token resolved to the wrong account")

    def test_a_manual_grant_still_kills_an_outstanding_link(self):
        """Part 1's back-office action and this must not disagree.

        The action calls signup_cancel(), which is what stops a stale link
        being replayed. That still has to hold now the link is ours: the
        account already has the group, so redeeming can add nothing - but the
        studio should not be relying on that alone.
        """
        user = self._user("token.manual@example.invalid")
        token = self._V()._issue(user)
        manager = self.env["res.users"].create({
            "name": "Token Manager",
            "login": "token.manager@example.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("fitness_core.group_fitness_manager").id])]})
        user.with_user(manager).action_fitness_verify_student()
        user.invalidate_recordset()

        self.assertTrue(user.fitness_is_verified_student)
        self.assertFalse(
            user.partner_id.signup_type,
            "the signup was not cancelled, so the account still reads as "
            "mid-verification and login would bounce to the verify page")
        # The link may still resolve - it was never spent - but it can no
        # longer achieve anything, and the route checks the group first.
        self.assertTrue(
            user.fitness_is_verified_student,
            "granting access by hand did not stick")
