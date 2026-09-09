import logging
import re
import pytz
from odoo import models, fields, api, _
from odoo.exceptions import UserError


# The studio, the site and the portal are Spanish-first, so anything with
# no language set falls back to Spanish rather than to Odoo's English base.
DEFAULT_LANG = 'es_ES'

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
    # Set when a logged-in student submits from the portal. Public website
    # submissions leave it empty and are matched by email at approval time -
    # this model predates the portal flow and was written for people with no
    # account, which is why name/email are free text rather than a partner.
    partner_id = fields.Many2one(
        'res.partner',
        string='Student',
        ondelete='set null',
        index=True,
        help="The student's contact record, when the request came from a "
             "logged-in portal user. Approval books against this partner; if "
             "it is empty the email address is looked up instead.",
    )
    phone = fields.Char(string='Phone')
    preferred_time_notes = fields.Text(string='Preferred Day / Time')
    occurrence_id = fields.Many2one(
        'calendar.event',
        string='Class Slot',
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
    confirmation_email_sent = fields.Boolean(
        string='Confirmation Email Sent', default=False, copy=False
    )
    confirmation_email_sent_date = fields.Datetime(
        string='Confirmation Sent On', readonly=True, copy=False
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
            lang = rec.lang or DEFAULT_LANG
            days = _DAY_NAMES.get(lang, _DAY_NAMES[DEFAULT_LANG])
            months = _MONTH_NAMES.get(lang, _MONTH_NAMES[DEFAULT_LANG])
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
                # Barre with a pre-selected slot: notify admin; student confirmation is sent manually
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

        # Capture previous statuses for post-write side effects
        prev_status = {}
        if 'status' in vals or 'scheduled_datetime' in vals:
            prev_status = {r.id: r.status for r in self}

        result = super().write(vals)

        if prev_status:
            if vals.get('status') == 'declined':
                for rec in self:
                    rec._send_declined_email()

            # Reset confirmation tracking whenever a record leaves 'scheduled'
            reset_ids = [
                r.id for r in self
                if prev_status.get(r.id) == 'scheduled' and r.status != 'scheduled'
            ]
            if reset_ids:
                self.env.cr.execute(
                    "UPDATE fitness_trial_request "
                    "SET confirmation_email_sent = FALSE, confirmation_email_sent_date = NULL "
                    "WHERE id = ANY(%s)",
                    [reset_ids],
                )
                self.browse(reset_ids).invalidate_recordset(
                    ['confirmation_email_sent', 'confirmation_email_sent_date']
                )

            # Entering 'scheduled' sends the student their confirmation. This
            # was meant to happen all along but no branch ever did it, so the
            # email waited on somebody remembering to press a second button
            # after approving - which is the gap Approve & Book exists to
            # close. Keyed on the transition, so it fires however the record
            # got here (the approval action, the statusbar, or the datetime
            # auto-advance above) and only once.
            newly_scheduled = self.filtered(
                lambda r: r.status == 'scheduled'
                and prev_status.get(r.id) != 'scheduled'
                and not r.confirmation_email_sent
            )
            for rec in newly_scheduled:
                rec._send_scheduled_email()
                rec._notify_scheduled_in_app()
            if newly_scheduled:
                # Written with SQL for the same reason the reset above is:
                # recording the send from inside write() would recurse.
                self.env.cr.execute(
                    "UPDATE fitness_trial_request "
                    "SET confirmation_email_sent = TRUE, "
                    "    confirmation_email_sent_date = %s "
                    "WHERE id = ANY(%s)",
                    [fields.Datetime.now(), newly_scheduled.ids],
                )
                newly_scheduled.invalidate_recordset(
                    ['confirmation_email_sent', 'confirmation_email_sent_date']
                )

        return result

    # ── Approval ────────────────────────────────────────────────────────
    TRIAL_PRODUCT_XMLID = {
        'barre': 'fitness_packages.product_barre_trial',
        'reformer': 'fitness_packages.product_reformer_trial',
    }

    def _resolve_partner(self):
        """The student this request belongs to.

        partner_id is set when a logged-in student submits from the portal.
        Public website submissions have no account, so fall back to matching
        the email address - case-insensitively, and only on a customer record.
        """
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        if not self.email:
            return self.env['res.partner'].browse()
        return self.env['res.partner'].sudo().search(
            [('email', '=ilike', self.email.strip())], limit=1)

    def _trial_product(self):
        self.ensure_one()
        xmlid = self.TRIAL_PRODUCT_XMLID.get(self.class_interest or 'barre')
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _existing_trial_credit(self, partner, product):
        """An unused, unexpired credit for this trial product, if any."""
        today = fields.Date.context_today(self)
        lines = self.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id', 'in', product.product_variant_ids.ids),
            ('fitness_remaining_classes', '>', 0),
            ('state', '=', 'sale'),
        ])
        return lines.filtered(
            lambda l: not l.fitness_validity_end_date
            or l.fitness_validity_end_date >= today)[:1]

    def _trial_already_claimed(self, partner, product):
        """Mirrors the portal's rule: a confirmed, zero-cost order of this
        product means the free trial has been used."""
        orders = self.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'sale'),
        ])
        for order in orders:
            for line in order.order_line:
                if (line.product_id.product_tmpl_id.id == product.id
                        and float(order.amount_total or 0.0) == 0.0):
                    return True
        return False

    def action_approve_and_book(self):
        """Approve the request and actually book the student in."""
        self.ensure_one()

        if not self.occurrence_id:
            raise UserError(_(
                "Choose a class slot first. Approval books the student into "
                "that class, so there has to be one."))
        if self.occurrence_id.class_state == 'cancelled':
            raise UserError(_("That class has been cancelled. Pick another slot."))

        # The picker is scoped to the right discipline, but a slot chosen
        # before that scoping - or set from anywhere other than the form -
        # would otherwise reach the booking's discipline check and fail with a
        # message about missing subscriptions, which describes neither the
        # cause nor the fix.
        slot_discipline = self.occurrence_id.class_type_id.classroom_type
        if slot_discipline and self.class_interest \
                and slot_discipline != self.class_interest:
            raise UserError(_(
                "%(cls)s is a %(slot)s class, but this is a %(want)s trial "
                "request. Pick a %(want)s class.",
                cls=self.occurrence_id.name or _("That class"),
                slot=slot_discipline,
                want=self.class_interest))

        partner = self._resolve_partner()
        if not partner:
            raise UserError(_(
                "No student record matches this request. It was submitted from "
                "the public site by %(email)s, and nobody with that address has "
                "an account yet.", email=self.email or '-'))

        product = self._trial_product()
        if not product:
            raise UserError(_("The trial product for this discipline is missing."))

        credit = self._existing_trial_credit(partner, product)
        if not credit:
            if self._trial_already_claimed(partner, product):
                raise UserError(_(
                    "%(name)s has already used their free trial, and has no "
                    "credit left to book with. Sell them a class instead, or "
                    "book it from the back office.", name=partner.name))
            variant = product.product_variant_ids[:1]
            if not variant:
                raise UserError(_("The trial product has no variant to sell."))
            # The promotion price, not the list price. Leaving price_unit off
            # let Odoo fill in the list price, so approving a *free* trial
            # raised a 15 EUR order: the student was billed for the thing the
            # studio advertises as free, and because the once-per-student rule
            # recognises a claimed trial by its zero total, the order did not
            # count as a claim either - so the rule stopped applying to every
            # trial granted this way. This is the same call the portal's
            # one-tap booking makes, for the same reason.
            order = self.env['sale.order'].sudo().create({
                'partner_id': partner.id,
                'order_line': [(0, 0, {
                    'product_id': variant.id,
                    'product_uom_qty': 1,
                    'price_unit': product.fitness_effective_price(),
                })],
            })
            order.action_confirm()
            _logger.info(
                "[TRIAL] Free trial order %s confirmed for partner %s from request %s",
                order.name, partner.id, self.id)

        # Students may only book 7 days out. Approval is the opposite case:
        # the studio is placing someone into a slot it picked, and the slot it
        # picks is routinely further out than that - so the approval carried
        # the student's restriction and simply refused. The override lifts that
        # one rule and nothing else; capacity, duplicates, discipline match and
        # the cancellation window all still apply. The booking model re-checks
        # group membership before honouring it, so this cannot widen anyone's
        # rights - it only stops a manager's own action from being blocked by
        # a rule that was never meant for them.
        is_manager = (self.env.user.has_group('fitness_core.group_fitness_manager')
                      or self.env.user.has_group('base.group_system'))
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': partner.id,
            'calendar_event_id': self.occurrence_id.id,
            'manager_override_timewindow': is_manager,
        })
        _logger.info(
            "[TRIAL] Request %s approved: booking %s created for partner %s "
            "on event %s", self.id, booking.id, partner.id, self.occurrence_id.id)

        vals = {'status': 'scheduled'}
        if not self.scheduled_datetime:
            vals['scheduled_datetime'] = self.occurrence_id.start
        if not self.partner_id:
            vals['partner_id'] = partner.id
        self.write(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Booked"),
                'message': _("%(name)s is booked into %(cls)s.",
                             name=partner.name,
                             cls=self.occurrence_id.name or _("the class")),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_send_confirmation_email(self):
        self.ensure_one()
        self._send_scheduled_email()
        self.write({
            'confirmation_email_sent': True,
            'confirmation_email_sent_date': fields.Datetime.now(),
        })

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

    def _notify_scheduled_in_app(self):
        """Ring the student's bell when their trial is scheduled.

        The email and the in-app notification had drifted apart. The email
        fires on this status change; the notification only ever came from
        fitness.booking.create(), so scheduling a request without using
        Approve & Book - which is what setting the status by hand does - sent
        the email and rang nothing. Every scheduled request in the database
        had zero bookings behind it, so nobody had ever been notified in-app.

        Skipped when a booking already exists for this slot and student: that
        path notifies on its own, and two bells for one class is worse than
        the one that was missing.
        """
        self.ensure_one()
        # fitness_notifications is not a dependency of this module - the bell
        # is an optional part of the suite - so this asks rather than assumes,
        # the same way the portal checks for the subscription app before
        # setting a plan. Without it the email still goes out.
        if 'fitness.notification' not in self.env:
            return
        partner = self._resolve_partner()
        if not partner:
            return
        user = self.env['res.users'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1)
        if not user:
            return          # a request from someone with no portal account

        if self.occurrence_id:
            already = self.env['fitness.booking'].sudo().search_count([
                ('student_id', '=', partner.id),
                ('calendar_event_id', '=', self.occurrence_id.id),
            ])
            if already:
                return      # the booking notified them already

        when = self.scheduled_datetime or (
            self.occurrence_id.start if self.occurrence_id else False)
        cls = self.occurrence_id.name if self.occurrence_id else ''
        if cls and when:
            body = _("%(cls)s on %(when)s.", cls=cls,
                     when=fields.Datetime.context_timestamp(self, when)
                     .strftime('%d %b %H:%M'))
        elif cls:
            body = _("Your trial class: %(cls)s.", cls=cls)
        else:
            body = _("The studio will confirm the details with you shortly.")

        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'booking_confirmed',
            _("Your trial class is confirmed"),
            body=body,
            action_url='/my/classes',
        )
        _logger.info(
            "[TRIAL] In-app notification sent to user %s for request %s",
            user.id, self.id)

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
