# -*- coding: utf-8 -*-
"""A verification token the studio owns, independent of Odoo's signup token.

Signup used to borrow Odoo's signup token. That token signs a payload
containing the account's latest login timestamp, so **any** login invalidates
**every** outstanding link. It is deliberate replay protection and correct for
what Odoo built it for - but it is hostile to email verification, because the
one thing a person does while waiting for a verification email is log in to
see whether it worked.

Measured on 2026-09-21, on a real account:

    token minted before any login   -> VALID
    student logs in to check        -> original link DEAD
    student presses Resend          -> new link VALID
    student logs in once more       -> resent link DEAD

Resending does not escape the trap, it resets it. Somebody anxious enough to
keep checking can never verify, which is exactly what happened: four accounts
stuck, two needing a script run against production to rescue.

So verification gets its own token. Odoo's signup machinery is left entirely
alone - `signup_cancel()` still works and is still called, so a manual grant
from the back office still kills anything outstanding.

What this keeps from the mechanism it replaces:

  * **single use** - a token is spent the moment it verifies, so a link
    forwarded or left in an inbox cannot be replayed
  * **expiry** - six days, the same as Odoo's signup default
  * **not stored in the clear** - only a hash is kept, so read access to the
    table does not hand anybody a working link
  * **superseded on resend** - asking for a new link retires the old one, so
    there is never more than one live link per account

What it deliberately drops is the login timestamp. Nothing about logging in
should invalidate a verification link; that is the whole bug.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Six days, matching auth_signup.signup.validity.hours' own default so the
# change of mechanism does not quietly change how long a link lives.
VALIDITY_HOURS = 144


class FitnessEmailVerification(models.Model):
    _name = 'fitness.email.verification'
    _description = 'Email verification token'
    _order = 'id desc'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade', index=True,
        string='Account')
    token_hash = fields.Char(
        required=True, index=True, readonly=True,
        help="SHA-256 of the token. The token itself is never stored: it "
             "exists only in the email that was sent.")
    expires_at = fields.Datetime(required=True, readonly=True)
    used_at = fields.Datetime(readonly=True)

    @staticmethod
    def _hash(token):
        return hashlib.sha256((token or '').encode('utf-8')).hexdigest()

    @api.model
    def _issue(self, user):
        """Mint a link for this account and retire any it already had.

        Returns the raw token, which is the only time it exists in readable
        form - the caller puts it straight into the email and forgets it.
        """
        self.sudo().search([
            ('user_id', '=', user.id), ('used_at', '=', False),
        ]).unlink()
        token = secrets.token_urlsafe(32)
        self.sudo().create({
            'user_id': user.id,
            'token_hash': self._hash(token),
            'expires_at': fields.Datetime.now() + timedelta(hours=VALIDITY_HOURS),
        })
        _logger.info("[VERIFY] issued a verification link for %s", user.login)
        return token

    @api.model
    def _redeem(self, token):
        """Spend a token and return its account, or an empty recordset.

        Every failure returns the same empty answer on purpose - expired,
        already used, never existed - so the caller cannot accidentally tell a
        visitor which it was.
        """
        if not token:
            return self.env['res.users']
        # Looked up by hash, then compared again in constant time. The index
        # does the work; compare_digest is there so a lookup that somehow
        # matched loosely still cannot be probed by timing.
        wanted = self._hash(token)
        record = self.sudo().search([('token_hash', '=', wanted)], limit=1)
        if not record or not hmac.compare_digest(record.token_hash, wanted):
            return self.env['res.users']
        if record.used_at:
            _logger.info("[VERIFY] a spent link was presented again for %s",
                         record.user_id.login)
            return self.env['res.users']
        if record.expires_at and record.expires_at < fields.Datetime.now():
            _logger.info("[VERIFY] an expired link was presented for %s",
                         record.user_id.login)
            return self.env['res.users']
        record.sudo().used_at = fields.Datetime.now()
        return record.user_id
