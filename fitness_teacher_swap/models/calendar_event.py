from odoo import models, fields
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    """Adds one-class-at-a-time teacher reassignment for the teacher portal page.

    All checks run against self.env.user (the actual caller, NEVER sudo) before
    any write happens. Only the final write — after every check has passed —
    is escalated via sudo(), since portal/teacher accounts are not given broad
    ORM write access to calendar.event via ir.model.access (see manifest: no
    new access rows are added by this module).
    """
    _inherit = 'calendar.event'

    # Minimal override: turn on chatter tracking for the organizer field so
    # every teacher change (swap or otherwise) is logged automatically.
    # string/comodel/default/etc. are untouched and inherit from base calendar.
    user_id = fields.Many2one(tracking=True)

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
        # Suppress fitness_notifications (it doesn't hook calendar.event today,
        # but this guarantees silence even if that ever changes) while still
        # persisting the change so students see the new teacher immediately.
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
                    notif_model._create_for_user(
                        student_user.id,
                        'teacher_swap',
                        f'Teacher updated: {self.name}',
                        f'Your class will now be taught by {new_teacher.name}.',
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
