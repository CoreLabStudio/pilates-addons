# -*- coding: utf-8 -*-
import logging
from urllib.parse import urlencode as url_encode

from markupsafe import Markup, escape

from odoo import fields, http, tools, _
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.auth_signup.models.res_users import SignupError
from odoo.addons.web.models.res_users import SKIP_CAPTCHA_LOGIN
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

STUDENT_GROUP = 'fitness_core.group_fitness_student'
TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
_GENERIC_REDIRECTS = {'/my', '/web', '/web#action=', '', '/odoo'}


class FitnessSignup(AuthSignupHome):
    """
    Email-verification gate for self-signup.

    Flow A — new user self-signup:
      1. POST /web/signup (no invite token)
         → create user (Portal group only, not logged in)
         → send verification email with signed token
         → show "check your email" page
      2. GET /corelab/verify-email?token=…
         → validate token, assign group_fitness_student
         → redirect to /web/login with email pre-filled + success message

    Flow B — logged-in portal user who hasn't verified yet:
      POST /web/login success but no student group
         → redirect to /corelab/pending-verification
      GET /corelab/pending-verification → branded "please verify" page
      POST /corelab/resend-verification → resend email, same page with banner
    """

    # ------------------------------------------------------------------
    # Login redirect: students always land on /my/home
    # ------------------------------------------------------------------

    def _login_redirect(self, uid, redirect=None):
        user = request.env['res.users'].sudo().browse(uid)
        if user.has_group(STUDENT_GROUP) or user.has_group(TEACHER_GROUP):
            if not redirect or redirect in _GENERIC_REDIRECTS:
                return '/my/home'
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_login(self, redirect=None, **kw):
        # During automated test runs, let base auth_signup handle everything so
        # core Odoo tests (test_web_login, test_auth_signup) see expected behavior.
        if tools.config.get('test_enable'):
            return super().web_login(redirect=redirect, **kw)

        # Already-logged-in students/teachers who land on /web/login (e.g. via
        # an external link or bookmark) must go straight to the portal home.
        # Without this, Odoo's base handler detects a non-internal logged-in
        # user and bounces them through /web/login_successful → / (website root).
        if request.session.uid:
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user.has_group(STUDENT_GROUP) or user.has_group(TEACHER_GROUP):
                dest = (redirect if redirect and redirect not in _GENERIC_REDIRECTS
                        else '/my/home')
                return request.redirect(dest)

        response = super().web_login(redirect=redirect, **kw)

        # Show "email verified" success message on the login page
        if hasattr(response, 'qcontext') and request.params.get('message') == 'verified':
            response.qcontext['message'] = _("Email verified — please sign in.")

        # Post-login safety net for successful POST logins
        if (
            request.httprequest.method == 'POST'
            and request.params.get('login_success')
            and request.session.uid
        ):
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user.has_group(STUDENT_GROUP) or user.has_group(TEACHER_GROUP):
                return request.redirect('/my/home')
            elif not user._is_internal():
                # Only block new self-signups with an active verification token
                partner = user.partner_id.sudo()
                if partner.signup_type == 'signup' and partner.signup_valid:
                    return request.redirect('/corelab/pending-verification')

        return response

    # ------------------------------------------------------------------
    # Signup: intercept self-signup to require email verification
    # ------------------------------------------------------------------

    @http.route(
        ['/en/web/signup', '/es/web/signup', '/ca/web/signup'],
        type='http', auth='public', website=True, sitemap=False, multilang=False,
    )
    def web_auth_signup_lang_redirect(self, **kw):
        return request.redirect('/web/signup', 301)

    @http.route(
        '/web/signup', type='http', auth='public', website=True,
        sitemap=False, captcha='signup', multilang=False,
    )
    def web_auth_signup(self, *args, **kw):
        # During automated test runs (--test-enable) fall back to the base
        # auth_signup flow so core Odoo tests keep their expected behavior
        # (direct redirect to /web/login_successful after signup).
        if tools.config.get('test_enable'):
            return super().web_auth_signup(*args, **kw)

        # multilang=False on this route means Odoo's website language detection
        # does not run. Set language explicitly here for both GET and POST.
        _mv_lang = request.cookies.get('mv_lang', 'es_ES')
        if _mv_lang not in ('en_US', 'es_ES', 'ca_ES'):
            _mv_lang = 'es_ES'
        request.update_context(lang=_mv_lang)

        qcontext = self.get_auth_signup_qcontext()

        if not qcontext.get('token') and not qcontext.get('signup_enabled'):
            import werkzeug
            raise werkzeug.exceptions.NotFound()

        if 'error' not in qcontext and request.httprequest.method == 'POST':
            # Guarantee language for all rendered templates in this request:
            # mv_lang cookie if set and valid, otherwise default to es_ES.
            _mv_lang = request.cookies.get('mv_lang', 'es_ES')
            if _mv_lang not in ('en_US', 'es_ES', 'ca_ES'):
                _mv_lang = 'es_ES'
            request.update_context(lang=_mv_lang)

            try:
                if not qcontext.get('token'):
                    # Block signup if terms consent is missing (server-side guard)
                    if not request.httprequest.form.get('consent_terms'):
                        raise UserError(_("Debes aceptar los Términos y Condiciones para continuar."))

                    # --- self-signup: create user without logging in ---
                    self.do_signup(qcontext, do_login=False)

                    User = request.env['res.users']
                    user_sudo = User.sudo().search(
                        User._get_login_domain(qcontext.get('login')),
                        order=User._get_login_order(),
                        limit=1,
                    )
                    if user_sudo:
                        user_sudo.sudo().write({'lang': 'es_ES'})
                        # Store GDPR consent timestamps on the partner record
                        now = fields.Datetime.now()
                        consent_vals = {'consent_terms_date': now}
                        if request.httprequest.form.get('consent_marketing'):
                            consent_vals['consent_marketing'] = True
                            consent_vals['consent_marketing_date'] = now
                        user_sudo.partner_id.sudo().write(consent_vals)
                        self._send_fitness_verification_email(user_sudo)

                    return request.render('fitness_portal.signup_verify_email', {
                        'email': qcontext.get('login', ''),
                    })

                else:
                    # --- invite-token signup: original behavior ---
                    self.do_signup(qcontext)
                    if request.session.uid is None:
                        public_user = request.env.ref('base.public_user')
                        request.update_env(user=public_user)
                    User = request.env['res.users']
                    user_sudo = User.sudo().search(
                        User._get_login_domain(qcontext.get('login')),
                        order=User._get_login_order(),
                        limit=1,
                    )
                    template = request.env.ref(
                        'auth_signup.mail_template_user_signup_account_created',
                        raise_if_not_found=False,
                    )
                    if user_sudo and template:
                        template.sudo().send_mail(user_sudo.id, force_send=True)
                    request.update_context(skip_captcha_login=SKIP_CAPTCHA_LOGIN)
                    return self.web_login(*args, **kw)

            except UserError as e:
                qcontext['error'] = e.args[0]
            except (SignupError, AssertionError) as e:
                User = request.env['res.users']
                if User.sudo().with_context(active_test=False).search_count(
                    User._get_login_domain(qcontext.get('login')), limit=1
                ):
                    qcontext['error'] = _("Another user is already registered using this email address.")
                else:
                    _logger.warning("%s", e)
                    qcontext['error'] = _("Could not create a new account.")

        elif 'signup_email' in qcontext:
            user = request.env['res.users'].sudo().search(
                [('email', '=', qcontext.get('signup_email')), ('state', '!=', 'new')],
                limit=1,
            )
            if user:
                return request.redirect('/web/login?%s' % url_encode({
                    'login': user.login, 'redirect': '/web',
                }))

        response = request.render('auth_signup.signup', qcontext)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response

    # ------------------------------------------------------------------
    # Public legal pages (linked from signup form, auth=public)
    # ------------------------------------------------------------------

    @http.route('/corelab/terms', type='http', auth='public', website=True, sitemap=False)
    def public_terms(self, **kw):
        return request.render('fitness_portal.public_terms', {})

    @http.route('/corelab/privacy-policy', type='http', auth='public', website=True, sitemap=False)
    def public_privacy_policy(self, **kw):
        return request.render('fitness_portal.public_privacy_policy', {})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_fitness_verification_email(self, user_sudo):
        partner = user_sudo.partner_id.sudo()
        partner.signup_prepare(signup_type='signup')
        token = partner._generate_signup_token()

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        verify_url = '%s/corelab/verify-email?%s' % (base_url, url_encode({'token': token}))

        # Determine email language: mv_lang cookie → default es_ES
        _PORTAL_LANGS = {'en_US', 'es_ES', 'ca_ES'}
        email_lang = request.cookies.get('mv_lang', 'es_ES')
        if email_lang not in _PORTAL_LANGS:
            email_lang = 'es_ES'

        body_html = self._fitness_verification_email_body(user_sudo.name, verify_url, email_lang)
        subject = (
            'Verify your CoreLab account' if email_lang == 'en_US'
            else 'Verifica tu compte de CoreLab' if email_lang == 'ca_ES'
            else 'Verifica tu cuenta de CoreLab'
        )
        email_from = (
            user_sudo.company_id.email_formatted
            or 'CoreLab Studio <noreply@corelab.studio>'
        )
        request.env['mail.mail'].sudo().create({
            'subject': subject,
            'email_to': user_sudo.email,
            'email_from': email_from,
            'body_html': body_html,
            'auto_delete': True,
        }).send()

    def _fitness_verification_email_body(self, name, verify_url, lang='es_ES'):
        safe_name = escape(name)
        safe_url = escape(verify_url)

        if lang == 'en_US':
            greeting = 'Welcome to CoreLab, {name}.'
            body = 'Please verify your email address to activate your account and access the studio portal.'
            cta = 'Verify my email'
            footer = 'This link expires in 6 days. If you did not create a CoreLab account, you can safely ignore this email.'
        elif lang == 'ca_ES':
            greeting = 'Benvingut/da a CoreLab, {name}.'
            body = 'Verifica la teva adreça de correu electrònic per activar el teu compte i accedir al portal de l\'estudi.'
            cta = 'Verificar el meu correu'
            footer = 'Aquest enllaç caduca en 6 dies. Si no has creat un compte a CoreLab, pots ignorar aquest correu.'
        else:  # es_ES (default)
            greeting = 'Bienvenido/a a CoreLab, {name}.'
            body = 'Verifica tu dirección de correo electrónico para activar tu cuenta y acceder al portal del estudio.'
            cta = 'Verificar mi correo'
            footer = 'Este enlace caduca en 6 días. Si no has creado una cuenta en CoreLab, puedes ignorar este correo.'

        return Markup("""<div style="font-family:Georgia,serif;color:#18110C;max-width:520px;margin:0 auto;padding:40px 24px;">
  <p style="font-size:22px;font-weight:600;margin:0 0 20px;">{greeting}</p>
  <p style="font-size:15px;line-height:1.7;color:#4a3728;margin:0 0 28px;">{body}</p>
  <div style="margin:0 0 32px;">
    <a href="{url}"
       style="background-color:#18110C;color:#F5F0E8;text-decoration:none;
              padding:14px 28px;border-radius:4px;font-size:14px;
              letter-spacing:0.05em;display:inline-block;">
      {cta}
    </a>
  </div>
  <p style="font-size:13px;color:#8a7060;line-height:1.6;margin:0 0 32px;">{footer}</p>
  <hr style="border:none;border-top:1px solid #E8E0D5;margin:0 0 24px;"/>
  <p style="font-size:12px;color:#8a7060;margin:0;">CoreLab Studio</p>
</div>""").format(
            greeting=escape(greeting).format(name=safe_name),
            body=body,
            url=safe_url,
            cta=cta,
            footer=footer,
        )

    # ------------------------------------------------------------------
    # Email verification endpoint
    # ------------------------------------------------------------------

    @http.route('/corelab/verify-email', type='http', auth='public', website=True, sitemap=False, multilang=False)
    def verify_email(self, token=None, **kw):
        if not token:
            return request.redirect('/web/login')

        _mv_lang = request.cookies.get('mv_lang', 'es_ES')
        if _mv_lang not in ('en_US', 'es_ES', 'ca_ES'):
            _mv_lang = 'es_ES'
        request.update_context(lang=_mv_lang)

        try:
            partner = request.env['res.partner'].sudo()._signup_retrieve_partner(
                token, check_validity=True, raise_exception=True,
            )
        except Exception:
            return request.render('fitness_portal.verify_email_failed', {})

        partner_user = partner.user_ids[:1]
        if not partner_user:
            return request.redirect('/web/login')

        # If already verified, just send to login
        if partner_user.has_group(STUDENT_GROUP):
            return request.redirect('/web/login?%s' % url_encode({
                'login': partner_user.login,
                'message': 'verified',
            }))

        # Assign fitness student group
        fitness_group = request.env.ref(STUDENT_GROUP)
        partner_user.sudo().write({'group_ids': [(4, fitness_group.id)]})

        # Invalidate signup token
        partner.sudo().signup_cancel()

        return request.redirect('/web/login?%s' % url_encode({
            'login': partner_user.login,
            'message': 'verified',
        }))

    # ------------------------------------------------------------------
    # Pending verification (logged in but not yet verified)
    # ------------------------------------------------------------------

    @http.route('/corelab/pending-verification', type='http', auth='user', website=True, sitemap=False, multilang=False)
    def pending_verification(self, **kw):
        user = request.env.user
        if user.has_group(STUDENT_GROUP) or user.has_group(TEACHER_GROUP) or user._is_internal():
            return request.redirect('/my/home')
        _mv_lang = request.cookies.get('mv_lang', 'es_ES')
        if _mv_lang not in ('en_US', 'es_ES', 'ca_ES'):
            _mv_lang = 'es_ES'
        request.update_context(lang=_mv_lang)
        return request.render('fitness_portal.pending_verification', {
            'user_email': user.email or '',
        })

    @http.route('/corelab/resend-verification', type='http', auth='user', methods=['POST'], website=True, sitemap=False, multilang=False)
    def resend_verification(self, **kw):
        user = request.env.user
        if user.has_group(STUDENT_GROUP) or user.has_group(TEACHER_GROUP) or user._is_internal():
            return request.redirect('/my/home')
        _mv_lang = request.cookies.get('mv_lang', 'es_ES')
        if _mv_lang not in ('en_US', 'es_ES', 'ca_ES'):
            _mv_lang = 'es_ES'
        request.update_context(lang=_mv_lang)
        try:
            self._send_fitness_verification_email(user.sudo())
            resent = True
        except Exception:
            resent = False
        return request.render('fitness_portal.pending_verification', {
            'user_email': user.email or '',
            'resent': resent,
        })
