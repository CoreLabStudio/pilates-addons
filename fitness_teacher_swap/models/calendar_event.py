import pytz as _pytz

from odoo import models, fields
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


def _fmt_event_dt(dt_utc, user):
    """Return dt_utc formatted in the user's local timezone."""
    if not dt_utc:
        return ''
    try:
        tz = _pytz.timezone(user.tz or 'UTC')
    except Exception:
        tz = _pytz.UTC
    local = _pytz.UTC.localize(dt_utc).astimezone(tz)
    return local.strftime('%d/%m/%Y %H:%M')


class CalendarEvent(models.Model):
    """Adds one-class-at-a-time teacher reassignment for the teacher portal page,
    and sends in-app notifications whenever a fitness class teacher is changed
    or a class is rescheduled via the backend form."""
    _inherit = 'calendar.event'

    # Turn on chatter tracking for the organizer field.
    user_id = fields.Many2one(tracking=True)

    def write(self, vals):
        skip = self.env.context.get('skip_fitness_notification')
        changing_teacher = 'user_id' in vals and not skip
        changing_time    = 'start' in vals and not skip

        if not changing_teacher and not changing_time:
            return super().write(vals)

        fitness_events = self.filtered('is_fitness_class')
        # Snapshot before write
        old_data = {
            e.id: {'teacher_id': e.user_id.id, 'start': e.start}
            for e in fitness_events
        }

        result = super().write(vals)

        if not old_data:
            return result

        Notif = self.env['fitness.notification'].sudo()
        now   = fields.Datetime.now()

        for event in fitness_events:
            snap = old_data.get(event.id, {})

            # ── Teacher swap notifications ──────────────────────────────
            if changing_teacher:
                new_teacher_id = vals['user_id']
                if new_teacher_id and snap.get('teacher_id') != new_teacher_id:
                    new_teacher = self.env['res.users'].browse(new_teacher_id)
                    if new_teacher.exists():
                        bookings = self.env['fitness.booking'].sudo().search([
                            ('calendar_event_id', '=', event.id),
                            ('state', '=', 'booked'),
                        ])
                        notified = 0
                        for booking in bookings:
                            student_user = booking.student_id.user_ids[:1]
                            if student_user:
                                senv = self.with_context(lang=student_user.lang or 'en_US')
                                Notif._create_for_user(
                                    student_user.id,
                                    'teacher_swap',
                                    senv.env._('Teacher updated: %s', event.name),
                                    senv.env._('Your class will now be taught by %s.', new_teacher.name),
                                    action_url=f'/my/classes/{event.id}',
                                )
                                notified += 1
                        tenv = self.with_context(lang=new_teacher.lang or 'en_US')
                        Notif._create_for_user(
                            new_teacher.id,
                            'teacher_swap',
                            tenv.env._('Class assigned to you: %s', event.name),
                            tenv.env._('You have been assigned as teacher for this class.'),
                            action_url=f'/my/teacher/classes/{event.id}',
                        )
                        _logger.info(
                            "[TEACHER-ASSIGN] '%s': assigned to %s, %d student(s) notified",
                            event.name, new_teacher.name, notified,
                        )

            # ── Reschedule notifications ────────────────────────────────
            if changing_time:
                old_start = snap.get('start')
                new_start = event.start
                # Guard: only fire if start actually moved by >1 min and class is in the future
                if (old_start and new_start and new_start > now
                        and abs((new_start - old_start).total_seconds()) > 60):
                    teacher = event.user_id
                    bookings = self.env['fitness.booking'].sudo().search([
                        ('calendar_event_id', '=', event.id),
                        ('state', '=', 'booked'),
                    ])
                    notified = 0
                    for booking in bookings:
                        student_user = booking.student_id.user_ids[:1]
                        if student_user:
                            new_dt_str = _fmt_event_dt(new_start, student_user)
                            senv = self.with_context(lang=student_user.lang or 'en_US')
                            Notif._create_for_user(
                                student_user.id,
                                'class_rescheduled',
                                senv.env._('Class rescheduled: %s', event.name),
                                senv.env._('This class has been moved to %s.', new_dt_str),
                                action_url=f'/my/classes/{event.id}',
                            )
                            notified += 1
                    if teacher and teacher.id:
                        new_dt_str = _fmt_event_dt(new_start, teacher)
                        tenv = self.with_context(lang=teacher.lang or 'en_US')
                        Notif._create_for_user(
                            teacher.id,
                            'class_rescheduled',
                            tenv.env._('Class rescheduled: %s', event.name),
                            tenv.env._('Your class has been moved to %s.', new_dt_str),
                            action_url=f'/my/teacher/classes/{event.id}',
                        )
                    _logger.info(
                        "[RESCHEDULE] '%s' (id=%d): %s → %s, %d student(s) + teacher notified",
                        event.name, event.id, old_start, new_start, notified,
                    )

        return result

    def fitness_reassign_teacher(self, new_teacher_id):
        self.ensure_one()

        if not self.is_fitness_class:
            raise UserError("This is not a fitness class.")

        # 1. Caller must be the CURRENT teacher of this class.
        if self.env.user.id != self.user_id.id:
            raise UserError("You can only reassign your own classes.")

        # 2. Class must be in the future.
        if self.start <= fields.Datetime.now():
            raise UserError("Cannot reassign a class that has already started or passed.")

        # 3. Target must be a valid, different teacher.
        new_teacher = self.env['res.users'].browse(new_teacher_id)
        if not new_teacher.exists() or not new_teacher.has_group('fitness_core.group_fitness_teacher'):
            raise UserError("The selected user is not a registered teacher.")
        if new_teacher.id == self.user_id.id:
            raise UserError(f"{new_teacher.name} is already the teacher for this class.")

        # 4. Clash guard: the new teacher must not already be teaching an
        #    overlapping fitness class at this time.
        overlapping = self.env['calendar.event'].search([
            ('id', '!=', self.id),
            ('user_id', '=', new_teacher.id),
            ('is_fitness_class', '=', True),
            ('start', '<', self.stop),
            ('stop', '>', self.start),
        ], limit=1)
        if overlapping:
            raise UserError(
                f"{new_teacher.name} is already teaching '{overlapping.name}' "
                "at an overlapping time."
            )

        old_teacher_name = self.user_id.name
        # skip_fitness_notification prevents our write() hook from firing;
        # this method sends its own notifications below.
        self.sudo().with_context(skip_fitness_notification=True).write({'user_id': new_teacher.id})
        _logger.info(
            "[TEACHER-SWAP] %s reassigned class %s (id=%d) from %s to %s",
            self.env.user.name, self.name, self.id, old_teacher_name, new_teacher.name,
        )

        # Notify affected students: in-app + email
        affected_bookings = self.env['fitness.booking'].sudo().search([
            ('calendar_event_id', '=', self.id),
            ('state', '=', 'booked'),
        ])
        if affected_bookings:
            notif_model = self.env['fitness.notification'].sudo()
            template = self.env.ref(
                'fitness_teacher_swap.mail_template_teacher_swap',
                raise_if_not_found=False,
            )
            for booking in affected_bookings:
                student_user = booking.student_id.user_ids[:1]
                if student_user:
                    student_env = self.with_context(lang=student_user.lang or 'en_US')
                    notif_model._create_for_user(
                        student_user.id,
                        'teacher_swap',
                        student_env.env._('Teacher updated: %s', self.name),
                        student_env.env._('Your class will now be taught by %s.', new_teacher.name),
                        action_url=f'/my/classes/{self.id}',
                    )
                if template:
                    try:
                        template.send_mail(booking.id, force_send=False)
                    except Exception:
                        _logger.exception(
                            "[TEACHER-SWAP] Failed to queue swap email for booking %d",
                            booking.id,
                        )
            _logger.info(
                "[TEACHER-SWAP] Notified %d student(s) of teacher change on class %d.",
                len(affected_bookings), self.id,
            )
