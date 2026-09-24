# -*- coding: utf-8 -*-
"""Giving something away, and remembering that you did.

Until now a free class was given through the Roster's "Add student" screen,
in courtesy mode, and a free pack or membership could not be given at all
without pretending to sell one at zero. Neither left a record anybody could
look at later: the only trace was a chatter line on an order, findable if
you already knew which order to open.

Two things live here. The wizard, which gives one student one thing, free,
by exactly the route a purchase takes - a confirmed order at zero, and for a
class a real booking - so she is notified, credited and booked the same way
as if she had paid. And the log, which is the answer to "what have we given
away", a question the studio could not previously ask at all.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'

# The zero-price products a gifted class is booked against, per discipline.
# They never appear in the shop; a gifted class has to be booked against
# something, and booking it against a saleable product would put a zero-price
# class in the catalogue.
COURTESY_PRODUCT_XMLID = {
    'reformer': 'fitness_packages.product_courtesy_reformer',
    'barre': 'fitness_packages.product_courtesy_barre',
}


class FitnessGiftLog(models.Model):
    """Every gift ever given. Written by the wizard, never by hand.

    A plain model rather than chatter on the order: the studio's question is
    "what have we given away, and why", which nobody can answer by opening
    orders one at a time. Kept even if the order behind it is later
    cancelled - the fact that it was given is the record, and undoing the
    credit does not undo the decision.
    """
    _name = 'fitness.gift.log'
    _description = 'Free Gift'
    _order = 'given_on desc, id desc'
    _rec_name = 'display_name_computed'

    student_id = fields.Many2one(
        'res.partner', 'Student', required=True, ondelete='restrict',
        index=True)
    gift_type = fields.Selection([
        ('class', 'Class'),
        ('package', 'Package'),
        ('membership', 'Membership'),
    ], 'Type', required=True, index=True)
    product_id = fields.Many2one(
        'product.template', 'What was given', ondelete='restrict')
    calendar_event_id = fields.Many2one(
        'calendar.event', 'Class', ondelete='set null',
        help="The class the spot was given in, when the gift was a class.")
    reason = fields.Text('Reason', required=True)
    given_on = fields.Datetime(
        'Given', required=True, default=fields.Datetime.now, index=True)
    given_by = fields.Many2one(
        'res.users', 'Given by', required=True,
        default=lambda self: self.env.user, ondelete='restrict')
    order_id = fields.Many2one('sale.order', 'Order', ondelete='set null')
    booking_id = fields.Many2one(
        'fitness.booking', 'Booking', ondelete='set null')
    value = fields.Monetary(
        'Value given away', currency_field='currency_id',
        help="What the student would have paid. Zero was charged; this is "
             "what the studio chose not to take.")
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    display_name_computed = fields.Char(compute='_compute_display_name_field')

    @api.depends('student_id', 'gift_type', 'product_id')
    def _compute_display_name_field(self):
        for log in self:
            what = log.product_id.name or dict(
                self._fields['gift_type'].selection).get(log.gift_type, '')
            log.display_name_computed = '%s - %s' % (
                log.student_id.name or '?', what)


class FitnessGiftWizard(models.TransientModel):
    """Give one student one thing, free.

    One wizard behind both entry points - a student's profile and a class on
    the timetable - because they are the same decision reached from two
    directions, and two wizards would be two sets of rules about who may be
    given what.
    """
    _name = 'fitness.gift.wizard'
    _description = 'Give a Free Gift'

    student_id = fields.Many2one(
        'res.partner', 'Student', required=True,
        domain="[('is_company', '=', False)]")
    gift_type = fields.Selection([
        ('class', 'A class'),
        ('package', 'A package'),
        ('membership', 'A membership'),
    ], 'Give', required=True, default='class')

    calendar_event_id = fields.Many2one(
        'calendar.event', 'Which class',
        domain="[('id', 'in', available_event_ids)]")
    available_event_ids = fields.Many2many(
        'calendar.event', compute='_compute_available_event_ids')
    seats_label = fields.Char(compute='_compute_seats_label')

    product_id = fields.Many2one(
        'product.template', 'Which one',
        domain="[('id', 'in', available_product_ids)]")
    available_product_ids = fields.Many2many(
        'product.template', compute='_compute_available_product_ids')
    plan_id = fields.Many2one('sale.subscription.plan', 'Billing period')

    reason = fields.Text(
        'Reason', required=True,
        help="Why this is being given. It is the only record anyone will "
             "have of it later.")
    value = fields.Monetary(
        'Normally costs', compute='_compute_value',
        currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # ── what can be given ───────────────────────────────────────────────────

    @api.depends('gift_type')
    def _compute_available_event_ids(self):
        """Classes a spot can actually be given in.

        Still to come, not cancelled, and a fitness class - the studio should
        never be offered a slot that cannot be filled. Full classes are left
        in the list rather than hidden, because the seat count is shown and
        the studio may be deciding to squeeze somebody in; action_give
        refuses it, so the rule is enforced where it matters.
        """
        now = fields.Datetime.now()
        for wiz in self:
            wiz.available_event_ids = self.env['calendar.event'].search([
                ('is_fitness_class', '=', True),
                ('start', '>', now),
                ('class_state', '!=', 'cancelled'),
            ], order='start', limit=200)

    @api.depends('gift_type')
    def _compute_available_product_ids(self):
        for wiz in self:
            if wiz.gift_type == 'package':
                domain = [('fitness_is_package', '=', True),
                          ('fitness_class_count', '>', 1)]
            elif wiz.gift_type == 'membership':
                domain = [('fitness_is_subscription_plan', '=', True)]
            else:
                wiz.available_product_ids = False
                continue
            wiz.available_product_ids = self.env['product.template'].search(
                domain + [('sale_ok', '=', True)], order='name')

    @api.depends('calendar_event_id')
    def _compute_seats_label(self):
        """The real count, so the studio picks a class that has room."""
        for wiz in self:
            event = wiz.calendar_event_id
            if not event:
                wiz.seats_label = ''
                continue
            capacity = event.capacity or 0
            taken = event.booked_seats or 0
            wiz.seats_label = (
                self.env._('%(taken)s of %(capacity)s spots taken',
                           taken=taken, capacity=capacity)
                if capacity else
                self.env._('%(taken)s booked', taken=taken))

    @api.depends('gift_type', 'product_id', 'calendar_event_id')
    def _compute_value(self):
        for wiz in self:
            if wiz.gift_type == 'class':
                product = wiz._courtesy_product()
                wiz.value = wiz.calendar_event_id and (
                    product.list_price if product else 0.0) or 0.0
            else:
                wiz.value = wiz.product_id.list_price or 0.0

    @api.onchange('gift_type')
    def _onchange_gift_type(self):
        """Clear the other branch's choice, so a type change cannot leave a
        membership selected while the wizard is set to give a class."""
        if self.gift_type == 'class':
            self.product_id = False
            self.plan_id = False
        else:
            self.calendar_event_id = False

    def _courtesy_product(self):
        self.ensure_one()
        event = self.calendar_event_id
        if not event:
            return self.env['product.template']
        discipline = (event.class_type_id.classroom_type
                      or event.class_type_id.fitness_class_type
                      if event.class_type_id else None)
        xmlid = COURTESY_PRODUCT_XMLID.get(discipline)
        if not xmlid:
            return self.env['product.template']
        return self.env.ref(xmlid, raise_if_not_found=False) \
            or self.env['product.template']

    # ── giving it ───────────────────────────────────────────────────────────

    def action_give(self):
        self.ensure_one()
        if not (self.env.user.has_group(MANAGER_GROUP)
                or self.env.user._is_admin()):
            raise AccessError(self.env._(
                "Only studio managers can give a free gift."))
        if not (self.reason or '').strip():
            raise UserError(self.env._(
                "Say why this is being given. It is the only record anyone "
                "will have of it later."))

        if self.gift_type == 'class':
            log = self._give_a_class()
        else:
            log = self._give_a_product()

        _logger.info(
            "[GIFT] %s given %s to %s by %s (reason: %s)",
            self.gift_type, log.product_id.name or '-',
            self.student_id.name, self.env.user.name,
            (self.reason or '').strip()[:60])
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fitness.gift.log',
            'res_id': log.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _zero_order(self, product, plan=None):
        """A real order at zero, confirmed.

        Not a shortcut around the purchase machinery but a pass straight
        through it: confirming is what mints credits, starts a membership and
        notifies the student, and a gift that skipped it would leave her with
        something a purchase would not have given her.
        """
        vals = {
            'partner_id': self.student_id.id,
            'fitness_payment_method': 'free',
        }
        if plan:
            vals['plan_id'] = plan.id
        order = self.env['sale.order'].sudo().create(vals)
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            'price_unit': 0.0,
        })
        order.action_confirm()
        order.message_post(body=self.env._(
            "Given free by %(user)s. Reason: %(reason)s",
            user=self.env.user.name, reason=(self.reason or '').strip()))
        return order

    def _give_a_class(self):
        event = self.calendar_event_id
        if not event:
            raise UserError(self.env._("Choose the class to give a spot in."))
        if event.class_state == 'cancelled':
            raise UserError(self.env._(
                "'%(name)s' is cancelled. Put it back on the timetable "
                "first.", name=event.name))
        if event.capacity and (event.booked_seats or 0) >= event.capacity:
            raise UserError(self.env._(
                "'%(name)s' is full - %(taken)s of %(capacity)s spots taken.",
                name=event.name, taken=event.booked_seats,
                capacity=event.capacity))

        product = self._courtesy_product()
        if not product:
            raise UserError(self.env._(
                "There is no free-class product for this discipline, so "
                "there is nothing to book the spot against."))

        order = self._zero_order(product)
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': self.student_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': order.order_line[:1].id,
            'manager_override_timewindow': True,
        })
        return self.env['fitness.gift.log'].sudo().create({
            'student_id': self.student_id.id,
            'gift_type': 'class',
            'product_id': product.id,
            'calendar_event_id': event.id,
            'reason': (self.reason or '').strip(),
            'given_by': self.env.user.id,
            'order_id': order.id,
            'booking_id': booking.id,
            'value': product.list_price or 0.0,
        })

    def _give_a_product(self):
        product = self.product_id
        if not product:
            raise UserError(self.env._("Choose what to give."))
        plan = self.plan_id if self.gift_type == 'membership' else None
        if self.gift_type == 'membership' and not plan:
            raise UserError(self.env._(
                "Choose the billing period for the membership."))

        order = self._zero_order(product, plan=plan)
        return self.env['fitness.gift.log'].sudo().create({
            'student_id': self.student_id.id,
            'gift_type': self.gift_type,
            'product_id': product.id,
            'reason': (self.reason or '').strip(),
            'given_by': self.env.user.id,
            'order_id': order.id,
            'value': product.list_price or 0.0,
        })
