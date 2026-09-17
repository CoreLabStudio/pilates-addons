# -*- coding: utf-8 -*-
"""The three calls a browser makes to register itself for push.

Nothing here reads or writes notifications, bell state or mail. A device
registers, a device unregisters, and the page asks for the public key it
needs in order to do either.
"""
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FitnessPushController(http.Controller):

    @http.route('/my/push/key', type='jsonrpc', auth='user', methods=['POST'])
    def push_key(self, **kw):
        """The studio's VAPID public key, which the browser subscribes against.

        Generated on the first call rather than at install: a database that
        never turns push on never grows a keypair.
        """
        Sub = request.env['fitness.push.subscription'].sudo()
        return {'key': Sub._public_key() or ''}

    @http.route('/my/push/subscribe', type='jsonrpc', auth='user', methods=['POST'])
    def push_subscribe(self, subscription=None, **kw):
        """Register this device for the logged-in user."""
        sub = subscription or {}
        endpoint = (sub.get('endpoint') or '').strip()
        keys = sub.get('keys') or {}
        p256dh, auth = keys.get('p256dh'), keys.get('auth')
        if not (endpoint and p256dh and auth):
            return {'ok': False, 'error': 'incomplete subscription'}
        # The subscription is bound to whoever is logged in on this browser,
        # taken from the session - never from the request body, or one account
        # could register a device against another.
        request.env['fitness.push.subscription'].sudo()._register_device(
            request.env.user.id, endpoint, p256dh, auth,
            user_agent=request.httprequest.headers.get('User-Agent'))
        _logger.info("[PUSH] device registered for user %s", request.env.user.login)
        return {'ok': True}

    @http.route('/my/push/unsubscribe', type='jsonrpc', auth='user', methods=['POST'])
    def push_unsubscribe(self, endpoint=None, **kw):
        """Stop pushing to this device.

        Scoped to the caller's own rows: an endpoint is a long opaque string,
        but it is not a secret, and it must not be usable to silence somebody
        else's phone.
        """
        if not endpoint:
            return {'ok': False}
        rows = request.env['fitness.push.subscription'].sudo().search([
            ('endpoint', '=', endpoint),
            ('user_id', '=', request.env.user.id),
        ])
        rows.write({'active': False})
        return {'ok': True, 'count': len(rows)}
