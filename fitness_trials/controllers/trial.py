import json as _json
import logging
import pytz
import re
import threading
import time
from datetime import date as _date, datetime, time as _time, timedelta

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

_STUDIO_TZ = pytz.timezone('Europe/Madrid')
_DAY_NAMES = {
    'en_US': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
    'es_ES': ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'],
    'ca_ES': ['Dilluns', 'Dimarts', 'Dimecres', 'Dijous', 'Divendres', 'Dissabte', 'Diumenge'],
}
_MONTH_NAMES = {
    'en_US': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    'es_ES': ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
    'ca_ES': ['gen', 'feb', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'oct', 'nov', 'des'],
}


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


def _format_event(ev, lang: str = 'es_ES') -> dict:
    """Convert a calendar.event record to a template-ready slot dict."""
    dt_local = ev.start.replace(tzinfo=pytz.UTC).astimezone(_STUDIO_TZ)
    duration = int((ev.stop - ev.start).total_seconds() // 60) if ev.stop else 0
    available = max(0, ev.capacity - ev.booked_seats) if ev.capacity else None
    days   = _DAY_NAMES.get(lang, _DAY_NAMES['es_ES'])
    months = _MONTH_NAMES.get(lang, _MONTH_NAMES['es_ES'])
    return {
        'id': ev.id,
        'name': ev.name,
        'day': days[dt_local.weekday()],
        'day_num': dt_local.day,
        'month': months[dt_local.month - 1],
        'time': dt_local.strftime('%H:%M'),
        'duration': duration,
        'teacher': ev.user_id.name if ev.user_id and ev.user_id.login != 'OdooBot' else '',
        'available': available,
        'start_utc': ev.start,
        'start_date': dt_local.date().isoformat(),
    }


class TrialRequestController(http.Controller):

    def _get_slots(self, discipline) -> list:
        """Formatted class occurrences for a discipline, next 14 days.

        Reformer was deliberately absent here: the studio reviewed those
        requests by hand so a first-timer could be matched to a suitable
        class, and the form asked about experience instead of offering a
        slot. Both disciplines are booked the same way now - pick a class -
        so the only thing that differs is the classroom_type asked for.
        """
        lang = request.context.get('lang', 'es_ES')
        now = _odoo_fields.Datetime.now()
        horizon = now + timedelta(days=14)

        # Never offer a class the trial cannot be claimed on. Fourteen days and
        # the end of the offer happen to be the same date today, which is why
        # the lists look right; a week from now the rolling window would run
        # past the offer and show classes nobody could take.
        offer_end = request.env['ir.config_parameter'].sudo().get_param(
            'fitness.trial_offer_end')
        if offer_end:
            try:
                end_dt = datetime.combine(
                    _date.fromisoformat(offer_end), _time.max)
                horizon = min(horizon, end_dt)
            except (ValueError, TypeError):
                pass

        if horizon <= now:
            return []

        events = request.env['calendar.event'].sudo().search([
            ('is_fitness_class', '=', True),
            ('class_type_id.classroom_type', '=', discipline),
            ('class_state', '!=', 'cancelled'),
            ('start', '>', now),
            ('start', '<', horizon),
        ], order='start asc')
        return [_format_event(ev, lang) for ev in events]

    def _get_barre_slots(self) -> list:
        """Kept for the JSON API below, which only ever offered Barre."""
        return self._get_slots('barre')

    def _trials(self):
        """The model, which owns the timetable questions."""
        return request.env['fitness.trial.request'].sudo()

    def _class_types(self):
        return self._trials()._offered_class_types()

    def _form_ctx(self, **extra):
        """Everything the form needs to render, however it got here."""
        Trials = self._trials()
        types = Trials._offered_class_types()
        open_days = Trials._open_weekdays()
        lang = request.httprequest.cookies.get('mv_lang', 'es_ES')
        if lang not in _VALID_LANGS:
            lang = 'es_ES'
        ctx = {
            'barre_types': types['barre'],
            'reformer_types': types['reformer'],
            'today_iso': _date.today().isoformat(),
            # Which days the studio is open, for the hint under the date box
            # and for the check in the browser. Python's weekday numbers,
            # because that is what a Date gives JavaScript once shifted.
            'open_days': open_days,
            'open_dows': [Trials.WEEKDAY_ORDER.index(d) for d in open_days],
            'open_days_label': Trials._weekday_hint(open_days, lang),
            'form_values': {},
            'source': 'website',
        }
        ctx.update(extra)
        return ctx

    def _get_date_filters(self, slots: list) -> list:
        """Return [{key, label}] for each unique slot date — used by date-filter pills."""
        try:
            from babel.dates import format_date as _babel_fmt
            _babel_ok = True
        except ImportError:
            _babel_ok = False

        lang     = request.context.get('lang', 'es_ES')
        today    = _date.today()
        tomorrow = today + timedelta(days=1)

        seen    = set()
        filters = []
        for slot in slots:
            d_str = slot.get('start_date', '')
            if not d_str or d_str in seen:
                continue
            seen.add(d_str)
            try:
                d = _date.fromisoformat(d_str)
            except (ValueError, AttributeError):
                continue

            if d == today:
                label = _('Today')
            elif d == tomorrow:
                label = _('Tomorrow')
            elif _babel_ok:
                try:
                    locale = lang.replace('_', '-')
                    abbr   = _babel_fmt(d, format='EEE', locale=locale).rstrip('.').strip()
                    label  = '{} {}'.format(abbr.capitalize(), d.day)
                except Exception:
                    label  = '{} {}'.format(d.strftime('%a'), d.day)
            else:
                label = '{} {}'.format(d.strftime('%a'), d.day)

            filters.append({'key': d_str, 'label': label})

        return filters

    # ──────────────────────────────────────────────────────────────
    # Portal form  GET /trial  /  POST /trial/submit
    # ──────────────────────────────────────────────────────────────

    @http.route('/my/trial', type='http', auth='user', website=True,
                sitemap=False, multilang=False)
    def trial_form_app(self, **kw):
        """The same form, reached from inside the app.

        One handler and one template; the only thing that differs is the label
        the request is stamped with, so an admin can tell where somebody was
        standing when they asked.
        """
        return self.trial_form(_source='app', **kw)

    @http.route('/trial/classes', type='http', auth='public', website=True,
                methods=['GET'], sitemap=False, multilang=False, csrf=False)
    def trial_classes(self, **kw):
        """The classes actually running on a date and period, as JSON.

        The form asks for this the moment the date or the period changes, so
        what a student chooses from is the timetable as it stands rather than
        a catalogue of class types the studio might run on some other day.
        That is the whole point of the reorder: a class the studio cancelled
        for that day cannot be picked, because it is not in this answer.

        Public on purpose - the trial form is the front door and most people
        using it have no account. Nothing comes back that is not already on
        the public timetable, and the rule about what may be offered lives on
        the model, shared with the studio's own candidate-slot list, so the
        two cannot end up saying different things.
        """
        raw = (kw.get('date') or '').strip()[:10]
        try:
            day = _date.fromisoformat(raw) if raw else None
        except ValueError:
            day = None
        period = (kw.get('period') or '').strip()
        if period not in ('morning', 'evening'):
            period = None
        slots = []
        if day:
            slots = request.env['fitness.trial.request'].sudo()._trial_slots(
                day, period)
        return request.make_response(
            _json.dumps({'slots': slots}),
            headers=[('Content-Type', 'application/json')])

    @http.route('/trial', type='http', auth='public', website=True, sitemap=True, multilang=False)
    def trial_form(self, _source='website', **kw):
        """Render the trial class request form."""
        # A logged-in student should not retype what we already know. Their
        # name and email are pre-filled, and class_interest can be preselected
        # by query string so the portal's Reformer guard lands on the right
        # branch of the form rather than a blank choice.
        prefill = {}
        if not request.env.user._is_public():
            partner = request.env.user.partner_id
            prefill = {'name': partner.name or '', 'email': partner.email or '',
                       'phone': partner.phone or ''}
        wanted = (kw.get('class_interest') or '').strip()
        if wanted in ('barre', 'reformer'):
            prefill['class_interest'] = wanted

        # Say no here rather than after she has filled it in. The entitlement
        # is one trial per student, either discipline, and approval refuses a
        # second - so a student whose trial is spent could complete the whole
        # form, wait, and be declined. Home already hides the offer from her;
        # this page did not, because it never asked.
        #
        # Only for somebody we can identify. A public visitor is not asked to
        # prove who they are before seeing a form, and matching on a typed
        # email would tell a stranger whether that address has an account.
        already_used = False
        pending = False
        if not request.env.user._is_public():
            TR = request.env['fitness.trial.request'].sudo()
            partner = request.env.user.partner_id
            already_used = TR._trial_already_claimed(partner)
            # She has asked and the studio has not answered yet. The shop
            # already said "Request sent"; this form did not ask, so she
            # could fill it in again and send a second one.
            pending = bool(TR._open_request_for(partner))

        ctx = self._form_ctx(error=kw.get('error'), form_values=prefill,
                             source=_source)
        ctx['trial_already_used'] = already_used
        ctx['trial_request_pending'] = pending
        return request.render('fitness_trials.trial_request_form', ctx)

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
        class_type_raw  = (kw.get('class_type_id') or '').strip()
        occurrence_raw  = (kw.get('occurrence_id') or '').strip()
        preferred_date  = (kw.get('preferred_date') or '').strip()[:10]
        preferred_period = (kw.get('preferred_period') or '').strip()
        # Stamped by the form itself rather than guessed from the session: a
        # student can be signed in and still be reading the public site.
        source = 'app' if (kw.get('source') or '').strip() == 'app' else 'website'
        lang = request.httprequest.cookies.get('mv_lang', 'es_ES')
        if lang not in _VALID_LANGS:
            lang = 'es_ES'

        form_values = {
            'name': name, 'email': email, 'phone': phone,
            'class_interest': class_interest, 'notes': notes,
            'reformer_is_first_time': reformer_first,
            'reformer_years_experience': reformer_years,
            'class_type_id': class_type_raw,
            'occurrence_id': occurrence_raw,
            'preferred_date': preferred_date,
            'preferred_period': preferred_period,
        }

        errors = []
        if not name:
            errors.append(_('Please provide your name.'))
        if not email or not _EMAIL_RE.match(email):
            errors.append(_('A valid email address is required.'))
        if class_interest not in _VALID_CLASS_INTERESTS:
            errors.append(_('Please select a class type (Barre or Reformer).'))

        # The class they asked for has to exist and belong to the discipline
        # they chose, so a stale Barre id cannot arrive on a Reformer request.
        class_type = None
        if class_interest in _VALID_CLASS_INTERESTS:
            if not class_type_raw:
                errors.append(_('Please choose a class.'))
            else:
                try:
                    ct = request.env['fitness.class.type'].sudo().browse(int(class_type_raw))
                    if ct.exists() and ct.classroom_type == class_interest:
                        class_type = ct
                    else:
                        errors.append(_('That class does not belong to the discipline you chose.'))
                except (ValueError, TypeError):
                    errors.append(_('Please choose a class.'))
        if not preferred_date:
            errors.append(_('Please choose a preferred date.'))
        else:
            try:
                chosen = _date.fromisoformat(preferred_date)
                if chosen < _date.today():
                    errors.append(_('Please choose a date that has not already passed.'))
            except ValueError:
                errors.append(_('Please choose a preferred date.'))
        if preferred_period not in ('morning', 'evening'):
            errors.append(_('Please say whether you prefer the morning or the evening.'))
        # The studio is closed on days it runs nothing, so a request for one
        # is a request somebody has to go back and renegotiate. Checked here
        # as well as in the browser: the browser check is a courtesy, this is
        # the one that holds.
        if preferred_date and not errors:
            _trials = self._trials()
            try:
                _day = _date.fromisoformat(preferred_date)
            except ValueError:
                _day = None
            if _day is not None and not _trials._is_open_on(_day):
                errors.append(_(
                    'The studio is closed that day. Please choose another: %(days)s.',
                    days=_trials._weekday_hint(_trials._open_weekdays(), lang)))
        if class_interest == 'reformer' and reformer_first not in ('yes', 'no'):
            errors.append(_('Please tell us whether you have used a Reformer before.'))

        # The actual class they picked, re-checked against the same rule the
        # form was filled from. A posted id is never taken on trust: the page
        # can have sat open while the studio cancelled that class, and the
        # whole point of this rework is that a cancelled class cannot be
        # booked. Re-asking the model is what makes that true at submit time
        # and not merely at render time.
        occurrence = None
        if occurrence_raw and not errors:
            try:
                wanted = int(occurrence_raw)
            except (ValueError, TypeError):
                wanted = 0
            if wanted:
                _day2 = None
                try:
                    _day2 = _date.fromisoformat(preferred_date)
                except ValueError:
                    _day2 = None
                allowed = {s['id'] for s in self._trials()._trial_slots(
                    _day2, preferred_period)} if _day2 else set()
                if wanted in allowed:
                    occurrence = request.env['calendar.event'].sudo().browse(wanted)
                else:
                    errors.append(_(
                        'That class is no longer available. Please choose '
                        'another one.'))

        # One open request at a time. The form is reachable directly, and a
        # student who asked yesterday could send another today - the studio
        # then has two rows for one person and no way to tell which she meant.
        # Matched on the logged-in student rather than the typed email: a
        # public visitor is not identified, and answering on an email would
        # tell a stranger whether that address has asked for anything.
        if not request.env.user._is_public():
            TR = request.env['fitness.trial.request'].sudo()
            open_already = TR._open_request_for(request.env.user.partner_id)
            if open_already:
                errors.append(_(
                    'You already have a trial request with the studio. '
                    'We will be in touch shortly.'))

        if errors:
            return request.render(
                'fitness_trials.trial_request_form',
                self._form_ctx(error=' '.join(errors), form_values=form_values,
                               source=source))

        vals = {
            'name': name,
            'email': email,
            'phone': phone or False,
            'class_interest': class_interest,
            'class_type_id': class_type.id if class_type else False,
            'occurrence_id': occurrence.id if occurrence else False,
            'preferred_date': preferred_date or False,
            'preferred_period': preferred_period or False,
            'source': source,
            'lang': lang,
        }
        # The Reformer intake answers. The form has asked these for as long as
        # it has existed and the submit handler read them into the re-render
        # values and then dropped them on the floor - they were never written
        # to the record, so the studio's Reformer Intake fields sat empty no
        # matter what anybody answered. Only stored for Reformer: they mean
        # nothing on a Barre request.
        if class_interest == 'reformer':
            vals['reformer_is_first_time'] = reformer_first or False
            vals['reformer_years_experience'] = (
                reformer_years if reformer_first == 'no' else False)

        # A logged-in student gets their partner attached, so approval can book
        # against a real record instead of matching on an email string. Public
        # submissions leave it empty and are resolved by email at approval time.
        #
        # Only when the address on the form is their own, though. The session
        # belongs to whoever last used the browser, and the form asks for a
        # name and an email precisely because that may be somebody else - an
        # instructor filling it in for a walk-in on the studio's tablet, a
        # friend borrowing a phone. Attaching the logged-in partner regardless
        # attributes the trial to the wrong person, and approval then books
        # that person into the class instead of the one who asked.
        if not request.env.user._is_public():
            own = (request.env.user.partner_id.email or '').strip().lower()
            if own and own == email.strip().lower():
                vals['partner_id'] = request.env.user.partner_id.id
            else:
                _logger.info(
                    "Trial submitted for %s from a session belonging to %s; "
                    "leaving it unattached to be matched by email",
                    email, request.env.user.login)

        # No slot is chosen here any more, so nothing books itself: every
        # request lands as pending and the studio places it. With a
        # three-student minimum an instant booking could not have known
        # whether the class would actually run.
        # One open request per address, whoever is asking.
        #
        # This used to match on email AND class AND date, which only ever
        # caught a double click. Changing the class or the date produced a
        # second row, and the studio's Pending list filled up with the same
        # person several times over - Núria Mundó Guixà twice, Laia Ubia
        # twice, Eva Morales seven times. Measured on the live form: same
        # address, different class, two requests created.
        #
        # Deliberately answered with the SAME confirmation page rather than
        # an error. A public visitor is not identified, and a message saying
        # "you already have a request" would tell whoever typed an address
        # whether that address has ever contacted the studio. Returning her
        # to the confirmation blocks the duplicate and discloses nothing -
        # and it is true: her request is with the studio.
        #
        # Still open only. Once a request has been declined or scheduled,
        # asking again is a real second ask - she may want to buy a class
        # now - and the studio sees that one flagged Trial Used instead.
        twin = request.env['fitness.trial.request'].sudo().search([
            ('email', '=ilike', email),
            ('status', 'in', ('pending', 'contacted')),
        ], limit=1)
        if twin:
            _logger.info(
                "Duplicate trial submission for %s; she already has open "
                "request %s, returning her to the confirmation",
                email, twin.id)
            return request.render(
                'fitness_trials.trial_request_form',
                self._form_ctx(success=True, submitted_interest=class_interest,
                               source=source))

        try:
            request.env['fitness.trial.request'].sudo().create(vals)
        except Exception:
            _logger.exception("Portal trial submission error")
            return request.render(
                'fitness_trials.trial_request_form',
                self._form_ctx(error=_('Something went wrong. Please try again.'),
                               form_values=form_values, source=source))

        return request.render(
            'fitness_trials.trial_request_form',
            self._form_ctx(success=True, submitted_interest=class_interest,
                           source=source))

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
        lang             = (data.get('lang')             or 'es_ES').strip()[:10]
        class_interest   = (data.get('class_interest')   or 'barre').strip()
        reformer_first   = (data.get('reformer_is_first_time')     or '').strip()
        reformer_years   = (data.get('reformer_years_experience')  or '').strip()[:40]

        if not name:
            return _json_err('Name is required.')
        if not email or not _EMAIL_RE.match(email):
            return _json_err('A valid email address is required.')
        if lang not in _VALID_LANGS:
            lang = 'es_ES'
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
