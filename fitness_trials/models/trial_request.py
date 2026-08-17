import logging
import re
import pytz
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

_DAY_NAMES = {
    'en_US': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
    'es_ES': ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'],
    'ca_ES': ['Dilluns', 'Dimarts', 'Dimecres', 'Dijous', 'Divendres', 'Dissabte', 'Diumenge'],
}
_MONTH_NAMES = {
    'en_US': ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December'],
    'es_ES': ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
              'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
    'ca_ES': ['gener', 'febrer', 'març', 'abril', 'maig', 'juny',
              'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre'],
}
_STUDIO_TZ = pytz.timezone('Europe/Madrid')


class FitnessTrialRequest(models.Model):
    _name = 'fitness.trial.request'
    _description = 'Trial Class Request'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True)
    email = fields.Char(string='Email', required=True)
    phone = fields.Char(string='Phone')
    preferred_time_notes = fields.Text(string='Preferred Day / Time')
    occurrence_id = fields.Many2one(
        'calendar.event',
        string='Barre Class Slot',
        ondelete='set null',
        index=True,
    )
    lang = fields.Char(string='Language', default='es_ES')
    class_interest = fields.Selection(
        selection=[
            ('barre', 'Barre'),
            ('reformer', 'Reformer'),
        ],
        string='Class Interest',
        required=True,
        default='barre',
        index=True,
    )
    # Reformer-specific intake questions
    reformer_is_first_time = fields.Selection(
        selection=[
            ('yes', 'Yes'),
            ('no', 'No'),
        ],
        string='First time with Reformer Pilates?',
    )
    reformer_years_experience = fields.Char(string='Years of Reformer Experience')
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('contacted', 'Contacted'),
            ('scheduled', 'Scheduled'),
            ('declined', 'Declined'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
    )
    scheduled_datetime = fields.Datetime(string='Scheduled Date/Time')
    scheduled_datetime_display = fields.Char(
        string='Formatted Date/Time',
        compute='_compute_scheduled_datetime_display',
        store=False,
    )
    create_date = fields.Datetime(string='Received On', readonly=True)

    @api.depends('scheduled_datetime', 'lang')
    def _compute_scheduled_datetime_display(self):
        for rec in self:
            if not rec.scheduled_datetime:
                rec.scheduled_datetime_display = ''
                continue
            dt_utc = rec.scheduled_datetime.replace(tzinfo=pytz.UTC)
            dt_local = dt_utc.astimezone(_STUDIO_TZ)
            lang = rec.lang or 'en_US'
            days = _DAY_NAMES.get(lang, _DAY_NAMES['en_US'])
            months = _MONTH_NAMES.get(lang, _MONTH_NAMES['en_US'])
            rec.scheduled_datetime_display = (
                f"{days[dt_local.weekday()]}, {dt_local.day} "
                f"{months[dt_local.month - 1]} {dt_local.year} · "
                f"{dt_local.strftime('%H:%M')}"
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.class_interest == 'reformer':
                pass  # held for admin review; no email at creation
            elif rec.status == 'scheduled':
                # Barre with a pre-selected slot: confirm immediately
                rec._send_scheduled_email()
                rec._send_barre_admin_notification()
            else:
                rec._send_pending_email()
        return records

    def write(self, vals):
        # Auto-advance to 'scheduled' when a datetime is saved without an explicit status change
        if vals.get('scheduled_datetime') and 'status' not in vals:
            pre_schedule = self.filtered(lambda r: r.status in ('pending', 'contacted'))
            if pre_schedule:
                vals = dict(vals, status='scheduled')

        # Capture the "schedulable" state before write to detect transitions
        prev = {}
        if 'status' in vals or 'scheduled_datetime' in vals:
            prev = {
                r.id: (r.status == 'scheduled' and bool(r.scheduled_datetime))
                for r in self
            }
        result = super().write(vals)
        if prev:
            for rec in self:
                was = prev.get(rec.id, False)
                is_now = (rec.status == 'scheduled' and bool(rec.scheduled_datetime))
                if not was and is_now:
                    rec._send_scheduled_email()
            # Handle declined transition separately
            if vals.get('status') == 'declined':
                for rec in self:
                    rec._send_declined_email()
        return result

    def _send_pending_email(self):
        template = self.env.ref(
            'fitness_trials.mail_template_trial_pending', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=True, raise_exception=False)
        except Exception:
            _logger.exception("Trial pending email failed for record %s", self.id)

    def _send_scheduled_email(self):
        template = self.env.ref(
            'fitness_trials.mail_template_trial_scheduled', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=True, raise_exception=False)
        except Exception:
            _logger.exception("Trial scheduled email failed for record %s", self.id)

    def _send_barre_admin_notification(self):
        template = self.env.ref(
            'fitness_trials.mail_template_barre_trial_admin', raise_if_not_found=False
        )
        if not template:
            return
        admin_email = self.env.company.email
        if not admin_email:
            _logger.warning("No company email set; skipping admin notification for trial %s", self.id)
            return
        try:
            template.sudo().send_mail(
                self.id,
                force_send=True,
                raise_exception=False,
                email_values={'email_to': admin_email},
            )
        except Exception:
            _logger.exception("Barre admin notification failed for record %s", self.id)

    def _send_declined_email(self):
        template = self.env.ref(
            'fitness_trials.mail_template_trial_declined', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=True, raise_exception=False)
        except Exception:
            _logger.exception("Trial declined email failed for record %s", self.id)
