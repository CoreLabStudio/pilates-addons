# -*- coding: utf-8 -*-
"""Web Push: one row per device, and the keys that let us talk to it.

A push subscription belongs to a browser on a device, not to a person: the
same student on a phone and a laptop is two rows, and reinstalling the app
makes a third and silently retires the first. So the endpoint is the identity
here, not the user.

Nothing in this file touches the bell, the notification records or the
emails. Push is a third delivery of text that has already been written and
already been stored.
"""
import base64
import json
import logging

from odoo import api, fields, models

from . import web_push

_logger = logging.getLogger(__name__)

# Where the keypair lives. Generated once, on first use, and never rotated
# automatically: every existing subscription is signed against the public key
# and would be invalidated by a new one.
PARAM_PUBLIC = 'fitness.push.vapid_public'
PARAM_PRIVATE = 'fitness.push.vapid_private'
PARAM_SUBJECT = 'fitness.push.vapid_subject'
DEFAULT_SUBJECT = 'mailto:info@corelabstudio.es'

# Who may still be pushed to once Odoo has marked this database as a copy of
# production. Comma-separated user ids; empty means nobody, which is the
# default and the safe answer. ir.config_parameter is cached per process, so
# a change made from the UI is picked up, but one written from another
# process - a shell, a test - needs the server restarted or the registry
# signalled before the running site sees it.
PARAM_TEST_USERS = 'fitness.push.test_user_ids'


class FitnessPushSubscription(models.Model):
    _name = 'fitness.push.subscription'
    _description = 'Web Push Subscription (one per device)'
    _order = 'create_date desc'
    _rec_name = 'endpoint'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    endpoint = fields.Char(required=True, index=True)
    p256dh = fields.Char(required=True, help="The device's public key.")
    auth = fields.Char(required=True, help="The device's auth secret.")
    user_agent = fields.Char(help="Whatever the browser called itself when it subscribed.")
    active = fields.Boolean(default=True, index=True)
    last_sent = fields.Datetime()
    last_error = fields.Char()

    # The push service hands out one endpoint per browser installation, so
    # re-subscribing must update the row rather than grow a second one -
    # otherwise every reinstall doubles the notifications. Declared the Odoo 19
    # way: _sql_constraints is ignored now, and silently, so the index simply
    # never existed.
    _endpoint_uniq = models.Constraint(
        'UNIQUE (endpoint)', 'This device is already registered.')

    # ── keys ───────────────────────────────────────────────────────────────

    @api.model
    def _vapid_keys(self, generate=True):
        """The studio's keypair, generating one the first time it is asked for."""
        icp = self.env['ir.config_parameter'].sudo()
        pub, priv = icp.get_param(PARAM_PUBLIC), icp.get_param(PARAM_PRIVATE)
        if pub and priv:
            return pub, priv
        if not generate:
            return None, None
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
        except ImportError:                                   # pragma: no cover
            _logger.warning("[PUSH] cryptography is unavailable; cannot make VAPID keys")
            return None, None

        key = ec.generate_private_key(ec.SECP256R1())
        raw_priv = key.private_numbers().private_value.to_bytes(32, 'big')
        raw_pub = key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)

        def b64(raw):
            return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')

        pub, priv = b64(raw_pub), b64(raw_priv)
        icp.set_param(PARAM_PUBLIC, pub)
        icp.set_param(PARAM_PRIVATE, priv)
        _logger.info("[PUSH] generated a VAPID keypair for this database")
        return pub, priv

    @api.model
    def _public_key(self):
        return self._vapid_keys()[0]

    # ── registration ───────────────────────────────────────────────────────

    @api.model
    def _register_device(self, user_id, endpoint, p256dh, auth, user_agent=None):
        """Store or refresh one device. Returns the row."""
        existing = self.sudo().with_context(active_test=False).search(
            [('endpoint', '=', endpoint)], limit=1)
        vals = {
            'user_id': user_id,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': (user_agent or '')[:200],
            'active': True,
            'last_error': False,
        }
        if existing:
            # A shared device handed to a different person re-subscribes with
            # the same endpoint. Reassigning is what stops the previous owner
            # receiving the new one's notifications.
            #
            # DELIBERATE, and knowingly a trade. The endpoint arrives from the
            # browser while the user comes from the session, so an
            # authenticated student who knew another student's endpoint could
            # move that device onto her own account and silence the original
            # owner. An endpoint is opaque and is never printed by anything
            # here, but it is not a secret. Refusing the reassignment would
            # close that and break the shared phone, which is a real thing a
            # studio does; the decision was to keep it and make it visible.
            #
            # Hence the log line - ids only, never the endpoint, because a log
            # that carried one would hand over the very capability the rest of
            # this file is careful not to print.
            if existing.user_id.id != user_id:
                _logger.info(
                    "[PUSH] device %s reassigned from user %s to user %s",
                    existing.id, existing.user_id.id, user_id)
            existing.write(vals)
            return existing
        vals['endpoint'] = endpoint
        return self.sudo().create(vals)

    # ── copies of production ───────────────────────────────────────────────

    @api.model
    def _is_neutralized(self):
        """Is this a copy of production that Odoo has neutralized?

        odoo.sh runs base/data/neutralize.sql when it builds staging, which
        sets database.is_neutralized, switches the crons off and points mail
        at a dead server. It also clears Odoo's OWN push: the
        mail.web_push_* keys and every row of mail_push_device.

        It does not clear ours. fitness.push.* and fitness.push.subscription
        appear in no neutralize.sql anywhere in Odoo, and this module ships
        none - so a copy of production arrives holding real students'
        endpoints, and the push service routes by endpoint without caring
        which database asked.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'database.is_neutralized')
        return str(raw or '').strip().lower() in ('1', 't', 'true', 'yes')

    @api.model
    def _push_test_user_ids(self):
        """Who may still be pushed to on a neutralized copy.

        Returns a set of ids, or None when the parameter cannot be read as a
        list. None means suppress everything: a typo in this setting must
        not be the reason a real student's phone rings from staging.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_TEST_USERS) or ''
        out = set()
        for piece in raw.split(','):
            piece = piece.strip()
            if not piece:
                continue            # spaces and a trailing comma are fine
            if not piece.isdigit():
                _logger.warning(
                    "[PUSH] %s contains %r, which is not a user id; every "
                    "push on this neutralized database is suppressed until "
                    "it is fixed", PARAM_TEST_USERS, piece[:32])
                return None
            out.add(int(piece))
        return out

    @api.model
    def _may_push_to(self, user_id):
        """Whether a push to this user may leave a neutralized database."""
        if not self._is_neutralized():
            return True             # production and local dev: unchanged
        allowed = self._push_test_user_ids()
        if allowed is None:
            _logger.info(
                "[PUSH] push suppressed on a neutralized database for user "
                "%s; %s could not be read as a list of ids",
                user_id, PARAM_TEST_USERS)
            return False
        if user_id in allowed:
            return True
        # INFO, never ERROR: odoo.sh grades a build on its ERROR lines, and
        # a guard doing its job is not a failure.
        _logger.info(
            "[PUSH] push suppressed on a neutralized database for user %s; "
            "add the id to %s to test", user_id, PARAM_TEST_USERS)
        return False

    # ── sending ────────────────────────────────────────────────────────────

    @api.model
    def _notify_user(self, user_id, title, body=None, url=None, tag=None):
        """Push one message to every device a user has registered.

        Never raises: a delivery problem must not roll back the booking, the
        cancellation or the bell notification that caused it.

        Only the push is gated. The caller has already written the in-app
        notification by the time this runs, so the bell is unaffected on a
        neutralized database - and email is already dead there, because
        neutralization points the mail server at nothing.
        """
        if not user_id:
            return 0
        if not self._may_push_to(user_id):
            return 0
        subs = self.sudo().search([('user_id', '=', user_id), ('active', '=', True)])
        if not subs:
            return 0
        pub, priv = self._vapid_keys(generate=False)
        if not (pub and priv):
            _logger.info("[PUSH] no VAPID keypair yet; nothing sent")
            return 0
        subject = (self.env['ir.config_parameter'].sudo().get_param(PARAM_SUBJECT)
                   or DEFAULT_SUBJECT)
        payload = json.dumps({
            'title': title or '',
            'body': body or '',
            'url': url or '/my/home',
            'tag': tag or 'corelab',
        })
        sent = 0
        for sub in subs:
            try:
                status, detail = web_push.send(
                    sub.endpoint, sub.p256dh, sub.auth, payload,
                    private_key_b64=priv, public_key_b64=pub, subject=subject)
                if status in (200, 201, 202):
                    sub.write({'last_sent': fields.Datetime.now(), 'last_error': False})
                    sent += 1
                elif status in (404, 410):
                    # The push service saying this device is gone for good -
                    # uninstalled, or permission revoked. Keep the row for the
                    # audit trail but stop trying.
                    sub.write({'active': False, 'last_error': 'gone (%s)' % status})
                    _logger.info("[PUSH] device retired (%s) for user %s", status, user_id)
                else:
                    sub.write({'last_error': ('HTTP %s %s' % (status, detail))[:200]})
                    _logger.warning("[PUSH] send refused for user %s: HTTP %s %s",
                                    user_id, status, detail)
            except Exception as exc:
                sub.write({'last_error': str(exc)[:200]})
                _logger.warning("[PUSH] send error for user %s: %s", user_id, exc)
        return sent
