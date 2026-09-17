# -*- coding: utf-8 -*-
"""Push: the encryption, the language, and what it must not disturb.

The encryption is the part that cannot be eyeballed - a wrong key derivation
produces a body the phone silently discards, with no error anywhere on the
server. So it is verified by decrypting it the way a browser would.
"""
import json

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_notifications.models import web_push


def _fake_device():
    """A browser's half of the key exchange."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b'0123456789abcdef'                      # 16 bytes, as a browser sends
    return priv, web_push.b64url_encode(pub_raw), web_push.b64url_encode(auth), auth


@tagged("post_install", "-at_install")
class TestWebPushCrypto(TransactionCase):

    longMessage = False

    def test_the_phone_can_decrypt_what_we_send(self):
        """Round-trip through the real key agreement.

        This is the whole ballgame: get the HKDF info strings or the record
        framing wrong and the push service still returns 201, while the phone
        shows nothing at all.
        """
        priv, pub_b64, auth_b64, auth_raw = _fake_device()
        payload = json.dumps({"title": "Clase cancelada", "body": "Tu crédito ha vuelto."})
        body = web_push.encrypt(payload, pub_b64, auth_b64)
        back = web_push.decrypt(body, priv, auth_raw)
        self.assertEqual(json.loads(back.decode("utf-8"))["title"], "Clase cancelada")

    def test_accents_survive_the_round_trip(self):
        """Spanish and Catalan are the point; a mangled accent is a failure."""
        priv, pub_b64, auth_b64, auth_raw = _fake_device()
        payload = json.dumps({"body": "La teva classe s'ha mogut a dimecres · 08:00"},
                             ensure_ascii=False)
        body = web_push.encrypt(payload, pub_b64, auth_b64)
        back = json.loads(web_push.decrypt(body, priv, auth_raw).decode("utf-8"))
        self.assertIn("s'ha mogut", back["body"])
        self.assertIn("·", back["body"])

    def test_every_message_uses_a_fresh_salt(self):
        """Two identical messages must not produce identical bodies."""
        _priv, pub_b64, auth_b64, _auth = _fake_device()
        a = web_push.encrypt("same", pub_b64, auth_b64)
        b = web_push.encrypt("same", pub_b64, auth_b64)
        self.assertNotEqual(a, b, "the salt or the ephemeral key is being reused")

    def test_the_body_is_framed_the_way_the_spec_says(self):
        """16-byte salt, 4-byte record size, 1-byte key length, 65-byte key."""
        _priv, pub_b64, auth_b64, _auth = _fake_device()
        body = web_push.encrypt("x", pub_b64, auth_b64)
        self.assertEqual(body[20], 65, "the ephemeral key length byte is wrong")
        self.assertGreater(len(body), 16 + 4 + 1 + 65)

    def test_the_vapid_header_is_a_signed_jwt_for_this_host(self):
        """The push service rejects a token whose audience is not its own origin."""
        Sub = self.env['fitness.push.subscription']
        pub, priv = Sub._vapid_keys()
        headers = web_push.vapid_headers(
            'https://fcm.googleapis.com/fcm/send/abc123', priv, pub, 'mailto:x@y.z')
        self.assertTrue(headers['Authorization'].startswith('vapid t='))
        self.assertIn('k=%s' % pub, headers['Authorization'])
        token = headers['Authorization'].split('t=')[1].split(',')[0]
        header_b64, claims_b64, signature_b64 = token.split('.')
        claims = json.loads(web_push.b64url_decode(claims_b64))
        self.assertEqual(claims['aud'], 'https://fcm.googleapis.com')
        self.assertEqual(claims['sub'], 'mailto:x@y.z')
        self.assertEqual(len(web_push.b64url_decode(signature_b64)), 64,
                         "ES256 wants the raw r||s pair, not a DER signature")
        self.assertEqual(headers['Content-Encoding'], 'aes128gcm')


@tagged("post_install", "-at_install")
class TestPushSubscriptions(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = cls.env['res.users'].create({
            'name': 'Push Student', 'login': 'push.student@example.invalid',
        })
        cls.other = cls.env['res.users'].create({
            'name': 'Other Student', 'login': 'push.other@example.invalid',
        })
        cls.Sub = cls.env['fitness.push.subscription']

    def test_resubscribing_updates_the_device_rather_than_adding_one(self):
        """Every reinstall would otherwise double the notifications."""
        for _ in range(3):
            self.Sub._register_device(self.student.id, 'https://push.example/abc', 'k1', 'a1')
        rows = self.Sub.with_context(active_test=False).search(
            [('endpoint', '=', 'https://push.example/abc')])
        self.assertEqual(len(rows), 1)

    def test_a_shared_device_follows_whoever_logged_in_last(self):
        """The old owner must stop receiving the new one's notifications."""
        self.Sub._register_device(self.student.id, 'https://push.example/shared', 'k', 'a')
        self.Sub._register_device(self.other.id, 'https://push.example/shared', 'k', 'a')
        row = self.Sub.search([('endpoint', '=', 'https://push.example/shared')])
        self.assertEqual(row.user_id, self.other)

    def test_sending_to_someone_with_no_device_is_not_an_error(self):
        self.assertEqual(self.Sub._notify_user(self.student.id, 'hi'), 0)

    def test_a_dead_push_service_never_breaks_the_notification(self):
        """The endpoint is unreachable; the call must still return quietly.

        This is the guarantee that matters: push failing must not roll back
        the booking or lose the bell notification that triggered it.
        """
        self.Sub._register_device(self.student.id, 'https://127.0.0.1:9/gone',
                           web_push.b64url_encode(b'\x04' + b'\x01' * 64),
                           web_push.b64url_encode(b'0123456789abcdef'))
        self.Sub._vapid_keys()
        sent = self.Sub._notify_user(self.student.id, 'title', body='body')
        self.assertEqual(sent, 0)
        row = self.Sub.search([('endpoint', '=', 'https://127.0.0.1:9/gone')])
        self.assertTrue(row.last_error, "the failure should be recorded on the device")


@tagged("post_install", "-at_install")
class TestPushLeavesTheBellAlone(TransactionCase):

    longMessage = False

    def test_the_bell_record_is_still_created_when_push_is_impossible(self):
        """No keys, no devices, no pywebpush - the bell must be untouched."""
        user = self.env['res.users'].create({
            'name': 'Bell Only', 'login': 'bell.only@example.invalid',
        })
        before = self.env['fitness.notification'].search_count([('user_id', '=', user.id)])
        self.env['fitness.notification']._create_for_user(
            user.id, 'booking_confirmed', 'Reserva confirmada', 'Nos vemos en clase.',
            action_url='/my/schedule')
        after = self.env['fitness.notification'].search([('user_id', '=', user.id)])
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[0].title, 'Reserva confirmada')
        self.assertEqual(after[0].action_url, '/my/schedule')

    def test_push_carries_exactly_what_the_bell_stored(self):
        """One text, two channels - so the phone cannot say something else.

        The callers build that text in the recipient's own language, which is
        what makes the push language-correct without this layer knowing
        anything about languages.
        """
        captured = {}
        Sub = self.env['fitness.push.subscription']
        original = type(Sub)._notify_user

        def spy(self_model, user_id, title, body=None, url=None, tag=None):
            captured.update(user_id=user_id, title=title, body=body, url=url, tag=tag)
            return 0

        type(Sub)._notify_user = spy
        try:
            user = self.env['res.users'].create({
                'name': 'Spy', 'login': 'push.spy@example.invalid'})
            self.env['fitness.notification']._create_for_user(
                user.id, 'class_rescheduled', 'La teva classe ha canviat',
                "S'ha mogut a dimecres.", action_url='/my/schedule')
        finally:
            type(Sub)._notify_user = original

        self.assertEqual(captured['title'], 'La teva classe ha canviat')
        self.assertEqual(captured['body'], "S'ha mogut a dimecres.")
        self.assertEqual(captured['url'], '/my/schedule')
        self.assertEqual(captured['tag'], 'class_rescheduled')
