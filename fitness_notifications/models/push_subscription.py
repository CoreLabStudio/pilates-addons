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
            existing.write(vals)
            return existing
        vals['endpoint'] = endpoint
        return self.sudo().create(vals)

    # ── sending ────────────────────────────────────────────────────────────

    @api.model
    def _notify_user(self, user_id, title, body=None, url=None, tag=None):
        """Push one message to every device a user has registered.

        Never raises: a delivery problem must not roll back the booking, the
        cancellation or the bell notification that caused it.
        """
        if not user_id:
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
