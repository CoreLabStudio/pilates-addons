# -*- coding: utf-8 -*-
"""Put a student into a class from the class itself, on her own credit.

A private class is agreed in conversation, and somebody then has to
actually make the booking. This is where: Add a student, on the class's
Roster.

It used to do that by SELLING the class: it created a new confirmed order
at the typed price and booked against it, every time, without looking at
what she already held. A student with a private class left on her pack
was charged again and kept the class she had paid for (defect A6).

Owner decision Q2: it uses her existing credit and never charges. Which
credit is the payment engine's choice - _select_payment_source, the same
one a booking she makes herself goes through, so the soonest-expiring
source that covers this class is spent and a cancelled order's credit
never is. If she holds nothing that covers the class, the dialog says so
and offers the desk, which is where the studio sells; once she has the
credit, Add a student books it.

What it still does NOT do:

  * bypass fitness.booking.create(). Every rule still runs - capacity,
    duplicates, overlapping bookings, the opening date. The one thing it
    may waive is the seven-day booking window, and only through
    manager_override_timewindow, which re-checks the group itself. A
    private class is routinely agreed weeks ahead.
  * create an order. Nothing here can charge her.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FitnessAddStudentWizard(models.TransientModel):
    _name = 'fitness.add.student.wizard'
    _description = 'Add a student to this class'

    #: where a student with no credit is sent. fitness_portal depends on
    #: this module, so the desk is found by xmlid at run time, not imported.
    DESK_ACTION_XMLID = 'fitness_portal.action_fitness_desk_sale'

    event_id = fields.Many2one(
        'calendar.event', string='Class', required=True, readonly=True)
    student_id = fields.Many2one(
        'res.partner', string='Student', required=True,
        help="Any contact. The booking is made against them, paid with "
             "credit they already hold.")

    # Shown, not computed at save: the studio should see the room it has
    # before it picks a student, not after being refused.
    # depends_context='lang': the value below is a translated string, and
    # Odoo partitions a computed field's cache only by the context keys the
    # field declares. Without it the first language to compute it in a
    # transaction is handed to every later reader in that transaction.
    seats_label = fields.Char(
        compute='_compute_seats_label', depends_context=('lang',))
    is_private = fields.Boolean(compute='_compute_seats_label')

    # What will pay, said before anybody presses anything.
    has_credit = fields.Boolean(compute='_compute_credit')
    credit_label = fields.Char(
        string='Paid with', compute='_compute_credit',
        depends_context=('lang',))

    @api.depends('event_id')
    def _compute_seats_label(self):
        for wiz in self:
            event = wiz.event_id
            capacity = event.capacity or 0
            taken = event.booked_seats or 0
            wiz.is_private = event.session_type != 'group' or (
                event.class_type_id.session_type or 'group') != 'group'
            if not capacity:
                wiz.seats_label = _("%(taken)s booked", taken=taken)
            else:
                wiz.seats_label = _(
                    "%(taken)s of %(capacity)s booked, %(free)s free",
                    taken=taken, capacity=capacity,
                    free=max(0, capacity - taken))

    def _source(self):
        """The engine's choice for this student and class, or None."""
        self.ensure_one()
        if not (self.student_id and self.event_id):
            return None
        try:
            return self.env['fitness.booking'].sudo()._select_payment_source(
                self.student_id.id, self.event_id)
        except UserError:
            return None

    @api.depends('student_id', 'event_id')
    def _compute_credit(self):
        for wiz in self:
            source = wiz._source()
            wiz.has_credit = bool(source)
            if not wiz.student_id:
                wiz.credit_label = False
            elif not source:
                wiz.credit_label = _(
                    "Nothing she holds covers this class.")
            elif source.get('package_order_line_id'):
                line = self.env['sale.order.line'].sudo().browse(
                    source['package_order_line_id'])
                wiz.credit_label = _(
                    "%(product)s (%(order)s), %(left)s left",
                    product=line.product_id.name, order=line.order_id.name,
                    left=line.fitness_remaining_classes)
            else:
                sub = self.env['sale.order'].sudo().browse(
                    source['subscription_id'])
                wiz.credit_label = _(
                    "Membership %(name)s",
                    name=sub.fitness_subscription_product_id.name or sub.name)

    @api.model
    def default_get(self, fields_list):
        """Opened from a class, so the class comes with it."""
        res = super().default_get(fields_list)
        event_id = self.env.context.get('default_event_id') \
            or self.env.context.get('active_id')
        if event_id and self.env.context.get('active_model') in (
                'calendar.event', None):
            event = self.env['calendar.event'].browse(event_id)
            if event.exists():
                res['event_id'] = event.id
        return res

    def _check_manager(self):
        if not self.env.user.has_group('fitness_core.group_fitness_manager') \
                and not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only studio managers can add a student to a class."))

    def action_open_desk(self):
        """She has no credit for this class: sell her one at the desk."""
        self.ensure_one()
        self._check_manager()
        if not self.env.ref(self.DESK_ACTION_XMLID, raise_if_not_found=False):
            raise UserError(_("The desk is not installed on this database."))
        action = self.env['ir.actions.actions']._for_xml_id(
            self.DESK_ACTION_XMLID)
        action['context'] = {'default_partner_id': self.student_id.id}
        return action

    def action_add(self):
        """Book her on this class, paid with credit she already holds."""
        self.ensure_one()
        self._check_manager()

        event = self.event_id
        if event.class_state == 'cancelled':
            raise UserError(_(
                "That class is cancelled. Put it back on the timetable first."))

        # Checked here as well as inside create(), the same way the Clase Fija
        # placement does, so a full class is refused with a sentence about
        # this class rather than a generic booking error.
        if event.capacity and (event.booked_seats or 0) >= event.capacity:
            raise UserError(_(
                "'%(name)s' is full - %(taken)s/%(capacity)s seats taken.",
                name=event.name, taken=event.booked_seats,
                capacity=event.capacity))

        source = self._source()
        if not source:
            # Over RPC there is no dialog to show the desk button on, so the
            # refusal itself says where to go.
            raise UserError(_(
                "%(student)s holds no credit that covers this class, so "
                "nothing was booked and nothing was charged. Sell her a "
                "class at the desk, then add her here.",
                student=self.student_id.display_name))
        paid_with = self.credit_label

        vals = {
            'student_id': self.student_id.id,
            'calendar_event_id': event.id,
            # A private class is agreed weeks ahead as a matter of course, so
            # the seven-day window has to give. Through the flag the model
            # already re-checks, not around it.
            'manager_override_timewindow': True,
        }
        vals.update(source)
        booking = self.env['fitness.booking'].create(vals)

        booking.sudo().message_post(body=_(
            "Added to %(name)s by %(who)s, paid with her existing credit: "
            "%(source)s. Nothing was charged.",
            name=event.name, who=self.env.user.name, source=paid_with))
        _logger.info(
            "[ADD STUDENT] %s booked onto %s (%s) by %s on her own credit %s",
            self.student_id.display_name, event.name, event.start,
            self.env.user.login, source)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Student added"),
                'message': _(
                    "%(student)s is booked on %(name)s, paid with %(source)s. "
                    "Nothing was charged.",
                    student=self.student_id.display_name, name=event.name,
                    source=paid_with),
                'type': 'success',
                'sticky': False,
                # The roster behind the dialog is stale the moment this
                # returns; without a reload the studio adds the same student
                # twice because the list still shows them missing.
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
