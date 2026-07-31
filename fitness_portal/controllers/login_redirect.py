from odoo.addons.web.controllers.home import Home
from odoo.http import request

STUDENT_GROUP = 'fitness_core.group_fitness_student'


class FitnessHome(Home):
    """Students land on the CoreLab Home tab after signing in, instead of the
    Profile page. An explicit ?redirect= is always respected."""

    def _login_redirect(self, uid, redirect=None):
        if not redirect:
            user = request.env['res.users'].sudo().browse(uid)
            if user.has_group(STUDENT_GROUP):
                return '/my/home'
        return super()._login_redirect(uid, redirect=redirect)
