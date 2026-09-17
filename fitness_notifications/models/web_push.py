# -*- coding: utf-8 -*-
"""Web Push, written against the cryptography Odoo already ships.

Why not pywebpush: it depends on py-vapid, which requires cryptography>=46,
and Odoo pins cryptography==42.0.8 because pyOpenSSL needs <43. Installing it
upgrades cryptography and breaks pyOpenSSL - verified, not assumed. A push
feature is not worth putting the production container's TLS stack at risk, so
the two specs it needs are implemented here instead:

  RFC 8291 - message encryption (aes128gcm)
  RFC 8292 - voluntary application server identification (VAPID, ES256)

Both are short and fully specified. The encryption is covered by a round-trip
test that decrypts what this produces, which is the part that would otherwise
fail silently on a real phone.
"""
import base64
import json
import os
import struct
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONTENT_ENCODING = 'aes128gcm'
RECORD_SIZE = 4096
VAPID_TTL = 12 * 3600          # the spec caps this at 24h; 12 is comfortable


def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def b64url_decode(text):
    if isinstance(text, str):
        text = text.encode('ascii')
    return base64.urlsafe_b64decode(text + b'=' * (-len(text) % 4))


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length,
                salt=salt, info=info).derive(ikm)


def _raw_public(public_key):
    return public_key.public_bytes(serialization.Encoding.X962,
                                   serialization.PublicFormat.UncompressedPoint)


def encrypt(payload, client_public_b64, client_auth_b64):
    """Encrypt one message for one device. Returns the request body.

    The layout is the aes128gcm one: everything the recipient needs to derive
    the key travels in the header of the body itself, which is why no extra
    HTTP headers describe the keys.
    """
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    ua_public_raw = b64url_decode(client_public_b64)
    auth_secret = b64url_decode(client_auth_b64)

    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), ua_public_raw)
    as_private = ec.generate_private_key(ec.SECP256R1())
    as_public_raw = _raw_public(as_private.public_key())

    shared = as_private.exchange(ec.ECDH(), ua_public)
    # The auth secret is the salt here, and the two public keys are bound into
    # the info string - that is what ties the key to this exact pair of
    # endpoints rather than to the message.
    prk = _hkdf(auth_secret, shared,
                b'WebPush: info\x00' + ua_public_raw + as_public_raw, 32)

    salt = os.urandom(16)
    cek = _hkdf(salt, prk, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, prk, b'Content-Encoding: nonce\x00', 12)

    # 0x02 marks the final record. Everything fits in one record here: these
    # are notification titles, not documents.
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)

    return (salt
            + struct.pack('!L', RECORD_SIZE)
            + struct.pack('!B', len(as_public_raw))
            + as_public_raw
            + ciphertext)


def decrypt(body, receiver_private_key, auth_secret):
    """Undo encrypt(). Only used by the tests - a real client does this."""
    salt, body = body[:16], body[16:]
    body = body[4:]                                   # record size
    idlen, body = body[0], body[1:]
    as_public_raw, ciphertext = body[:idlen], body[idlen:]
    as_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), as_public_raw)
    shared = receiver_private_key.exchange(ec.ECDH(), as_public)
    ua_public_raw = _raw_public(receiver_private_key.public_key())
    prk = _hkdf(auth_secret, shared,
                b'WebPush: info\x00' + ua_public_raw + as_public_raw, 32)
    cek = _hkdf(salt, prk, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, prk, b'Content-Encoding: nonce\x00', 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plain.rstrip(b'\x02')


def vapid_headers(endpoint, private_key_b64, public_key_b64, subject):
    """The Authorization header that identifies this studio to the push service."""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    audience = '%s://%s' % (parsed.scheme, parsed.netloc)

    header = b64url_encode(json.dumps(
        {'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    claims = b64url_encode(json.dumps(
        {'aud': audience, 'exp': int(time.time()) + VAPID_TTL, 'sub': subject},
        separators=(',', ':')).encode())
    signing_input = ('%s.%s' % (header, claims)).encode('ascii')

    priv_int = int.from_bytes(b64url_decode(private_key_b64), 'big')
    private_key = ec.derive_private_key(priv_int, ec.SECP256R1())
    der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # JOSE wants the raw pair, not the DER structure cryptography hands back.
    r, s = asym_utils.decode_dss_signature(der)
    signature = b64url_encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))

    token = '%s.%s.%s' % (header, claims, signature)
    return {
        'Authorization': 'vapid t=%s, k=%s' % (token, public_key_b64),
        'Content-Encoding': CONTENT_ENCODING,
    }


def send(endpoint, client_public_b64, client_auth_b64, payload,
         private_key_b64, public_key_b64, subject, ttl=86400, timeout=10):
    """Deliver one message. Returns the push service's HTTP status."""
    import urllib.request
    import urllib.error

    body = encrypt(payload, client_public_b64, client_auth_b64)
    headers = vapid_headers(endpoint, private_key_b64, public_key_b64, subject)
    headers.update({
        'TTL': str(ttl),
        'Content-Type': 'application/octet-stream',
        'Content-Length': str(len(body)),
    })
    req = urllib.request.Request(endpoint, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, ''
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'replace')[:200]
        except Exception:
            pass
        return exc.code, detail
