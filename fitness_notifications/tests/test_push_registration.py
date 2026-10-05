# -*- coding: utf-8 -*-
"""Who may register a device, who may silence one, and when a row retires.

The crypto is covered next door. This is the other half: the three routes a
browser calls, and the one rule that decides whose phone a notification
reaches. None of it can be eyeballed from the UI - a student only ever sees
her own device, so a route that quietly accepted somebody else's would look
perfectly normal from every screen in the app.

The HTTP cases are driven over the wire rather than by calling the
controller, because auth='user' is enforced by the dispatcher and a direct
call would skip the very thing being tested.
"""
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPushRegistration(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.Sub = self.env['fitness.push.subscription']
        portal = self.env.ref('base.group_portal')
        self.alice = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Alice Push', 'login': 'alice.push',
                'email': 'alice.push@example.invalid',
                'password': 'alice-push-pw-1',
                'group_ids': [(6, 0, [portal.id])]})
        self.bob = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Bob Push', 'login': 'bob.push',
                'email': 'bob.push@example.invalid',
                'password': 'bob-push-pw-1',
                'group_ids': [(6, 0, [portal.id])]})

    # ── helpers ──────────────────────────────────────────────────────────
    def _rpc(self, route, params):
        """Call a jsonrpc route and hand back the parsed envelope."""
        res = self.url_open(
            route, data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                                    'params': params}),
            headers={'Content-Type': 'application/json'})
        return res, res.json()

    def _device(self, endpoint, p256dh='pub-key', auth='auth-secret'):
        return {'endpoint': endpoint, 'keys': {'p256dh': p256dh, 'auth': auth}}

    # ── the routes ───────────────────────────────────────────────────────
    def test_an_unauthenticated_browser_cannot_register_a_device(self):
        """No session, no registration - and no row left behind either."""
        before = self.Sub.search_count([])
        res, body = self._rpc('/my/push/subscribe',
                              {'subscription': self._device('https://x/anon')})
        # Odoo answers a jsonrpc call from no session with an error envelope
        # rather than a redirect. What matters is that it is not a success and
        # that nothing was stored.
        self.assertNotIn('result', body,
                         "an anonymous subscribe must not succeed: %s" % body)
        self.assertEqual(
            self.Sub.search_count([]), before,
            "an anonymous subscribe wrote a subscription row")

    def test_a_student_cannot_unsubscribe_another_students_device(self):
        """Bob knowing Alice's endpoint must not let him silence her phone."""
        self.Sub._register_device(self.alice.id, 'https://x/alice-1',
                                  'pub', 'auth')
        self.authenticate('bob.push', 'bob-push-pw-1')
        res, body = self._rpc('/my/push/unsubscribe',
                              {'endpoint': 'https://x/alice-1'})
        self.assertEqual(body.get('result', {}).get('count'), 0,
                         "unsubscribe reached a row that was not the caller's")
        row = self.Sub.with_context(active_test=False).search(
            [('endpoint', '=', 'https://x/alice-1')])
        self.assertTrue(row.active,
                        "Bob switched off Alice's device")
        self.assertEqual(row.user_id, self.alice.partner_id.user_ids[:1] or
                         self.alice, "the row changed hands on an unsubscribe")

    def test_a_student_cannot_list_another_students_devices(self):
        """The model is not readable across students from a portal session."""
        self.Sub._register_device(self.alice.id, 'https://x/alice-2',
                                  'pub', 'auth')
        rows = self.Sub.with_user(self.bob).search([])
        self.assertFalse(
            rows.filtered(lambda r: r.user_id.id == self.alice.id),
            "a portal student could read another student's subscriptions")

    def test_resubscribing_the_same_endpoint_updates_one_row(self):
        """Idempotent per device: a reinstall must not double the pushes."""
        self.Sub._register_device(self.alice.id, 'https://x/same', 'k1', 'a1')
        self.Sub._register_device(self.alice.id, 'https://x/same', 'k2', 'a2')
        rows = self.Sub.with_context(active_test=False).search(
            [('endpoint', '=', 'https://x/same')])
        self.assertEqual(len(rows), 1, "one endpoint grew two rows")
        self.assertEqual(rows.p256dh, 'k2', "the refreshed key was not stored")

    def test_a_shared_device_is_reassigned_and_that_is_deliberate(self):
        """One phone handed to another person follows whoever logged in last.

        Kept on purpose: refusing it would break a studio's shared tablet.
        The cost is written down in _register_device - an authenticated
        student who knew an endpoint could move it - and the reassignment is
        logged so it is at least visible when it happens.
        """
        row = self.Sub._register_device(self.alice.id, 'https://x/shared',
                                        'pub', 'auth')
        self.assertEqual(row.user_id.id, self.alice.id)
        again = self.Sub._register_device(self.bob.id, 'https://x/shared',
                                          'pub', 'auth')
        self.assertEqual(again.id, row.id, "reassignment created a second row")
        self.assertEqual(again.user_id.id, self.bob.id,
                         "the device did not follow the new person")
        self.assertEqual(
            self.Sub.search_count([('user_id', '=', self.alice.id),
                                   ('endpoint', '=', 'https://x/shared')]), 0,
            "the previous owner would still receive this device's pushes")

    def test_a_gone_device_is_retired_rather_than_retried(self):
        """404 and 410 mean the browser is gone for good, so stop pushing.

        Never once fired in production - every registered device is still
        live - so this is the only place the cleanup is exercised at all.
        """
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.push.vapid_public', 'pub-for-test')
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.push.vapid_private', 'priv-for-test')
        row = self.Sub._register_device(self.alice.id, 'https://x/gone',
                                        'pub', 'auth')

        from odoo.addons.fitness_notifications.models import web_push
        real_send = web_push.send
        web_push.send = lambda *a, **kw: (410, 'Gone')
        try:
            sent = self.Sub._notify_user(self.alice.id, 'Title', 'Body')
        finally:
            web_push.send = real_send

        self.assertEqual(sent, 0, "a gone device was counted as delivered")
        row.invalidate_recordset()
        self.assertFalse(row.active, "a 410 did not retire the row")
        self.assertIn('410', row.last_error or '',
                      "the reason the device was retired was not recorded")

    def test_an_error_from_the_push_service_keeps_the_device(self):
        """A 500 is the service having a bad day, not the phone being gone."""
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.push.vapid_public', 'pub-for-test')
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.push.vapid_private', 'priv-for-test')
        row = self.Sub._register_device(self.alice.id, 'https://x/flaky',
                                        'pub', 'auth')

        from odoo.addons.fitness_notifications.models import web_push
        real_send = web_push.send
        web_push.send = lambda *a, **kw: (500, 'Server Error')
        try:
            self.Sub._notify_user(self.alice.id, 'Title', 'Body')
        finally:
            web_push.send = real_send

        row.invalidate_recordset()
        self.assertTrue(
            row.active,
            "a transient failure retired a device that is still reachable")
        self.assertIn('500', row.last_error or '')
