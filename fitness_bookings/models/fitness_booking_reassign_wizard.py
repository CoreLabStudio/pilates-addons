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

    # Every booking that was ticked. booking_id stays as the first of them so
    # the related fields below - student, class, date - still describe
    # something, and a single selection behaves exactly as it always did.
    booking_ids = fields.Many2many('fitness.booking', string='Bookings')
    # Writable, and it writes through to booking_ids. Anything that creates the
    # wizard with a single booking - the form view, the tests, any caller that
    # predates multi-select - keeps working unchanged.
    booking_id = fields.Many2one(
        'fitness.booking', compute='_compute_booking_id',
        inverse='_inverse_booking_id', store=False, readonly=False)
    booking_count = fields.Integer(compute='_compute_booking_id')

    @api.depends('booking_ids')
    def _compute_booking_id(self):
        for wiz in self:
            wiz.booking_id = wiz.booking_ids[:1]
            wiz.booking_count = len(wiz.booking_ids)

    def _inverse_booking_id(self):
        for wiz in self:
            if wiz.booking_id and wiz.booking_id not in wiz.booking_ids:
                wiz.booking_ids = [(4, wiz.booking_id.id)]

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
    reason = fields.Text(
        'Reason',
        help="Optional. Goes to the student with the message they already "
             "get, whether they are moved or cancelled, and is kept on the "
             "booking when it is a cancellation.")

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
        # sudo: a fitness manager is not a Sales user, and reading the credit
        # line raises AccessError on sale.order.line for every manager except
        # the owner, who happens to be an administrator. That made the move
        # impossible for anybody she delegated to, while working perfectly
        # for her - so it never showed up in her own testing.
        #
        # Taken here rather than at each call site so a future caller cannot
        # forget it. Reading the pool to decide coverage is the wizard's own
        # business; nothing about the line is shown to anyone.
        line = line.sudo()
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
            bookings = wiz.booking_ids or wiz.booking_id
            event = wiz.booking_id.calendar_event_id
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
            # A class has to work for every student that was ticked, not just
            # the first: five bookings can hold five different credits, and a
            # target that suits one may not be covered for another.
            for other in bookings:
                other_line = other.package_order_line_id.sudo()
                if other_line:
                    candidates = candidates.filtered(
                        lambda e: wiz._line_covers(other_line, e))
            line = wiz.booking_id.package_order_line_id.sudo()
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
            # Room for all of them, not room for one. Offering a class with two
            # seats left to a selection of five is how a bulk move half
            # succeeds and leaves the desk to work out which half.
            needed = max(len(bookings), 1)
            free = candidates.filtered(
                lambda e: not e.capacity or e.available_seats >= needed)
            wiz.available_event_ids = [(6, 0, free.ids)]

    # ── outcomes ─────────────────────────────────────────────────────────────
    def action_cancel_only(self):
        """Cancel, and leave the student where they chose to be: nowhere."""
        self.ensure_one()
        for booking in (self.booking_ids or self.booking_id):
            self._do_cancel(booking)
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
        target = self.target_event_id
        for booking in (self.booking_ids or self.booking_id):
            self._move_one(booking, target)
        return {'type': 'ir.actions.act_window_close'}

    def _move_one(self, booking, target):
        """One booking, checked on its own terms.

        Deliberately per booking rather than once for the selection: five
        students ticked together can hold five different credits and five
        different cancellation windows, and a rule that passes for the first
        says nothing about the fifth.
        """
        origin = booking.calendar_event_id
        if booking.state == 'cancelled':
            raise UserError(_("That booking is already cancelled."))
        if target == origin:
            raise UserError(_("They are already in that class."))

        self._validate_move(target, booking)

        # The write does the rest. fitness.booking.write() recounts both
        # rosters and tells the student, because a booking can also be moved
        # by editing the field on the form - which used to do neither. Doing
        # it here as well would count twice and send two messages about one
        # move, so this passes the reason down and gets out of the way.
        booking.with_context(
            move_reason=(self.reason or '').strip() or False
        ).write({'calendar_event_id': target.id})

    def _validate_move(self, target, booking=None):
        """The booking rules that still apply when nobody is paying again.

        The payment-source check is deliberately absent - the credit is spent
        and stays spent. Coverage is checked instead, so the pool that paid for
        the old class is one that could have paid for the new one.
        """
        booking = booking or self.booking_id
        student = booking.student_id
        now = fields.Datetime.now()

        if not target.start or target.start <= now:
            raise UserError(_(
                "'%(name)s' has already started.", name=target.name))

        if target.class_state == 'cancelled':
            raise UserError(_(
                "'%(name)s' is cancelled.", name=target.name))

        line = booking.package_order_line_id.sudo()
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

    def _do_cancel(self, booking=None):
        booking = booking or self.booking_id
        if booking.state == 'cancelled':
            raise UserError(_("That booking is already cancelled."))
        # A box of spaces is an empty box.
        reason = (self.reason or '').strip()
        booking.with_context(
            _admin_cancel_direct=True,
            admin_force_refund=bool(self.restore_credit),
            cancel_reason=reason or False,
        ).action_cancel()
