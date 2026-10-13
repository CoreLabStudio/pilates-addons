# -*- coding: utf-8 -*-
"""Record that a student attended a class she never booked.

This happens. Somebody walks in, the instructor lets her take the class,
and nothing in the system knows. Until now every screen refused to fix
it afterwards: Add a student rejects group classes, Gift one spot lists
only future classes, and a booking made by hand is refused as past with
no payment source. Both times it came up - Laura's free Barre class and
Laia's no-show - it took a one-off script against production.

The engine has always allowed it for a manager, through the
fitness_record_past_attendance context flag that _validate_new_booking
checks. Nothing in the product ever set it. This does.

NOTHING IS SENT. Not to the student, not to the instructor: no email, no
in-app bell, no push. She was there; telling her she has been booked
onto a class she already took, hours later, is noise at best and
confusing at worst. The suppression is asserted by counting rows before
and after, not by trusting a flag, because that is exactly how a
confirmation leaked to a real student once already.
"""
import logging
from datetime import timedelta

import pytz

from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError

from odoo.addons.fitness_core.models.studio_time import studio_tz

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
WINDOW_PARAM = 'fitness.record_attendance_days'
WINDOW_DEFAULT = 14

COURTESY_XMLID = {
    ('barre', 'group'): 'fitness_packages.product_courtesy_barre',
    ('reformer', 'group'): 'fitness_packages.product_courtesy_reformer',
    ('barre', 'private'): 'fitness_packages.product_courtesy_barre_private',
    ('reformer', 'private'):
        'fitness_packages.product_courtesy_reformer_private',
}


class FitnessRecordAttendanceWizard(models.TransientModel):
    _name = 'fitness.record.attendance.wizard'
    _inherit = ['fitness.confirm.once.mixin']
    _description = 'Record an attendance that was never booked'

    calendar_event_id = fields.Many2one(
        'calendar.event', 'Class', required=True,
        domain="[('id', 'in', available_event_ids)]")
    available_event_ids = fields.Many2many(
        'calendar.event', compute='_compute_available_event_ids')
    student_id = fields.Many2one(
        'res.partner', 'Student', required=True,
        help="She does not need an app account. The class goes on her "
             "record either way.")
    pay_with = fields.Selection([
        ('existing', 'A credit she already has'),
        ('trial', 'Her free trial'),
        ('free', 'A free class, given now'),
    ], 'Charge it to', required=True, default='existing')
    reason = fields.Text(
        'Reason', required=True,
        help="Why this is being recorded after the class. It is the only "
             "record anyone will have of it later.")
    seats_label = fields.Char(compute='_compute_seats_label')
    source_label = fields.Char(compute='_compute_source_label')

    # ── what can be recorded ────────────────────────────────────────
    @api.depends('student_id')
    def _compute_available_event_ids(self):
        """Classes that have started, recently, and were not called off."""
        now = fields.Datetime.now()
        days = self._window_days()
        for wiz in self:
            wiz.available_event_ids = self.env['calendar.event'].search([
                ('is_fitness_class', '=', True),
                ('start', '<=', now),
                ('start', '>=', now - timedelta(days=days)),
                ('class_state', '!=', 'cancelled'),
            ], order='start desc', limit=200)

    @api.model
    def _window_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(WINDOW_PARAM)
        try:
            return int(raw) if raw else WINDOW_DEFAULT
        except (TypeError, ValueError):
            _logger.warning(
                "%s is %r, which is not a number; using %s",
                WINDOW_PARAM, raw, WINDOW_DEFAULT)
            return WINDOW_DEFAULT

    @api.depends('calendar_event_id')
    def _compute_seats_label(self):
        for wiz in self:
            event = wiz.calendar_event_id
            wiz.seats_label = self.env._(
                '%(taken)s of %(capacity)s spots taken',
                taken=event.booked_seats or 0,
                capacity=event.capacity or 0) if event else ''

    @api.depends('calendar_event_id', 'student_id', 'pay_with')
    def _compute_source_label(self):
        for wiz in self:
            wiz.source_label = ''
            if not (wiz.calendar_event_id and wiz.student_id):
                continue
            if wiz.pay_with == 'existing':
                try:
                    wiz.source_label = wiz._describe_source(
                        wiz._existing_source())
                except UserError as exc:
                    wiz.source_label = str(exc)
            elif wiz.pay_with == 'trial':
                try:
                    how, what = wiz._trial_plan()
                except UserError as exc:
                    wiz.source_label = str(exc)
                else:
                    wiz.source_label = (
                        wiz._describe_source({'package_order_line_id': what.id})
                        if how == 'held' else
                        self.env._("Her free trial can be used."))
            else:
                product = wiz._courtesy_product()
                wiz.source_label = (
                    self.env._("A free class will be given and used: "
                               "%(name)s", name=product.name)
                    if product else
                    self.env._("There is no free-class product for this "
                               "discipline and session type."))

    def _describe_source(self, source):
        """Say what the engine chose, as the manager would name it."""
        if source.get('package_order_line_id'):
            line = self.env['sale.order.line'].sudo().browse(
                source['package_order_line_id'])
            return self.env._(
                "Her %(product)s (%(order)s), %(left)s left.",
                product=line.product_id.name, order=line.order_id.name,
                left=line.fitness_remaining_classes)
        sub = self.env['sale.order'].sudo().browse(source['subscription_id'])
        return self.env._(
            "Her membership %(name)s.",
            name=sub.fitness_subscription_product_id.name or sub.name)

    # ── the three ways to pay for it ────────────────────────────────
    def _existing_source(self):
        """Whatever the engine itself would choose. Raises if nothing."""
        self.ensure_one()
        return self.env['fitness.booking'].sudo()._select_payment_source(
            self.student_id.id, self.calendar_event_id)

    def _trial_products(self):
        from odoo.addons.fitness_portal.controllers.portal import (
            FitnessStudentPortal,
        )
        out = self.env['product.template'].sudo().browse()
        for xmlid in FitnessStudentPortal.TRIAL_XMLIDS:
            product = self.env.ref(xmlid, raise_if_not_found=False)
            if product:
                out |= product.sudo()
        return out

    def _trial_for_discipline(self):
        event = self.calendar_event_id
        discipline = (event.class_type_id.classroom_type
                      or event.classroom_id.classroom_type or '')
        return self._trial_products().filtered(
            lambda p: p.fitness_class_type == discipline)[:1]

    def _class_day(self):
        """The class's calendar date in Madrid, whoever is asking."""
        return pytz.utc.localize(self.calendar_event_id.start).astimezone(
            studio_tz()).date()

    def _trial_plan(self):
        """How her free trial would pay for this class, without doing it.

        The studio's one rule, in its order - the same pieces trial approval
        uses, asked of fitness.trial.request rather than re-written here:

          1. a trial credit she already holds that covers this class is
             spent, and no new trial is made (a trial she bought, or one
             approved and not yet used);
          2. otherwise, if her one free trial - either discipline - is
             unused, and the offer was open on the day of the class in
             Madrid, a trial is created the way approval creates one;
          3. otherwise the trial cannot pay, and she is pointed at what can.

        This used to ask only whether she had a free trial of THIS class's
        discipline, so it gave a second free trial to a student who had
        bought one, who had had the other discipline's, or who had been
        given one by the walk-in before. The free single class and the desk
        gift are untouched: they are the studio giving on purpose.

        Returns ('held', line) or ('new', product); raises UserError.
        """
        self.ensure_one()
        TR = self.env['fitness.trial.request'].sudo()
        product = self._trial_for_discipline()
        if not product:
            raise UserError(self.env._(
                "There is no trial product for this discipline."))
        student = self.student_id
        held = TR._existing_trial_credit(student, product).fitness_covering(
            self.calendar_event_id)[:1]
        if held:
            return 'held', held
        if TR._trial_already_claimed(student, product):
            raise UserError(self.env._(
                "%(name)s has already had her free trial, and holds no trial "
                "class for this one. Charge it to a credit she already has, "
                "or give her a free class.", name=student.name))
        day = self._class_day()
        if not TR._trial_offer_open(on=day):
            raise UserError(self.env._(
                "The free trial offer had closed by %(day)s, the day of "
                "this class.", day=day))
        return 'new', product

    def _courtesy_product(self):
        event = self.calendar_event_id
        discipline = (event.class_type_id.classroom_type
                      or event.classroom_id.classroom_type or '')
        session = event.session_type or 'group'
        xmlid = COURTESY_XMLID.get((discipline, session))
        if not xmlid:
            return self.env['product.template']
        return self.env.ref(xmlid, raise_if_not_found=False) \
            or self.env['product.template']

    def _zero_order(self, product, free_reason=None):
        event = self.calendar_event_id
        discipline = (event.class_type_id.classroom_type
                      or event.classroom_id.classroom_type or '')
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student_id.id,
            'order_line': [(0, 0, {
                'product_id': product.product_variant_ids[:1].id,
                'product_uom_qty': 1,
                'price_unit': 0.0,
                'fitness_class_type': discipline,
            })],
        })
        if free_reason:
            # A free class given here is given exactly as at the desk:
            # payment method Free and the reason on the order, so it is in
            # Free classes given with who gave it and why.
            order.write({'fitness_payment_method': 'free',
                         'fitness_free_reason': free_reason})
        # Silent: it is given and used in the same step, for a class that
        # is already over.
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order

    # ── doing it ────────────────────────────────────────────────────
    def action_record(self):
        self.ensure_one()
        if not (self.env.user.has_group(MANAGER_GROUP)
                or self.env.user._is_admin()):
            raise AccessError(self.env._(
                "Only a studio manager can record an attendance."))
        if not (self.reason or '').strip():
            raise UserError(self.env._(
                "Say why this is being recorded after the class. It is the "
                "only record anyone will have of it later."))

        event = self.calendar_event_id
        now = fields.Datetime.now()
        if event.class_state == 'cancelled':
            raise UserError(self.env._(
                "'%(name)s' was cancelled, so nobody attended it.",
                name=event.name))
        if event.start > now:
            raise UserError(self.env._(
                "'%(name)s' has not happened yet. Book her onto it the "
                "ordinary way.", name=event.name))
        days = self._window_days()
        if (now - event.start).days > days:
            raise UserError(self.env._(
                "'%(name)s' was more than %(days)s days ago. Attendance is "
                "recorded within %(days)s days; after that it is history "
                "and somebody should look at it properly.",
                name=event.name, days=days))
        if event.capacity and (event.booked_seats or 0) >= event.capacity:
            raise UserError(self.env._(
                "'%(name)s' is full - %(taken)s of %(capacity)s spots "
                "taken. Recording her would put the class over its own "
                "capacity; check who else is on the roster first.",
                name=event.name, taken=event.booked_seats,
                capacity=event.capacity))

        # Every refusal is above this line. From here the dialog does its
        # work once: a second press would book her twice, spend a second
        # credit or give a second free class. See fitness_core/models/
        # confirm_once.py.
        self._fitness_confirm_once()

        gift_order = False
        if self.pay_with == 'existing':
            vals = self._existing_source()
        elif self.pay_with == 'trial':
            how, what = self._trial_plan()
            if how == 'held':
                vals = {'package_order_line_id': what.id}
            else:
                # Made by the code that approves a trial request, priced on
                # the class's day, and confirmed in silence: nobody is told
                # about an attendance recorded after the fact.
                gift_order = self.env['fitness.trial.request'].sudo().with_context(
                    skip_fitness_notification=True)._create_trial_order(
                        self.student_id, what, self._class_day())
                vals = {'package_order_line_id': gift_order.order_line[:1].id}
        else:
            product = self._courtesy_product()
            if not product:
                raise UserError(self.env._(
                    "There is no free-class product for this discipline and "
                    "session type, so there is nothing to record it "
                    "against."))
            gift_order = self._zero_order(
                product, free_reason=(self.reason or '').strip())
            vals = {'package_order_line_id': gift_order.order_line[:1].id}

        booking_vals = {
            'student_id': self.student_id.id,
            'calendar_event_id': event.id,
            'manager_override_timewindow': True,
        }
        booking_vals.update(vals)

        # Silence on every channel, and the past-booking permission the
        # engine re-checks against the manager group for itself.
        quiet = dict(
            self.env.context,
            fitness_record_past_attendance=True,
            skip_fitness_notification=True,
        )
        booking = self.env['fitness.booking'].sudo().with_context(
            **quiet).create(booking_vals)

        # Marked by the manager doing it, dated to the class rather than to
        # now, because that is when she was there.
        booking.with_context(**quiet).sudo().write({
            'state': 'attended',
            'marked_by_id': self.env.uid,
            'marked_date': event.start,
            'fitness_recorded_after_the_fact': True,
        })

        booking.sudo().message_post(body=self.env._(
            "Attendance recorded after the class by %(who)s. She attended "
            "%(klass)s and it was never booked. Reason: %(reason)s",
            who=self.env.user.name, klass=event.name,
            reason=(self.reason or '').strip()))

        _logger.info(
            "[RECORD-ATTENDANCE] %s on %s by %s, paid with %s (reason: %s)",
            self.student_id.display_name, event.name, self.env.user.login,
            self.pay_with, (self.reason or '').strip()[:60])

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fitness.booking',
            'res_id': booking.id,
            'view_mode': 'form',
            'target': 'current',
        }
