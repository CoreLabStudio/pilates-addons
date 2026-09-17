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

    # Still the studio's to deal with. Scheduled and declined are finished,
    # and somebody whose trial has been and gone may ask again.
    OPEN_STATES = ('pending', 'contacted')

    # Monday first, the way the timetable reads.
    WEEKDAY_ORDER = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

    @api.model
    def _live_schedule(self):
        """The studio's timetable: active, group slots.

        Archived rows are slots the studio has closed -
        action_close_for_booking archives the row and its future classes
        together - so "active" is the right question here. Private sessions
        are not something to offer as a first free class.
        """
        return self.env['fitness.class.schedule'].sudo().search([
            ('active', '=', True),
            ('session_type', '=', 'group'),
        ])

    @api.model
    def _offered_class_types(self):
        """The classes the trial form should offer, per discipline.

        Read from the timetable, not from the class-type catalogue. The
        catalogue holds everything the studio has ever defined, so a class
        nobody has scheduled - or one that has been retired - was being
        offered to somebody asking for their first visit.

        Deliberately the schedule rather than the generated calendar: a slot
        the studio closes is archived here, so closures are respected, and
        this does not empty out when class generation falls behind.
        """
        scheduled = self._live_schedule().mapped('class_type_id')
        # Both have to be live. mapped() browses by id, so an archived class
        # type still comes back through an active schedule row - and a class
        # the studio has retired must not be offered as somebody's first one.
        types = scheduled.filtered(
            lambda c: c.active and c.classroom_type in ('barre', 'reformer'))
        if not types:
            # Nothing on the timetable at all - a database that has not been
            # seeded, or a studio between schedules. Falling back to the
            # catalogue keeps the form usable instead of showing a discipline
            # with no classes under it.
            types = self.env['fitness.class.type'].sudo().search([
                ('classroom_type', 'in', ('barre', 'reformer')),
                ('session_type', '=', 'group'),
            ])
        out = {'barre': [], 'reformer': []}
        for ct in types.sorted(lambda c: (c.name or '').lower()):
            out.setdefault(ct.classroom_type, []).append({
                'id': ct.id,
                'name': ct.name or '',
                'duration': ct.duration or 0,
            })
        return out

    @api.model
    def _open_weekdays(self):
        """Weekday codes the studio runs something on, in timetable order."""
        days = set(self._live_schedule().mapped('weekday'))
        return [d for d in self.WEEKDAY_ORDER if d in days]

    @api.model
    def _weekday_hint(self, open_days, lang):
        """"Monday to Friday", or a list when the open days have a gap."""
        if not open_days or len(open_days) == 7:
            return ''
        code = lang if lang in ('en_US', 'ca_ES') else 'es_ES'
        names = {
            'en_US': {'mon': 'Monday', 'tue': 'Tuesday', 'wed': 'Wednesday',
                      'thu': 'Thursday', 'fri': 'Friday', 'sat': 'Saturday',
                      'sun': 'Sunday'},
            'ca_ES': {'mon': 'dilluns', 'tue': 'dimarts', 'wed': 'dimecres',
                      'thu': 'dijous', 'fri': 'divendres', 'sat': 'dissabte',
                      'sun': 'diumenge'},
            'es_ES': {'mon': 'lunes', 'tue': 'martes', 'wed': 'mi\u00e9rcoles',
                      'thu': 'jueves', 'fri': 'viernes', 'sat': 's\u00e1bado',
                      'sun': 'domingo'},
        }[code]
        joiner = {'en_US': ' to ', 'ca_ES': ' a ', 'es_ES': ' a '}[code]
        first = self.WEEKDAY_ORDER.index(open_days[0])
        last = self.WEEKDAY_ORDER.index(open_days[-1])
        # Contiguous runs read as a range; anything else is listed, because
        # "Monday to Saturday" would be a lie if Wednesday were closed.
        if last - first + 1 == len(open_days) and len(open_days) > 2:
            return names[open_days[0]] + joiner + names[open_days[-1]]
        return ', '.join(names[d] for d in open_days)

    @api.model
    def _is_open_on(self, day):
        """Does the studio run anything on this date?"""
        open_days = self._open_weekdays()
        if not open_days:
            return True
        return self.WEEKDAY_ORDER[day.weekday()] in open_days
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
    # ── where it came from ─────────────────────────────────────────────────
    # Both entry points feed one pipeline, which is the point - but an admin
    # answering a request still wants to know whether the person was standing
    # on the public site or already signed in to the app, because it changes
    # what she can assume they know.
    source = fields.Selection(
        [('website', 'Website'), ('app', 'App')],
        string='Came from', default='website', required=True, index=True,
    )

    # ── what they asked for ────────────────────────────────────────────────
    # The form asks for a specific class rather than only a discipline, so the
    # studio knows whether somebody wants Reformer Sculpt or Reformer Extreme
    # before deciding which slot to put them in. class_interest stays as the
    # discipline: every existing query, product lookup and email uses it.
    class_type_id = fields.Many2one(
        'fitness.class.type', string='Class Requested', ondelete='restrict',
        help="The specific class the person asked for. The discipline is still "
             "class_interest; this narrows it.",
    )
    preferred_date = fields.Date(
        string='Preferred Date',
        help="The day they would like to come. Not a booking - the studio "
             "still chooses the actual slot.",
    )
    preferred_period = fields.Selection(
        [('morning', 'Morning'), ('evening', 'Evening')],
        string='Morning or Evening',
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
            # Called Cancelled because that is what the button says. The
            # stored value stays 'declined': renaming it would be a data
            # migration for a word.
            ('declined', 'Cancelled'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
    )
    # Filled from the Class Slot, and read-only on screen: the slot is what
    # actually gets booked, so a second hand-typed time could only ever
    # disagree with it. Kept a plain stored field rather than a compute - see
    # _apply_slot_datetime.
    scheduled_datetime = fields.Datetime(
        string='Scheduled Date/Time', readonly=True)
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
    booking_id = fields.Many2one(
        'fitness.booking', string='Booking', readonly=True, copy=False,
        help="The place this request was approved into. Cancelling either "
             "one cancels the other.")
    decline_reason = fields.Text(
        string='Reason', copy=False,
        help="Why the studio could not take this request. Sent to the student "
             "and kept on the record.")
    create_date = fields.Datetime(string='Received On', readonly=True)

    # Other open requests from the same person. Not stored: it is a statement
    # about the rest of the table, and a stored copy would go stale the moment
    # one of the others was scheduled or declined.
    other_open_ids = fields.Many2many(
        'fitness.trial.request', compute='_compute_other_open',
        string='Other Open Requests')
    other_open_count = fields.Integer(
        compute='_compute_other_open', string='Duplicates')
    duplicate_warning = fields.Char(compute='_compute_other_open')

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

    @staticmethod
    def _apply_slot_datetime(vals, slot_start):
        """Put the slot's own start time on the request.

        Not a computed field on purpose. A stored compute recomputes over
        every existing row, and a request scheduled before this screen had
        slots carries a time that nothing else records; clearing those to keep
        the model tidy would throw away the only copy the studio has. This
        only ever writes a time, never blanks one.
        """
        if slot_start:
            vals['scheduled_datetime'] = slot_start
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('occurrence_id') and not vals.get('scheduled_datetime'):
                slot = self.env['calendar.event'].sudo().browse(vals['occurrence_id'])
                self._apply_slot_datetime(vals, slot.start)
        records = super().create(vals_list)
        # Fill the Student in straight away, so an admin opening the request
        # sees who it is rather than an empty field.
        records._link_partner()
        for rec in records:
            if rec.status == 'scheduled':
                # A slot was chosen on the form, so the class is booked: tell
                # the student it is confirmed and tell the studio it happened.
                #
                # Reformer used to fall through here doing nothing, because it
                # waited for the studio to review it by hand. It books directly
                # now, and that branch would have meant a trial nobody was told
                # about - the confirmation page promising an email that was
                # never sent, and no notification reaching the studio at all.
                rec._send_scheduled_email()
                rec._send_admin_notification()
                # Record it, or the form shows "Confirmation Email Sent" as
                # unticked and the studio sends a second one by hand.
                rec.write({
                    'confirmation_email_sent': True,
                    'confirmation_email_sent_date': fields.Datetime.now(),
                })
            else:
                rec._send_pending_email()
        return records

    # Set by _decline, and by nothing else. A context key rather than a
    # check on the reason, because the reason is optional: what has to be
    # true is that the cancellation went through the button, so the student
    # was told about it.
    _DECLINE_KEY = 'fitness_trial_declining'

    def write(self, vals):
        # Cancelling is a thing the student is told about, so it goes through
        # action_decline. Enforced here rather than by hiding the status on a
        # form: the dropdown, an import and a plain RPC write all arrive at
        # this method, and only this method sees all of them.
        if vals.get('status') == 'declined' and not self.env.context.get(self._DECLINE_KEY):
            changing = self.filtered(lambda r: r.status != 'declined')
            if changing:
                raise UserError(_(
                    "Use the Cancel request button. It tells the student, by "
                    "email and in the app, and lets you say why."))

        # Choosing a slot is choosing the time. Done here as well as in the
        # onchange so it holds for an import, a server action or anything else
        # that does not go through a form.
        #
        # There used to be an auto-advance to 'scheduled' here whenever a
        # datetime was saved without an explicit status. That was for a time
        # typed by hand, which is no longer possible - and leaving it would
        # have marked a request scheduled the moment somebody picked a
        # candidate slot to consider, without anything being booked.
        if 'occurrence_id' in vals and 'scheduled_datetime' not in vals:
            slot = self.env['calendar.event'].sudo().browse(vals['occurrence_id']) \
                if vals['occurrence_id'] else self.env['calendar.event']
            if slot.start:
                vals = self._apply_slot_datetime(dict(vals), slot.start)

        # Capture previous statuses for post-write side effects
        prev_status = {}
        if 'status' in vals or 'scheduled_datetime' in vals:
            prev_status = {r.id: r.status for r in self}

        result = super().write(vals)

        # A corrected email should find its student too, not leave the field
        # showing whoever the old address matched.
        if 'email' in vals:
            self.filtered(lambda r: not r.partner_id)._link_partner()

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

    occurrence_fill = fields.Char(
        string='How full', compute='_compute_occurrence_fill',
        help="Places taken on the chosen slot, out of its capacity.")

    @api.depends('occurrence_id')
    def _compute_occurrence_fill(self):
        """"3/8" for the chosen slot, so placement is an informed decision."""
        events = self.mapped('occurrence_id')
        counts = {}
        if events:
            for event, count in self.env['fitness.booking'].sudo()._read_group(
                [('calendar_event_id', 'in', events.ids),
                 ('state', 'in', ('booked', 'attended', 'no_show'))],
                groupby=['calendar_event_id'], aggregates=['__count'],
            ):
                counts[event.id] = count
        for rec in self:
            event = rec.occurrence_id
            if not event:
                rec.occurrence_fill = False
                continue
            taken = counts.get(event.id, 0)
            capacity = event.capacity or 0
            if not capacity:
                rec.occurrence_fill = _("%(taken)s booked", taken=taken)
            elif taken >= capacity:
                rec.occurrence_fill = _("%(taken)s/%(capacity)s - FULL",
                                        taken=taken, capacity=capacity)
            else:
                rec.occurrence_fill = _("%(taken)s/%(capacity)s - %(free)s free",
                                        taken=taken, capacity=capacity,
                                        free=capacity - taken)

    def action_view_candidate_slots(self):
        """Every slot this request could go into, with how full each one is.

        Opens the ordinary class list rather than a bespoke screen, so the
        capacity columns, filters and grouping the studio already knows all
        work here too.
        """
        self.ensure_one()
        domain = [
            ('is_fitness_class', '=', True),
            ('class_state', '!=', 'cancelled'),
            ('start', '>=', fields.Datetime.now()),
        ]
        if self.class_interest:
            domain.append(('class_type_id.classroom_type', '=', self.class_interest))
        if self.class_type_id:
            domain.append(('class_type_id', '=', self.class_type_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Slots for %(who)s", who=self.name or _("this request")),
            'res_model': 'calendar.event',
            'view_mode': 'list,calendar,form',
            'domain': domain,
            # No default grouping, deliberately. calendar.event._read_group
            # ANDs the personal-calendar privacy domain onto any grouped read
            # whose fields are not all "public" - and __count never is, so
            # grouping by anything applies it. That turned 53 candidate
            # classes into one group of 1 and left the studio staring at an
            # empty list. Grouping by hand from the UI has the same effect;
            # this page simply stops asking for it.
            'context': {},
        }

    @api.depends('email', 'partner_id', 'status')
    def _compute_other_open(self):
        """Who else is still waiting under this person's name.

        Reads the whole open set once rather than searching per record: open
        requests are by definition the ones nobody has dealt with yet, so the
        set is small, and matching in Python lets the email comparison ignore
        case and stray spaces the way the rest of this model does.
        """
        open_all = self.search([('status', 'in', list(self.OPEN_STATES))])
        by_email = {}
        by_partner = {}
        for rec in open_all:
            key = (rec.email or '').strip().lower()
            if key:
                by_email[key] = by_email.get(key, self.browse()) | rec
            if rec.partner_id:
                by_partner[rec.partner_id.id] = \
                    by_partner.get(rec.partner_id.id, self.browse()) | rec
        for rec in self:
            others = self.browse()
            key = (rec.email or '').strip().lower()
            if key:
                others |= by_email.get(key, self.browse())
            if rec.partner_id:
                others |= by_partner.get(rec.partner_id.id, self.browse())
            others -= rec
            # Only meaningful while this request is itself open. On a
            # scheduled or declined one the banner would be about somebody
            # else's decision.
            if rec.status not in self.OPEN_STATES:
                others = self.browse()
            rec.other_open_ids = others
            rec.other_open_count = len(others)
            if not others:
                rec.duplicate_warning = False
            elif len(others) == 1:
                rec.duplicate_warning = _(
                    "This person has 1 other open trial request. A student "
                    "gets one trial, so only one of these should be booked.")
            else:
                rec.duplicate_warning = _(
                    "This person has %(n)s other open trial requests. A "
                    "student gets one trial, so only one of these should be "
                    "booked.", n=len(others))

    def _find_booking(self):
        """The booking behind this request.

        Stored since the link was added; resolved by student and class for
        anything approved before that, so a request scheduled last week still
        finds its place without a migration to backfill it.
        """
        self.ensure_one()
        if self.booking_id:
            return self.booking_id
        if not self.partner_id or not self.occurrence_id:
            return self.env['fitness.booking'].browse()
        return self.env['fitness.booking'].sudo().search([
            ('student_id', '=', self.partner_id.id),
            ('calendar_event_id', '=', self.occurrence_id.id),
            ('state', 'in', ('booked', 'no_show')),
        ], limit=1)

    @api.model
    def _scheduled_behind(self, bookings):
        """Scheduled requests whose class place is one of these bookings."""
        if not bookings:
            return self.browse()
        found = self.sudo().search([
            ('status', '=', 'scheduled'),
            ('booking_id', 'in', bookings.ids),
        ])
        # Approved before the link existed: match on the student and the class
        # instead, which is what the booking is.
        legacy = self.sudo().search([
            ('status', '=', 'scheduled'),
            ('booking_id', '=', False),
            ('partner_id', 'in', bookings.mapped('student_id').ids),
            ('occurrence_id', 'in', bookings.mapped('calendar_event_id').ids),
        ])
        pairs = {(b.student_id.id, b.calendar_event_id.id) for b in bookings}
        legacy = legacy.filtered(
            lambda r: (r.partner_id.id, r.occurrence_id.id) in pairs)
        return found | legacy

    def _cancelled_with_booking(self):
        """The booking went, so the request is not scheduled any more.

        Deliberately silent. Cancelling the booking has already told the
        student their class is off, with whatever reason the studio gave;
        a trial notice on top would be two messages about one thing.
        """
        for rec in self:
            if rec.status != 'scheduled':
                continue
            rec.with_context(**{rec._DECLINE_KEY: True}).write({
                'status': 'declined',
                'decline_reason': rec.decline_reason or _(
                    'The class booking was cancelled.'),
            })
            _logger.info(
                "[TRIAL] Request %s marked cancelled because its booking was "
                "cancelled", rec.id)

    def action_decline(self):
        """Open the dialog that asks why before cancelling."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cancel this request"),
            'res_model': 'fitness.trial.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def _decline(self, reason):
        """Cancel the request, tell the student, and leave the door open.

        A declined request has never spent anything: approval is what mints
        the order, so the trial is still theirs and the portal will offer it
        again the moment this one stops being open. That is worth saying to
        them rather than leaving them to discover it.
        """
        self.ensure_one()
        # One booking, one truth. This used to refuse a scheduled request and
        # tell the studio to go and cancel the booking first, which is the
        # same two-step it is meant to save them.
        booking = self._find_booking()
        if booking.filtered(lambda b: b.state == 'booked'):
            booking.with_context(
                _trial_request_declining=True,
                _admin_cancel_direct=True,
                admin_force_refund=True,
                cancel_reason=reason or False,
            ).action_cancel()
        self.with_context(**{self._DECLINE_KEY: True}).write({
            'status': 'declined', 'decline_reason': reason or False})
        self._notify_declined(reason)
        return True

    def _notify_declined(self, reason):
        """In-app and push, in the student's own language.

        Wrapped: a notification that fails must not undo the cancellation, the
        reason, or the email. Silent when there is no portal user behind the
        request - somebody who asked from the public site and never signed up
        has no app to be notified in, and the declined email is their copy.
        """
        self.ensure_one()
        user = self.partner_id.user_ids[:1] if self.partner_id else None
        if not user:
            return
        try:
            # Written through lang_env.env._ rather than an alias: Odoo's
            # extractor only picks up calls literally named _(), so a helper
            # bound to a shorter name puts nothing in the catalogue and the
            # student is notified in English whatever they read the app in.
            lang_env = self.with_context(lang=user.lang or self.lang or 'es_ES')
            title = lang_env.env._("About your trial class request")
            if reason:
                body = lang_env.env._(
                    "The studio could not take this one: %(why)s You are still "
                    "welcome to ask for another - your free class has not been "
                    "used.", why=reason.strip())
            else:
                body = lang_env.env._(
                    "The studio could not take this one. You are still welcome "
                    "to ask for another - your free class has not been used.")
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id, 'trial_declined', title, body, action_url='/my/trial')
        except Exception:
            _logger.exception(
                "[TRIAL] Could not notify partner %s that request %s was declined",
                self.partner_id.id, self.id)

    def action_view_other_open(self):
        """The other open requests from this person, so they can be compared."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Open requests from %(who)s", who=self.name or self.email or '-'),
            'res_model': 'fitness.trial.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', (self.other_open_ids | self).ids)],
            'context': {},
        }

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Picking a student fills in who they are.

        The link already worked the other way round - an email finds its
        contact, see _link_partner - but an admin taking a request over the
        phone picks the student first, and was then retyping a name, address
        and number the contact record already holds.

        Only ever writes something. A contact with no phone must not blank a
        number somebody has just typed in, and the language comes across too
        so the confirmation email goes out in the one they read.
        """
        for rec in self:
            partner = rec.partner_id
            if not partner:
                continue
            if partner.name:
                rec.name = partner.name
            if partner.email:
                rec.email = partner.email
            if partner.phone:
                rec.phone = partner.phone
            if partner.lang:
                rec.lang = partner.lang

    @api.onchange('occurrence_id')
    def _onchange_occurrence_id(self):
        """Show the slot's time as soon as it is chosen, not after saving."""
        for rec in self:
            if rec.occurrence_id and rec.occurrence_id.start:
                rec.scheduled_datetime = rec.occurrence_id.start

    def _match_partner(self):
        """An existing contact with this request's email, if there is one."""
        self.ensure_one()
        if not self.email:
            return self.env['res.partner'].browse()
        return self.env['res.partner'].sudo().search(
            [('email', '=ilike', self.email.strip())], limit=1)

    def _link_partner(self):
        """Point the request at the contact it belongs to.

        Called on create and whenever the email changes, so the Student field
        is filled in before an admin ever opens the record rather than left
        blank for her to retype.
        """
        for rec in self:
            if rec.partner_id or not rec.email:
                continue
            match = rec._match_partner()
            if match:
                rec.partner_id = match

    def _resolve_partner(self, create_if_missing=False):
        """The student this request belongs to.

        partner_id is set when a logged-in student submits, and filled in from
        the email for everybody else. create_if_missing is used at approval:
        somebody requesting their first class has no contact record yet, and
        refusing to book them because of that put the work of retyping the
        name, email and phone back on the studio.
        """
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        match = self._match_partner()
        if match:
            self.partner_id = match
            return match
        if not (create_if_missing and self.email):
            return self.env['res.partner'].browse()
        partner = self.env['res.partner'].sudo().create({
            'name': (self.name or self.email).strip(),
            'email': self.email.strip(),
            'phone': self.phone or False,
            'lang': self.lang or 'es_ES',
        })
        self.partner_id = partner
        _logger.info("[TRIAL] Created contact %s for request %s from its own "
                     "submitted details", partner.id, self.id)
        return partner

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

        # Somebody booking their first class has no contact record yet. That
        # used to stop approval dead and hand the studio the job of retyping a
        # name, email and phone the request was already carrying.
        partner = self._resolve_partner(create_if_missing=True)
        if not partner:
            raise UserError(_(
                "This request has no email address, so there is nobody to book. "
                "Add one and try again."))

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

        vals = {'status': 'scheduled', 'booking_id': booking.id}
        # Normally already set the moment the slot was chosen. Kept as a
        # backstop for a request approved straight from a slot set by an
        # import or an older row.
        if not self.scheduled_datetime and self.occurrence_id.start:
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

    # Queued, not sent inline. These used to go out with force_send=True,
    # which delivers over SMTP inside the request: a visitor submitting the
    # public trial form waited 8 seconds staring at a spinner while two
    # messages were handed to the mail server one after the other. The cron
    # picks them up within the minute, and the rest of the app already queues
    # its mail this way.
    def _send_pending_email(self):
        template = self.env.ref(
            'fitness_trials.mail_template_trial_pending', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=False, raise_exception=False)
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
        # The trial is approved by the studio, so the acting language is the
        # studio's. The student is the one reading this.
        _ = self.env(context=dict(self.env.context,
                                  lang=user.lang or 'es_ES'))._
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
            template.sudo().send_mail(self.id, force_send=False, raise_exception=False)
        except Exception:
            _logger.exception("Trial scheduled email failed for record %s", self.id)

    def _send_admin_notification(self):
        """Tell the studio a trial was booked, whichever discipline it was."""
        template = self.env.ref(
            'fitness_trials.mail_template_trial_admin', raise_if_not_found=False
        ) or self.env.ref(
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
                force_send=False,
                raise_exception=False,
                email_values={'email_to': admin_email},
            )
        except Exception:
            _logger.exception("Trial admin notification failed for record %s", self.id)

    def _send_cancelled_email(self):
        """The studio cancelled the class this trial was holding."""
        template = self.env.ref(
            'fitness_trials.mail_template_trial_cancelled', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=False, raise_exception=False)
        except Exception:
            _logger.exception("Trial cancelled email failed for record %s", self.id)

    def _send_declined_email(self):
        template = self.env.ref(
            'fitness_trials.mail_template_trial_declined', raise_if_not_found=False
        )
        if not template:
            return
        try:
            template.sudo().send_mail(self.id, force_send=False, raise_exception=False)
        except Exception:
            _logger.exception("Trial declined email failed for record %s", self.id)
