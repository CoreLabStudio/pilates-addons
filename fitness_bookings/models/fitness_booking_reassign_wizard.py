# -*- coding: utf-8 -*-
"""Cancel one student's booking, and optionally put them in another class.

Cancelling a single student used to mean cancelling and then telling them to
go and rebook themselves, which is the studio doing half a job: the person who
knows a space just opened is the person at the desk, not the student at home.
This does both in one step - and, deliberately, will do only the first.

The assignment is optional on purpose. A student who wants their credit back
and no replacement must not be moved somewhere they did not ask to go, so
"Cancel only" is a first-class outcome rather than a thing you reach by
leaving a field blank and hoping.

Reached from both sides of the same fact: from the student's booking under
Students, and from the class roster under Classes. One wizard either way, so
the two entry points cannot drift apart.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FitnessBookingReassignWizard(models.TransientModel):
    _name = 'fitness.booking.reassign.wizard'
    _description = 'Cancel a booking, optionally moving the student'

    booking_id = fields.Many2one(
        'fitness.booking', required=True, ondelete='cascade', readonly=True)

    student_id = fields.Many2one(related='booking_id.student_id', readonly=True,
                                 string='Student')
    from_event_id = fields.Many2one(related='booking_id.calendar_event_id',
                                    readonly=True, string='Leaving')
    from_start = fields.Datetime(related='booking_id.calendar_event_id.start',
                                 readonly=True, string='Class date')

    target_event_id = fields.Many2one(
        'calendar.event', string='Move to',
        domain="[('id', 'in', available_event_ids)]",
        help="Leave empty to cancel without moving the student anywhere.")
    available_event_ids = fields.Many2many(
        'calendar.event', compute='_compute_available_event_ids')

    restore_credit = fields.Boolean(
        'Return the credit', default=True,
        help="Applies to a cancellation inside the studio's cancellation "
             "window, where credit would not normally come back.")

    # ── what a credit actually covers ────────────────────────────────────────
    @staticmethod
    def _event_studio(event):
        return (event.class_type_id.classroom_type
                or event.classroom_id.classroom_type)

    def _line_covers(self, line, event):
        """Whether the credit already spent on this booking covers that class.

        Mirrors the payment-source rules exactly: a pool is tied to a
        discipline and to a session type, and 'any' covers every discipline.
        A move must honour these - otherwise a Barre credit quietly pays for a
        Reformer class, which is the one thing the booking rules exist to stop.
        """
        if not line:
            return False
        product = line.product_id
        pool_type = line.fitness_class_type or product.fitness_class_type
        if pool_type not in ('any', self._event_studio(event)):
            return False
        return product.fitness_session_type == event.session_type

    @api.depends('booking_id')
    def _compute_available_event_ids(self):
        """Classes this student could actually be moved into.

        Only classes the booking rules would accept, so the desk is never
        offered a choice that fails on submit. That means: still to come, not
        cancelled, a seat free, not the class they are already in - and, above
        all, covered by the credit already on this booking.

        It used to filter on class_type_id alone, and only when the class had
        one set; a class without a type offered every class in the studio and
        the move then failed with a payment-source error that named nothing
        the desk could act on.
        """
        for wiz in self:
            booking = wiz.booking_id
            event = booking.calendar_event_id
            if not event:
                wiz.available_event_ids = False
                continue
            domain = [
                ('is_fitness_class', '=', True),
                ('id', '!=', event.id),
                ('start', '>', fields.Datetime.now()),
                ('class_state', '!=', 'cancelled'),
            ]
            candidates = self.env['calendar.event'].search(
                domain, order='start', limit=200)
            line = booking.package_order_line_id
            if line:
                candidates = candidates.filtered(
                    lambda e: wiz._line_covers(line, e))
            elif event.class_type_id:
                # No package line - a subscription booking. Coverage depends on
                # the plan rather than a pool, so stay conservative and offer
                # the same class type only.
                candidates = candidates.filtered(
                    lambda e: e.class_type_id == event.class_type_id)
            # Capacity is computed, so it is filtered here rather than in the
            # domain: a full class must not be offered as an option.
            free = candidates.filtered(
                lambda e: not e.capacity or e.available_seats > 0)
            wiz.available_event_ids = [(6, 0, free.ids)]

    # ── outcomes ─────────────────────────────────────────────────────────────
    def action_cancel_only(self):
        """Cancel, and leave the student where they chose to be: nowhere."""
        self.ensure_one()
        self._do_cancel()
        return {'type': 'ir.actions.act_window_close'}
        # act_window_close, not act_window_closed. The second is not an
        # action type Odoo knows; call_button validates what a button
        # returns and raises on it, which rolls the transaction back -
        # so the work is undone and the desk sees an error on a move
        # that had in fact just succeeded. Model-level tests never go
        # through call_button and cannot catch it.

    def action_move_student(self):
        """Move this booking to another class. Nothing is cancelled or re-sold.

        This used to cancel the booking and create a fresh one, which made the
        new booking look for a credit to spend - and there was none, because
        the credit had just been handed back, or in the case of a trial had
        never been a spendable pool line at all. The desk got "No active
        subscription or package covers this class type" while holding a
        booking that was already paid for. Being a manager did not help: that
        is a payment-source rule, not a permission.

        A move is not a sale. The booking keeps its row and its
        package_order_line_id and only changes which class it points at, so
        there is no credit to return and none to find. Trials move for the
        same reason - the claim stays attached to the booking that holds it.

        fitness.booking has no write() override, so none of the booking rules
        fire on a plain write. They are enforced here instead, and deliberately
        re-checked server-side rather than trusted to the dropdown.
        """
        self.ensure_one()
        if not self.target_event_id:
            raise UserError(_(
                "Choose a class to move %(name)s into, or use Cancel Only.",
                name=self.student_id.name or _('this student'),
            ))
        booking = self.booking_id
        target = self.target_event_id
        origin = booking.calendar_event_id
        if booking.state == 'cancelled':
            raise UserError(_("That booking is already cancelled."))
        if target == origin:
            raise UserError(_("They are already in that class."))

        self._validate_move(target)
        booking.write({'calendar_event_id': target.id})

        # The student has to hear about this: they did not ask to be moved,
        # and the class they think they are attending is no longer theirs.
        booking._notify_moved(origin)

        # Both rosters changed, so both seat counts are stale.
        booking._refresh_booked_seats()
        if origin:
            count = self.env['fitness.booking'].search_count([
                ('calendar_event_id', '=', origin.id),
                ('state', 'in', ('booked', 'attended')),
            ])
            origin.sudo().booked_seats = count
        return {'type': 'ir.actions.act_window_close'}

    def _validate_move(self, target):
        """The booking rules that still apply when nobody is paying again.

        The payment-source check is deliberately absent - the credit is spent
        and stays spent. Coverage is checked instead, so the pool that paid for
        the old class is one that could have paid for the new one.
        """
        booking = self.booking_id
        student = booking.student_id
        now = fields.Datetime.now()

        if not target.start or target.start <= now:
            raise UserError(_(
                "'%(name)s' has already started.", name=target.name))

        if target.class_state == 'cancelled':
            raise UserError(_(
                "'%(name)s' is cancelled.", name=target.name))

        line = booking.package_order_line_id
        if line and not self._line_covers(line, target):
            raise UserError(_(
                "The credit on this booking does not cover '%(name)s'. It "
                "was bought for a different kind of class, so moving them "
                "there would spend a credit they do not have.",
                name=target.name))

        Booking = self.env['fitness.booking']
        booked = Booking.search_count([
            ('calendar_event_id', '=', target.id),
            ('state', 'in', ('booked', 'attended')),
        ])
        if target.capacity and booked >= target.capacity:
            raise UserError(_(
                "'%(name)s' is full - %(booked)s/%(capacity)s seats taken.",
                name=target.name, booked=booked, capacity=target.capacity))

        duplicate = Booking.search([
            ('id', '!=', booking.id),
            ('student_id', '=', student.id),
            ('calendar_event_id', '=', target.id),
            ('state', 'in', ('booked', 'attended', 'no_show')),
        ], limit=1)
        if duplicate:
            raise UserError(_(
                "%(student)s is already booked into '%(name)s'.",
                student=student.name, name=target.name))

        # Excludes this booking: it is the one being moved, and it cannot
        # clash with itself.
        overlapping = Booking.search([
            ('id', '!=', booking.id),
            ('student_id', '=', student.id),
            ('state', 'in', ('booked', 'attended')),
            ('calendar_event_id.start', '<', target.stop),
            ('calendar_event_id.stop', '>', target.start),
        ], limit=1)
        if overlapping:
            raise UserError(_(
                "%(student)s already has a booking that overlaps that time "
                "(%(clash)s).",
                student=student.name,
                clash=overlapping.calendar_event_id.name))

    def _do_cancel(self):
        booking = self.booking_id
        if booking.state == 'cancelled':
            raise UserError(_("That booking is already cancelled."))
        booking.with_context(
            _admin_cancel_direct=True,
            admin_force_refund=bool(self.restore_credit),
        ).action_cancel()
