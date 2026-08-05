import json as _json
import logging
import re
import threading
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_WINDOW = 600   # seconds
_RATE_LIMIT_MAX = 5
_rate_buckets: dict = {}   # {ip: [timestamp, ...]}

# Cached DB name — resolved once on first request.
_TARGET_DB: str | None = None
_TARGET_DB_LOCK = threading.Lock()


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        bucket = _rate_buckets.get(ip, [])
        bucket = [t for t in bucket if now - t < _RATE_LIMIT_WINDOW]
        if len(bucket) >= _RATE_LIMIT_MAX:
            _rate_buckets[ip] = bucket
            return False
        bucket.append(now)
        _rate_buckets[ip] = bucket
        return True


def _get_target_db() -> str | None:
    """Return the first DB in odoo.conf that has fitness_trials installed."""
    global _TARGET_DB
    if _TARGET_DB:
        return _TARGET_DB
    with _TARGET_DB_LOCK:
        if _TARGET_DB:
            return _TARGET_DB
        import odoo
        from odoo.tools import config
        raw = config.get('db_name')
        if isinstance(raw, list):
            db_names = [d.strip() for d in raw if d.strip()]
        else:
            db_names = [d.strip() for d in (raw or '').split(',') if d.strip()]
        import odoo.sql_db
        for db_name in db_names:
            try:
                with odoo.sql_db.db_connect(db_name).cursor() as cr:
                    cr.execute(
                        "SELECT 1 FROM ir_module_module "
                        "WHERE name='fitness_trials' AND state='installed' LIMIT 1"
                    )
                    if cr.fetchone():
                        _TARGET_DB = db_name
                        _logger.info("fitness_trials: target DB resolved to %s", db_name)
                        return db_name
            except Exception as e:
                _logger.warning("fitness_trials: DB %s check failed: %s", db_name, e)
        _logger.error(
            "fitness_trials: no DB found with module installed — "
            "check db_name in odoo.conf and that fitness_trials is installed"
        )
        return None


_CORS_HEADERS = [
    ('Access-Control-Allow-Origin', '*'),
    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
    ('Access-Control-Allow-Headers', 'Content-Type'),
    ('Access-Control-Max-Age', '86400'),
]


def _json_ok(data: dict):
    return request.make_response(
        _json.dumps(data),
        headers=[('Content-Type', 'application/json')] + _CORS_HEADERS,
    )


def _json_err(msg: str, status: int = 200):
    return request.make_response(
        _json.dumps({'success': False, 'error': msg}),
        headers=[('Content-Type', 'application/json')] + _CORS_HEADERS,
        status=status,
    )


class TrialRequestController(http.Controller):

    @http.route(
        '/trial/request',
        type='http',
        auth='none',  # server-wide: no DB session required; we open the registry ourselves
        methods=['POST', 'OPTIONS'],
        csrf=False,
        save_session=False,
    )
    def submit_trial_request(self, **_post):
        # CORS preflight
        if request.httprequest.method == 'OPTIONS':
            return request.make_response('', headers=_CORS_HEADERS)

        ip = request.httprequest.remote_addr or 'unknown'

        if not _check_rate_limit(ip):
            return _json_err('Too many requests. Please try again later.', status=429)

        try:
            data = _json.loads(request.httprequest.data or b'{}')
        except Exception:
            return _json_err('Invalid request body.', status=400)

        name  = (data.get('name')  or '').strip()[:120]
        email = (data.get('email') or '').strip()[:200]
        phone = (data.get('phone') or '').strip()[:40]
        notes = (data.get('notes') or '').strip()[:1000]
        lang  = (data.get('lang')  or 'en_US').strip()[:10]

        if not name:
            return _json_err('Name is required.')
        if not email or not _EMAIL_RE.match(email):
            return _json_err('A valid email address is required.')
        if lang not in ('en_US', 'es_ES', 'ca_ES'):
            lang = 'en_US'

        db_name = _get_target_db()
        if not db_name:
            return _json_err('Server configuration error.', status=500)

        try:
            from odoo.modules.registry import Registry
            import odoo.api
            with Registry(db_name).cursor() as cr:
                env = odoo.api.Environment(cr, 1, {})
                env['fitness.trial.request'].create({
                    'name': name,
                    'email': email,
                    'phone': phone or False,
                    'preferred_time_notes': notes or False,
                    'lang': lang,
                    'status': 'pending',
                })
        except Exception:
            _logger.exception("Error creating trial request from %s", ip)
            return _json_err('Server error. Please try again.', status=500)

        return _json_ok({'success': True})
