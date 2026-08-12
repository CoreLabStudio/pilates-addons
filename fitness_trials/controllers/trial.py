import json as _json
import logging
import pytz
import re
import threading
import time
from datetime import timedelta

from odoo import fields as _odoo_fields, http, _
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

_VALID_LANGS = frozenset({'en_US', 'es_ES', 'ca_ES'})
_VALID_CLASS_INTERESTS = frozenset({'barre', 'reformer'})

_STUDIO_TZ = pytz.timezone('Europe/Lisbon')
_DAYS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
_MONTHS_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


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


def _format_event(ev) -> dict:
    """Convert a calendar.event record to a template-ready slot dict."""
    dt_local = ev.start.replace(tzinfo=pytz.UTC).astimezone(_STUDIO_TZ)
    duration = int((ev.stop - ev.start).total_seconds() // 60) if ev.stop else 0
    available = max(0, ev.capacity - ev.booked_seats) if ev.capacity else None
    return {
        'id': ev.id,
        'name': ev.name,
        'day': _DAYS_ES[dt_local.weekday()],
        'day_num': dt_local.day,
        'month': _MONTHS_ES[dt_local.month - 1],
        'time': dt_local.strftime('%H:%M'),
        'duration': duration,
        'teacher': ev.user_id.name if ev.user_id else '',
        'available': available,
        'start_utc': ev.start,
    }


class TrialRequestController(http.Controller):

    def _get_barre_slots(self) -> list:
        """Return formatted Barre class occurrences available in the next 14 days."""
        now = _odoo_fields.Datetime.now()
        events = request.env['calendar.event'].sudo().search([
            ('is_fitness_class', '=', True),
            ('start', '>', now),
            ('start', '<', now + timedelta(days=14)),
        ], order='start asc').filtered(
            lambda e: (
                e.class_type_id.classroom_type == 'barre'
                and (not e.capacity or e.booked_seats < e.capacity)
            )
        )
        return [_format_event(ev) for ev in events]

    # ──────────────────────────────────────────────────────────────
    # Portal form  GET /trial  /  POST /trial/submit
    # ──────────────────────────────────────────────────────────────

    @http.route('/trial', type='http', auth='public', website=True, sitemap=True, multilang=False)
    def trial_form(self, **kw):
        """Render the trial class request form."""
        return request.render('fitness_trials.trial_request_form', {
            'error': kw.get('error'),
            'form_values': {},
            'barre_slots': self._get_barre_slots(),
        })

    @http.route('/trial/submit', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False, multilang=False)
    def trial_submit(self, **kw):
        """Handle HTML form submission from the portal trial request form."""
        name            = (kw.get('name')   or '').strip()[:120]
        email           = (kw.get('email')  or '').strip()[:200]
        phone           = (kw.get('phone')  or '').strip()[:40]
        class_interest  = (kw.get('class_interest') or '').strip()
        notes           = (kw.get('notes')  or '').strip()[:1000]
        reformer_first  = (kw.get('reformer_is_first_time') or '').strip()
        reformer_years  = (kw.get('reformer_years_experience') or '').strip()[:40]
        occurrence_raw  = (kw.get('occurrence_id') or '').strip()
        lang = request.context.get('lang', 'es_ES')
        if lang not in _VALID_LANGS:
            lang = 'es_ES'

        form_values = {
            'name': name, 'email': email, 'phone': phone,
            'class_interest': class_interest, 'notes': notes,
            'reformer_is_first_time': reformer_first,
            'reformer_years_experience': reformer_years,
            'occurrence_id': occurrence_raw,
        }

        errors = []
        if not name:
            errors.append(_('Please provide your name.'))
        if not email or not _EMAIL_RE.match(email):
            errors.append(_('A valid email address is required.'))
        if class_interest not in _VALID_CLASS_INTERESTS:
            errors.append(_('Please select a class type (Barre or Reformer).'))

        # Barre: validate that a real, available slot was selected
        occurrence = None
        if class_interest == 'barre':
            if not occurrence_raw:
                errors.append(_('Please select a Barre class slot.'))
            else:
                try:
                    occ_id = int(occurrence_raw)
                    occ = request.env['calendar.event'].sudo().browse(occ_id)
                    if (
                        occ.exists()
                        and occ.is_fitness_class
                        and occ.class_type_id.classroom_type == 'barre'
                        and (not occ.capacity or occ.booked_seats < occ.capacity)
                    ):
                        occurrence = occ
                    else:
                        errors.append(_('Invalid class slot selected.'))
                except (ValueError, TypeError):
                    errors.append(_('Invalid class slot selected.'))

        if errors:
            return request.render('fitness_trials.trial_request_form', {
                'error': ' '.join(errors),
                'form_values': form_values,
                'barre_slots': self._get_barre_slots(),
            })

        vals = {
            'name': name,
            'email': email,
            'phone': phone or False,
            'class_interest': class_interest,
            'lang': lang,
        }

        submitted_slot = None
        if class_interest == 'barre' and occurrence:
            submitted_slot = _format_event(occurrence)
            vals.update({
                'occurrence_id': occurrence.id,
                'scheduled_datetime': occurrence.start,
                'status': 'scheduled',
                'preferred_time_notes': False,
            })
        elif class_interest == 'reformer':
            vals['preferred_time_notes'] = notes or False
            if reformer_first in ('yes', 'no'):
                vals['reformer_is_first_time'] = reformer_first
            if reformer_years and reformer_first == 'no':
                vals['reformer_years_experience'] = reformer_years

        try:
            request.env['fitness.trial.request'].sudo().create(vals)
        except Exception:
            _logger.exception("Portal trial submission error")
            return request.render('fitness_trials.trial_request_form', {
                'error': _('Something went wrong. Please try again.'),
                'form_values': form_values,
                'barre_slots': self._get_barre_slots(),
            })

        return request.render('fitness_trials.trial_request_form', {
            'success': True,
            'submitted_interest': class_interest,
            'submitted_slot': submitted_slot,
            'form_values': {},
            'barre_slots': [],
        })

    # ──────────────────────────────────────────────────────────────
    # External JSON API  POST /trial/request  (marketing site)
    # ──────────────────────────────────────────────────────────────

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

        name             = (data.get('name')             or '').strip()[:120]
        email            = (data.get('email')            or '').strip()[:200]
        phone            = (data.get('phone')            or '').strip()[:40]
        notes            = (data.get('notes')            or '').strip()[:1000]
        lang             = (data.get('lang')             or 'en_US').strip()[:10]
        class_interest   = (data.get('class_interest')   or 'barre').strip()
        reformer_first   = (data.get('reformer_is_first_time')     or '').strip()
        reformer_years   = (data.get('reformer_years_experience')  or '').strip()[:40]

        if not name:
            return _json_err('Name is required.')
        if not email or not _EMAIL_RE.match(email):
            return _json_err('A valid email address is required.')
        if lang not in _VALID_LANGS:
            lang = 'en_US'
        if class_interest not in _VALID_CLASS_INTERESTS:
            class_interest = 'barre'

        db_name = _get_target_db()
        if not db_name:
            return _json_err('Server configuration error.', status=500)

        try:
            from odoo.modules.registry import Registry
            import odoo.api
            with Registry(db_name).cursor() as cr:
                env = odoo.api.Environment(cr, 1, {})
                vals = {
                    'name': name,
                    'email': email,
                    'phone': phone or False,
                    'preferred_time_notes': notes or False,
                    'lang': lang,
                    'class_interest': class_interest,
                    'status': 'pending',
                }
                if class_interest == 'reformer':
                    if reformer_first in ('yes', 'no'):
                        vals['reformer_is_first_time'] = reformer_first
                    if reformer_years:
                        vals['reformer_years_experience'] = reformer_years
                env['fitness.trial.request'].create(vals)
        except Exception:
            _logger.exception("Error creating trial request from %s", ip)
            return _json_err('Server error. Please try again.', status=500)

        return _json_ok({'success': True})
