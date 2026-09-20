# -*- coding: utf-8 -*-
"""Tell the studio when class generation has stopped.

fitness_core detects it - it owns the schedules and can measure whether they
are still generated far enough ahead - but it cannot reach the notification
model, which lives here, downstream of it. So core leaves a seam and this
fills it.

Worth alerting on because the failure is both silent and total. The nightly
job swallows a failing schedule so one bad row cannot stop the rest, which
means it reports success while generating nothing. Nobody notices until the
timetable runs dry, and then it fails for everybody at once: classes cannot
be booked, and every Clase Fija renewal fails together with "no occurrences
found".
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class FitnessClassSchedule(models.Model):
    _inherit = 'fitness.class.schedule'

    @api.model
    def _notify_generation_stalled(self, stale, reason, detail):
        """Notify every manager, in their own language.

        Sent once per run rather than once per schedule: twelve schedules
        going stale is one fault, and twelve notifications for it is how an
        alert gets muted.
        """
        managers = self.env['res.users'].sudo().search([
            ('group_ids', 'in', [
                self.env.ref('fitness_core.group_fitness_manager').id]),
        ])
        if not managers:
            _logger.warning(
                "[SCHEDULE HEALTH] generation has stalled and there is no "
                "manager to tell: %s", reason)
            return False

        Notif = self.env['fitness.notification'].sudo()
        for manager in managers:
            # Written out in full rather than through an alias. Odoo's
            # extractor only recognises calls literally spelled `_(...)`, so
            # `translate = env(...)._` puts nothing in the catalogue at all
            # and every manager quietly gets English.
            lang_env = self.env(context=dict(
                self.env.context, lang=manager.lang or 'es_ES'))
            title = lang_env._("Classes are no longer being scheduled")
            body = lang_env._(
                "%(reason)s\n\n%(detail)s\n\n"
                "Until this is fixed, students cannot book the weeks that were "
                "never created, and members with a fixed weekly class will "
                "have nothing booked when their membership renews."
            ) % {'reason': reason, 'detail': detail}
            Notif._create_for_user(manager.id, 'generation_stalled', title, body)

        _logger.info("[SCHEDULE HEALTH] alerted %s manager(s)", len(managers))
        return True
