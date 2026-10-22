from datetime import timedelta

from odoo import models, fields, api
from odoo.tools import format_datetime

from odoo.addons.fitness_core.models.studio_lang import recipient_lang, studio_date

import logging

_logger = logging.getLogger(__name__)

# The studio's own timezone, used when a student has none set on their user.
# Matches DEFAULT_TZ in fitness_core's schedule and closure-day models.
# The studio's clock, and the only clock these messages use.
#
# This used to be `user.tz or STUDIO_TZ`, which meant a reminder was written in
# whatever timezone happened to be on the account - set by the browser at
# signup, or by whoever created it, rarely by the student. The portal now shows
# every class on studio time, so a mail on a different clock would contradict
# the page it links to. A class at 07:00 in Madrid is at 07:00 in the email too.
STUDIO_TZ = 'Europe/Madrid'


class FitnessBookingNotifications(models.Model):
    """Extends fitness.booking with email notifications on booking lifecycle events.

    Hooks ONLY the two existing student-facing events (create() = booking confirmed,
    action_cancel() = booking cancelled) — never calendar.event field changes such as
    a teacher swap. A future fitness_teacher_swap module can pass
    context={'skip_fitness_notification': True} on any write it makes to guarantee no
    student email is ever emitted as a side effect of a teacher change; this module
    itself never touches calendar.event at all, so swaps are silent by construction.
    """
    _inherit = 'fitness.booking'

    reminder_sent = fields.Boolean(
        "Reminder Sent",
        default=False,
        readonly=True,
        help="Set once the class-reminder cron has emailed this booking's student. "
             "Prevents duplicate reminders.",
    )
    bell_reminder_sent = fields.Boolean(
        "Bell Reminder Sent",
        default=False,
        readonly=True,
        help="Set once the 6–12h bell-notification cron has fired for this booking. "
             "Prevents duplicate in-app reminders.",
    )

    @api.model
    def _notif_enabled(self, key):
        """key in {'send_confirmation', 'send_cancellation', 'send_reminder'}"""
        value = self.env['ir.config_parameter'].sudo().get_param(f'fitness_notifications.{key}', 'True')
        return str(value).lower() in ('true', '1')

    def _send_notification(self, template_xmlid):
        if self.env.context.get('skip_fitness_notification'):
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning("[NOTIFICATIONS] Template %s not found, skipping send.", template_xmlid)
            return
        for booking in self:
            # Some students have no email address at all, on purpose - see
            # RUNBOOK-students-without-email.md. send_mail() does not care:
            # it builds the mail.mail anyway, and mail.mail._send() then
            # parks it in state='exception' with failure_type
            # 'mail_email_missing'. That is not a skip, it is a permanent
            # failure sitting in the outgoing queue for somebody to
            # investigate, once per booking, for ever.
            #
            # The bell notification is her channel and fires regardless, so
            # nothing reaches her any later for not queueing this.
            if not booking.student_id.email:
                _logger.info(
                    "[NOTIFICATIONS] %s has no email address; %s not queued "
                    "(the in-app notification still fires)",
                    booking.student_id.display_name, template_xmlid)
                continue
            try:
                template.sudo().send_mail(booking.id, force_send=False)
                _logger.info("[NOTIFICATIONS] Queued %s for booking %s (student=%s)",
                             template_xmlid, booking.id, booking.student_id.name)
            except Exception:
                _logger.exception("[NOTIFICATIONS] Failed to queue %s for booking %s",
                                   template_xmlid, booking.id)

    # ─── Moved to another class ─────────────────────────────────────────────

    def _notify_moved(self, origin_event):
        """Tell the student the studio moved them, by mail and by the bell.

        Overrides the no-op hook in fitness_bookings. Deliberately its own
        message rather than reusing the booking confirmation: a confirmation
        for a class they never chose reads like a mistake, and says nothing
        about the class they are no longer in.

        Reuses the class_rescheduled bell type - from the student's side, "the
        class you are going to has changed" is the same news whether the studio
        moved the class or moved them.
        """
        for booking in self:
            if self.env.context.get('skip_fitness_notification'):
                continue
            if self._notif_enabled('send_confirmation'):
                booking._send_notification(
                    'fitness_notifications.mail_template_booking_moved')

            user = booking.student_id.user_ids[:1]
            if not user:
                continue
            event = booking.calendar_event_id
            lang_env = self.with_context(lang=recipient_lang(self.env, user))
            when = ''
            if event.start:
                try:
                    when = format_datetime(
                        lang_env.env, event.start, tz=STUDIO_TZ,
                        dt_format='d MMM HH:mm',
                        lang_code=recipient_lang(self.env, user))
                except Exception:
                    when = event.start.strftime('%d %b %H:%M')
            from_name = origin_event.name if origin_event else ''
            if from_name and when:
                body = lang_env.env._(
                    'The studio moved you from %(old)s to %(new)s on %(when)s. '
                    'Your credit is unchanged.',
                    old=from_name, new=event.name or '', when=when)
            else:
                body = lang_env.env._(
                    'The studio moved you to %(new)s. Your credit is unchanged.',
                    new=event.name or '')
            # Whoever moved them may have said why. Appended rather than woven
            # in: the sentence above is the news, and the studio's own words
            # should arrive as the studio wrote them.
            why = (self.env.context.get('move_reason') or '').strip()
            if why:
                body = '%s %s' % (body, lang_env.env._('Reason: %(why)s', why=why))
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id, 'class_rescheduled',
                lang_env.env._('Your class has been changed'),
                body, action_url='/my/schedule')

    # ─── Booking confirmed (create) ─────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        bookings = super().create(vals_list)
        if self._notif_enabled('send_confirmation'):
            bookings._send_notification('fitness_notifications.mail_template_booking_confirmation')
        for booking in bookings:
            self._maybe_notify_booking_confirmed(booking)
            self._maybe_notify_instructor(booking)
            self._maybe_notify_credit_used(booking)
            self._maybe_notify_credit_low(booking)
            self._maybe_notify_credit_zero(booking)
        return bookings

    def _maybe_notify_booking_confirmed(self, booking):
        """In-app bell for a new booking.

        booking_confirmed was declared on the model, decorated in the admin list
        and offered as an admin filter, but nothing ever created one — which is
        why it had no action_url to fix: it had no call site at all. The email
        went out and the bell stayed silent, even though cancelling the same
        booking did ring it.
        """
        if self.env.context.get('skip_fitness_notification'):
            return
        user = booking.student_id.user_ids[:1]
        if not user:
            return
        class_name = booking.calendar_event_id.name or 'class'
        event_start = booking.calendar_event_id.start
        lang_env = self.with_context(lang=recipient_lang(self.env, user))
        # Locale-aware and in the student's timezone: strftime would hand a
        # Spanish reader "02 Sep" on a UTC clock. Same helper the dashboard
        # uses, with its strftime fallback if babel is unavailable.
        start_str = ''
        if event_start:
            try:
                start_str = format_datetime(
                    lang_env.env, event_start, tz=STUDIO_TZ,
                    dt_format='d MMM HH:mm', lang_code=recipient_lang(self.env, user))
            except Exception:
                start_str = event_start.strftime('%d %b %H:%M')
        body = (lang_env.env._('Your place is booked for %(cls)s on %(when)s.',
                               cls=class_name, when=start_str)
                if start_str else
                lang_env.env._('Your place is booked for %(cls)s.', cls=class_name))
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'booking_confirmed',
            lang_env.env._('Booking confirmed: %(cls)s', cls=class_name),
            body,
            # Same destination as booking_cancelled and class_reminder: the
            # class list is where you go to see what you just booked.
            action_url='/my/classes',
        )

    def _maybe_notify_instructor(self, booking):
        """Tell the instructor a student has been booked into her class.

        Nobody did. Every recipient on the booking path was the student;
        the only notice an instructor ever got was when a class's own
        teacher changed. Maridelvis had nothing for a 1-on-1 with Carlota
        on 16 October and found out by looking.

        Bell and push through _create_for_user, the same road the swap
        notice takes, in her own language and on studio time. Once per
        booking, because a booking is created once. Not for:

          * a class that has already started - a booking made then is a
            recording after the fact, and she was in the room;
          * the Clase Fija placement, which books a whole quarter at once
            and would bury her;
          * a caller that asked for silence.
        """
        ctx = self.env.context
        if ctx.get('skip_fitness_notification') \
                or ctx.get('_fitness_clase_fija_placement'):
            return
        event = booking.calendar_event_id.sudo()
        teacher = event.user_id
        if not teacher or not event.start \
                or event.start <= fields.Datetime.now():
            return
        lang = recipient_lang(self.env, teacher)
        tenv = self.with_context(lang=lang)
        class_name = event.name or 'class'
        try:
            when = format_datetime(tenv.env, event.start, tz=STUDIO_TZ,
                                   dt_format='d MMM HH:mm', lang_code=lang)
        except Exception:
            when = event.start.strftime('%d %b %H:%M')
        self.env['fitness.notification'].sudo()._create_for_user(
            teacher.id,
            'student_booked',
            tenv.env._('New booking: %(cls)s', cls=class_name),
            tenv.env._('%(student)s is booked into your class %(cls)s on '
                       '%(when)s.',
                       student=booking.student_id.sudo().name or '',
                       cls=class_name, when=when),
            action_url='/my/instructor/classes/%d' % event.id,
        )

    def _maybe_notify_credit_used(self, booking):
        """Notify student when a credit pack credit is used for a booking.
        Skipped for subscription bookings (no pack credits involved).
        """
        # Silent like booking_confirmed beside it: a booking made under
        # skip_fitness_notification - a walk-in recorded at the desk, a
        # bulk placement - must not ring her about the credit it spent.
        if self.env.context.get('skip_fitness_notification'):
            return
        if not booking.package_order_line_id:
            return
        partner = booking.student_id
        user = partner.user_ids[:1]
        if not user:
            return
        line = booking.package_order_line_id
        remaining = line.fitness_remaining_classes or 0
        class_name = booking.calendar_event_id.name or 'class'
        lang_env = self.with_context(lang=recipient_lang(self.env, user))
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_used',
            lang_env.env._('1 credit used for %s', class_name),
            lang_env.env._('%d credit(s) remaining in this pack.', remaining),
            action_url='/my/packages',
        )

    @api.model
    def _fitness_membership_still_gives(self, partner):
        """Whether a running membership still gives her classes.

        Unlimited, a weekly allowance (it renews every week), or floating
        credits left. A running membership with none of these - an
        allowance of 0 and nothing floating - is the only one that is
        really out of classes.
        """
        subs = self.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('is_subscription', '=', True),
            ('subscription_state', '=', '3_progress'),
        ])
        return any(s.fitness_is_unlimited
                   or (s.fitness_effective_weekly_allowance() or 0) > 0
                   or (s.fitness_floating_credits or 0) > 0
                   for s in subs)

    def _maybe_notify_credit_zero(self, booking):
        """Notify student when their total credit balance across all packs hits zero."""
        # Silent like booking_confirmed beside it: a booking made under
        # skip_fitness_notification - a walk-in recorded at the desk, a
        # bulk placement - must not ring her about the credit it spent.
        if self.env.context.get('skip_fitness_notification'):
            return
        partner = booking.student_id
        user = partner.user_ids[:1]
        if not user:
            return
        all_lines = self.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        if all_lines:
            return
        # A running membership is not "no credits". This only ever counted
        # packs, so a member booking with her membership - and every class
        # placed for a fixed-class member - was told she had used her last
        # credit while her membership still gave her classes every week.
        if self._fitness_membership_still_gives(partner):
            return
        recent = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'credit_zero'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=24)),
        ], limit=1)
        if recent:
            return
        lang_env = self.with_context(lang=recipient_lang(self.env, user))
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_zero',
            lang_env.env._('No credits remaining'),
            lang_env.env._('You have used your last credit. Visit Packages to purchase more.'),
            action_url='/my/packages',
        )

    def _maybe_notify_credit_low(self, booking):
        """Tell her when what she has left for this kind of class drops to 1.

        This used to take limit=1 on ANY of her lines with one credit left
        - expired, on a cancelled order, another discipline - and report
        that line's count as her balance. Carlota was told "only 1 credit
        left" while holding five: a Reformer private pack with four, and an
        old single with one.

        Now it counts what could pay for another class like the one just
        booked: the spendable lines (the shared rule - live order, not
        expired) that cover it (fitness_covering, the engine's own filter),
        summed. The threshold is unchanged.
        """
        LOW_THRESHOLD = 1
        # Silent like booking_confirmed beside it: a booking made under
        # skip_fitness_notification - a walk-in recorded at the desk, a
        # bulk placement - must not ring her about the credit it spent.
        if self.env.context.get('skip_fitness_notification'):
            return
        partner = booking.student_id
        SOL = self.env['sale.order.line'].sudo()
        lines = SOL.search(SOL._fitness_spendable_domain(partner=partner)
                           ).fitness_covering(booking.calendar_event_id)
        remaining = sum(lines.mapped('fitness_remaining_classes'))
        if not 0 < remaining <= LOW_THRESHOLD:
            return
        user = partner.user_ids[:1]
        if not user:
            return
        recent = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'credit_low'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=24)),
        ], limit=1)
        if recent:
            return
        lang_env = self.with_context(lang=recipient_lang(self.env, user))
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_low',
            lang_env.env._('Only %d credit(s) left', remaining),
            lang_env.env._('Running low on credits. Browse packages to top up.'),
            action_url='/my/packages',
        )

    # ─── Booking cancelled ───────────────────────────────────────────────────────

    def action_cancel(self):
        # Who is cancelling, and whether it is late, can only be read before
        # the cancel: afterwards the booking is cancelled and "late" is a
        # question about a class she no longer holds.
        student_cancels = self._fitness_student_cancels()
        result = super().action_cancel()

        # The base returns the admin late-cancel dialog's action BEFORE
        # cancelling anything. Dropping it here meant the dialog never
        # opened AND everything below still ran - so the student was sent
        # "your booking has been cancelled" about a class that was still
        # booked. Nothing is announced that did not happen.
        if isinstance(result, dict):
            return result

        if self._notif_enabled('send_cancellation'):
            self._send_notification('fitness_notifications.mail_template_booking_cancellation')
        # In-app bell: skip for class-wide cancellations (_class_cancelled=True)
        # because action_cancel_class() already sends a class-level alert per student.
        if self.env.context.get('skip_fitness_notification') or self.env.context.get('_class_cancelled'):
            return result
        self._maybe_notify_studio_of_cancel(student_cancels)
        for booking in self:
            user = booking.student_id.user_ids[:1]
            if not user:
                continue
            class_name = booking.calendar_event_id.name or 'class'
            event_start = booking.calendar_event_id.start
            lang_env = self.with_context(lang=recipient_lang(self.env, user))
            # Was f-strings, so no .po entry could ever reach it, and the date
            # was raw strftime: English month, UTC clock, an English "at"
            # wedged mid-sentence. Same treatment as booking_confirmed - the
            # connector lives in the translatable string so each language
            # places it itself.
            start_str = ''
            if event_start:
                try:
                    start_str = format_datetime(
                        lang_env.env, event_start, tz=STUDIO_TZ,
                        dt_format='d MMM HH:mm', lang_code=recipient_lang(self.env, user))
                except Exception:
                    start_str = event_start.strftime('%d %b %H:%M')
            body = (
                lang_env.env._(
                    'Your booking for %(cls)s on %(when)s has been cancelled.',
                    cls=class_name, when=start_str)
                if start_str else
                lang_env.env._(
                    'Your booking for %(cls)s has been cancelled.',
                    cls=class_name)
            )
            # Only what happened. This used to end "Check your credit
            # balance for any refunds" every time - including inside the
            # window, where the credit is kept on purpose, so a student was
            # sent to look for a refund that did not exist. Kept: nothing is
            # said about credit at all. Returned: one sentence saying so.
            if booking.credit_returned:
                body = '%s %s' % (
                    body, lang_env.env._('Your credit has been returned.'))
            # The studio's own words, when it gave any. Appended so the news
            # comes first and the explanation reads as the studio wrote it.
            why = (self.env.context.get('cancel_reason') or '').strip()
            if why:
                body = '%s %s' % (body, lang_env.env._('Reason: %(why)s', why=why))
            try:
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'booking_cancelled',
                    lang_env.env._('Booking cancelled: %(cls)s', cls=class_name),
                    body,
                    action_url='/my/classes',
                )
            except Exception:
                pass
        return result

    def _fitness_student_cancels(self):
        """{booking id: late?} for the bookings the student is cancelling herself.

        A cancel is hers when the user pressing it is the booking's own
        student, in her own environment - the app, or an RPC from her
        session. The studio cancelling on her behalf (back office, roster,
        a manager) is not, and is not announced back to the studio. Late
        means inside the cancellation window, read from the same setting
        the warning and the credit rule use, at the moment of the cancel.
        """
        if self.env.su:
            return {}
        user = self.env.user
        if user.has_group('fitness_core.group_fitness_manager') or user._is_admin():
            return {}
        window = self._cancellation_window_hours()
        now = fields.Datetime.now()
        out = {}
        for booking in self:
            if booking.state != 'booked' or booking.student_id != user.partner_id:
                continue
            start = booking.calendar_event_id.start
            hours_until = (start - now).total_seconds() / 3600.0 if start else 0
            out[booking.id] = 0 < hours_until <= window
        return out

    def _maybe_notify_studio_of_cancel(self, student_cancels):
        """Tell the class's teacher and the studio managers she cancelled.

        The other half of _maybe_notify_instructor: until now a cancel
        reached the student alone, and the teacher found out by opening her
        roster. Every cancellation the student makes herself - group or
        private, early or late - goes to the class's teacher (linked to her
        roster) and to every studio manager (linked to the class), each in
        her own language. No teacher on the class: managers only. Somebody
        who is both hears it once, as the teacher.
        """
        if not student_cancels:
            return
        Notif = self.env['fitness.notification'].sudo()
        managers = self.env['res.users'].sudo().search([
            ('group_ids', 'in', [self.env.ref('fitness_core.group_fitness_manager').id]),
            ('share', '=', False),
        ])
        for booking in self.sudo().filtered(
                lambda b: b.id in student_cancels and b.state == 'cancelled'):
            event = booking.calendar_event_id
            late = student_cancels[booking.id]
            still = self.sudo().search_count([
                ('calendar_event_id', '=', event.id),
                ('state', 'in', ('booked', 'attended')),
            ])
            teacher = event.user_id if event.user_id.active else self.env['res.users']
            for user, url in ([(teacher, '/my/instructor/classes/%d' % event.id)] if teacher else []) + [
                    (m, '/odoo/calendar.event/%d' % event.id) for m in managers - teacher]:
                lang = recipient_lang(self.env, user)
                tenv = self.with_context(lang=lang).env
                cls = event.with_context(lang=lang).name or 'class'
                try:
                    when = format_datetime(tenv, event.start, tz=STUDIO_TZ,
                                           dt_format='d MMM HH:mm', lang_code=lang)
                except Exception:
                    when = event.start.strftime('%d %b %H:%M') if event.start else ''
                title = (tenv._('Late cancellation: %(cls)s', cls=cls) if late
                         else tenv._('Cancellation: %(cls)s', cls=cls))
                body = tenv._('%(student)s cancelled their place in %(cls)s on '
                              '%(when)s. Still booked: %(count)s.',
                              student=booking.student_id.name or '', cls=cls,
                              when=when, count=still)
                if late:
                    body = '%s %s' % (body, tenv._(
                        'Cancelled less than %(hours)s hours before the class.',
                        hours=self._format_window(self._cancellation_window_hours())))
                Notif._create_for_user(user.id, 'student_cancelled', title, body,
                                       action_url=url)

    def _notify_credit_returned_by_studio(self):
        """Tell her the studio returned a credit the policy had kept.

        Give the Credit Back after a late cancel, or Cancel with reason on
        a marked booking with the tick on. Her earlier message said nothing
        about credit, because at the time nothing came back; when the
        studio decides otherwise, this is the only place she hears it.
        """
        result = super()._notify_credit_returned_by_studio()
        if self.env.context.get('skip_fitness_notification'):
            return result
        user = self.student_id.user_ids[:1]
        if user:
            class_name = self.calendar_event_id.name or 'class'
            lang_env = self.with_context(lang=recipient_lang(self.env, user))
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'booking_cancelled',
                lang_env.env._('Credit returned: %(cls)s', cls=class_name),
                lang_env.env._(
                    'The studio has returned your credit for %(cls)s.',
                    cls=class_name),
                action_url='/my/packages',
            )
        return result

    # ─── Class reminder (cron) ──────────────────────────────────────────────────

    @api.model
    def _cron_send_reminders(self):
        if not self._notif_enabled('send_reminder'):
            _logger.info("[NOTIFICATIONS] Reminders disabled via settings, cron skipped.")
            return
        lead_hours = float(self.env['ir.config_parameter'].sudo().get_param(
            'fitness_notifications.reminder_lead_hours', '24'))
        now = fields.Datetime.now()
        window_end = now + timedelta(hours=lead_hours)

        due = self.search([
            ('state', '=', 'booked'),
            ('reminder_sent', '=', False),
            ('class_start', '>', now),
            ('class_start', '<=', window_end),
        ])
        if not due:
            _logger.info("[NOTIFICATIONS] No reminders due (lead=%.1fh).", lead_hours)
            return
        due._send_notification('fitness_notifications.mail_template_class_reminder')
        due.write({'reminder_sent': True})
        _logger.info("[NOTIFICATIONS] Sent %d reminder(s) (lead=%.1fh).", len(due), lead_hours)

    # ─── Credit pack expiry check (cron) ────────────────────────────────────────

    @api.model
    def _cron_check_credit_expiry(self):
        """Notify students whose credit pack expires within 7 days (once per pack per week)."""
        if not self._notif_enabled('send_credit_expiry'):
            return
        today = fields.Date.context_today(self)
        expiry_window = today + timedelta(days=7)

        expiring_lines = self.env['sale.order.line'].sudo().search([
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
            ('fitness_validity_end_date', '!=', False),
            ('fitness_validity_end_date', '>=', today),
            ('fitness_validity_end_date', '<=', expiry_window),
        ])
        notified = 0
        for line in expiring_lines:
            partner = line.order_partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            recent = self.env['fitness.notification'].sudo().search([
                ('user_id', '=', user.id),
                ('notification_type', '=', 'credit_expiring'),
                ('create_date', '>=', fields.Datetime.now() - timedelta(days=7)),
            ], limit=1)
            if recent:
                continue
            days_left = (line.fitness_validity_end_date - today).days
            remaining = line.fitness_remaining_classes
            lang = recipient_lang(self.env, user)
            expire_date_str = studio_date(
                self.env, line.fitness_validity_end_date, 'd MMM y', lang)
            lang_env = self.with_context(lang=lang)
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'credit_expiring',
                lang_env.env._('%d credit(s) expiring in %d day(s)', remaining, days_left),
                lang_env.env._('Your pack expires on %s. Use your remaining credits before they expire.', expire_date_str),
                action_url='/my/packages',
            )
            notified += 1
        _logger.info("[NOTIFICATIONS] Credit expiry: notified %d student(s).", notified)

    # ─── Subscription billing reminder (cron, 3 days lead) ──────────────────────

    @api.model
    def _cron_send_billing_reminders(self):
        """Notify subscribers N days before their next renewal/billing date.

        N is the studio's renewal window (fitness.renewal_window_days,
        default 3): the reminder goes out on the day the shop starts
        offering Renew and the desk may take the renewal, never before.
        """
        LEAD_DAYS = self.env['sale.order']._fitness_renewal_window_days()
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=LEAD_DAYS)

        due_subs = self.env['sale.order'].sudo().search([
            ('is_subscription', '=', True),
            ('subscription_state', '=', '3_progress'),
            ('next_invoice_date', '=', target_date),
        ])
        notified = 0
        for sub in due_subs:
            partner = sub.partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            recent = self.env['fitness.notification'].sudo().search([
                ('user_id', '=', user.id),
                ('notification_type', '=', 'billing_reminder'),
                ('create_date', '>=', fields.Datetime.now() - timedelta(hours=48)),
            ], limit=1)
            if recent:
                continue
            plan_name = sub.fitness_subscription_product_id.name if sub.fitness_subscription_product_id else sub.name
            lang = recipient_lang(self.env, user)
            renew_date_str = studio_date(self.env, target_date, 'd MMM y', lang)
            lang_env = self.with_context(lang=lang)
            # "No action needed" was true when nothing a student could do
            # affected her renewal. It is not true now: she can renew from the
            # app, and the studio can take the money in person. It was also
            # never true on this database - Odoo's recurring invoicing is
            # switched off and most members hold no saved card, so the
            # promise was being made to people nothing was going to bill.
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'billing_reminder',
                lang_env.env._('Subscription renews in %d days', LEAD_DAYS),
                lang_env.env._(
                    'Your %s plan reaches the end of its period on %s. You '
                    'can renew it in the app, or pay at the studio.',
                    plan_name, renew_date_str),
                action_url='/my/packages',
            )
            notified += 1
        _logger.info("[NOTIFICATIONS] Billing reminders: notified %d subscriber(s).", notified)

    # ─── Class bell reminder (cron, 6–12h window) ────────────────────────────────

    @api.model
    def _cron_send_bell_reminders(self):
        """Send in-app bell notifications for classes starting in 6–12 hours.

        Fires once per booking (bell_reminder_sent flag). The 6h lower bound
        prevents overlap with last-minute logistics; 12h gives enough notice
        to prepare or cancel. Runs every 30 min so no booking falls through the gap.
        """
        now = fields.Datetime.now()
        window_start = now + timedelta(hours=6)
        window_end = now + timedelta(hours=12)

        due = self.search([
            ('state', '=', 'booked'),
            ('bell_reminder_sent', '=', False),
            ('class_start', '>', window_start),
            ('class_start', '<=', window_end),
        ])
        if not due:
            _logger.info("[NOTIFICATIONS] No bell reminders due (6–12h window).")
            return

        notified = 0
        for booking in due:
            partner = booking.student_id
            user = partner.user_ids[:1]
            if not user:
                continue
            event = booking.calendar_event_id
            class_name = event.name or 'class'
            hours_until = max(1, int((booking.class_start - now).total_seconds() / 3600))
            lang_env = self.with_context(lang=recipient_lang(self.env, user))
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'class_reminder',
                lang_env.env._('Class in ~%d hours', hours_until),
                lang_env.env._('Reminder: %s is coming up soon. See you there!', class_name),
                action_url='/my/classes',
            )
            notified += 1

        due.write({'bell_reminder_sent': True})
        _logger.info("[NOTIFICATIONS] Bell reminders: notified %d student(s).", notified)
