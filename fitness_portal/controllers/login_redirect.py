from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.http import request

STUDENT_GROUP = 'fitness_core.group_fitness_student'

# Generic destinations that are not meaningful to students — intercept these
# and send students to the Home tab instead.
_GENERIC_REDIRECTS = {'/my', '/web', '/web#action=', '', '/odoo'}


class FitnessHome(Home):
    """Students always land on /my/home after signing in.

    Two-layer approach:
    1. _login_redirect — handles cases where redirect is None or a generic path,
       runs early in the MRO before portal converts None → '/my'.
    2. web_login — post-login safety net: fires after the entire super() chain
       completes and overrides the destination for any successful student POST login.
       Catches the direct /web/login entry point (no redirect param) where portal's
       MRO intercepts redirect=None and converts it to '/my' before our super()
       call in _login_redirect can see '/my' as a generic path."""

    def _login_redirect(self, uid, redirect=None):
        user = request.env['res.users'].sudo().browse(uid)
        if user.has_group(STUDENT_GROUP):
            if not redirect or redirect in _GENERIC_REDIRECTS:
                return '/my/home'
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)
        # Post-login safety net: for any successful student POST login, override
        # the destination to /my/home regardless of what the redirect chain decided.
        # This ensures direct external links (/web/login with no redirect param)
        # behave the same as the internal PWA login flow.
        if (request.httprequest.method == 'POST'
                and request.params.get('login_success')
                and request.session.uid):
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user.has_group(STUDENT_GROUP):
                return request.redirect('/my/home')
        return response
