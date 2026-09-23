# -*- coding: utf-8 -*-
"""Put a student into a class from the class itself.

A private class is agreed in conversation: the student taps Contact on the
shop card, the studio works out which class and when, and then somebody has
to actually make the booking. Until now that last step had no home. The
Roster on a class is read-only, and creating a booking by hand from Student
Bookings fails for exactly the case it is needed for - a student with no
private credit is refused by _select_payment_source with "No active
subscription or package covers this class type", because the credit is the
thing that was agreed verbally and never recorded.

So this does both halves in one action: it records what was agreed as a real
paid line, and books the student on the back of it.

Two things it deliberately does NOT do:

  * It does not bypass fitness.booking.create(). Every rule still runs -
    capacity, duplicates, overlapping bookings, the opening date. The one
    thing it may waive is the seven-day booking window, and only through
    manager_override_timewindow, which re-checks the group itself. A private
    class is routinely agreed weeks ahead; that is the whole point of
    agreeing it.
  * It does not touch _select_payment_source. That helper only runs when the
    caller sets neither source, so handing the booking its line explicitly
    means the refusal never arises rather than being worked around. No
    context escape, no second code path.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FitnessAddStudentWizard(models.TransientModel):
    _name = 'fitness.add.student.wizard'
    _description = 'Add a student to this class'

    # Which product records the credit, per discipline. Named rather than
    # searched: a search would quietly pick up whatever else somebody adds
    # later, and this has to be the single class the studio actually sells.
    PRIVATE_PRODUCT_XMLID = {
        'reformer': 'fitness_packages.product_private_single',
        'barre': 'fitness_packages.product_barre_privada_single',
    }
    # What a given-away class is charged against: zero euros, and a product
    # the shop never shows. Same reasoning as the private map - named, not
    # searched, so it cannot drift onto whatever somebody adds later.
    COURTESY_PRODUCT_XMLID = {
        'reformer': 'fitness_packages.product_courtesy_reformer',
        'barre': 'fitness_packages.product_courtesy_barre',
    }

    event_id = fields.Many2one(
        'calendar.event', string='Class', required=True, readonly=True)
    student_id = fields.Many2one(
        'res.partner', string='Student', required=True,
        help="Any contact. The booking and the paid line are both created "
             "against them.")
    price = fields.Float(
        string='Agreed price', default=0.0,
        help="What the studio agreed with the student. Defaults to the list "
             "price of the private class, and is meant to be changed when the "
             "conversation landed somewhere else.")
    # Not required on the field: required=True puts a NOT NULL constraint on
    # the column, and a constraint cannot know that a courtesy class has no
    # price to give. The form asks for it when the mode charges, and
    # action_add refuses a charged booking without one - both of which can
    # see the mode, where the database cannot.
    product_id = fields.Many2one(
        'product.template', string='Charged as', readonly=True)
    # Asked outright rather than inferred from a price of zero, for the same
    # reason the desk wizard asks: charging nothing by accident and giving a
    # class away on purpose must not look identical on the record.
    mode = fields.Selection(
        [('charge', 'Charge the agreed price'),
         ('courtesy', 'Free class - the studio is giving it')],
        default='charge', required=True, string='This is a')
    reason = fields.Text(
        string='Reason',
        help="Why the class was given. Required for a free class, and the "
             "only record anyone will have of it later.")

    # Shown, not computed at save: the studio should see the room it has
    # before it picks a student, not after being refused.
    seats_label = fields.Char(compute='_compute_seats_label')
    is_private = fields.Boolean(compute='_compute_seats_label')

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

    @api.onchange('mode')
    def _onchange_mode(self):
        """Switching the act switches what it is charged against."""
        for wiz in self:
            if not wiz.event_id:
                continue
            product = wiz._product_for(wiz.event_id, wiz.mode)
            wiz.product_id = product.id if product else False
            wiz.price = (0.0 if wiz.mode == 'courtesy'
                         else (product.list_price or 0.0 if product else 0.0))

    @api.model
    def default_get(self, fields_list):
        """Opened from a class, so the class and its price come with it."""
        res = super().default_get(fields_list)
        event_id = self.env.context.get('default_event_id') \
            or self.env.context.get('active_id')
        if event_id and self.env.context.get('active_model') in (
                'calendar.event', None):
            event = self.env['calendar.event'].browse(event_id)
            if event.exists():
                res['event_id'] = event.id
                # A group class has no product to charge against - the
                # private ones are refused by the booking validator for a
                # group session, and the single-class group packs are
                # archived. So the sensible default there is the act that
                # actually works, rather than one that fails on save.
                is_group = (event.class_type_id.session_type
                            or 'group') == 'group'
                # Assigned, and read from the context rather than from res:
                # the field's own default of 'charge' is already sitting in
                # res by now, so setdefault does nothing and res.get() cannot
                # tell a real request apart from that default. Same trap as
                # the price default three lines down, for the same reason.
                mode = (self.env.context.get('default_mode')
                        or ('courtesy' if is_group else 'charge'))
                res['mode'] = mode
                product = self._product_for(event, mode)
                if product:
                    res['product_id'] = product.id
                    # Assigned, not setdefault: the field carries a default
                    # of 0.0 so the column is never null, and setdefault then
                    # left every charged booking at zero - which the price
                    # guard duly refused.
                    res['price'] = (0.0 if mode == 'courtesy'
                                    else (product.list_price or 0.0))
        return res

    def _product_for(self, event, mode='charge'):
        """The credit product for this class's discipline.

        Two maps, because the two acts are different: a private class agreed
        in conversation is sold, and a courtesy class is given. The courtesy
        product costs nothing and never appears in the shop, so a free
        booking still has a real order behind it without putting a zero-euro
        class in front of students.
        """
        discipline = (event.class_type_id.classroom_type
                      or event.classroom_id.classroom_type or '')
        table = (self.COURTESY_PRODUCT_XMLID if mode == 'courtesy'
                 else self.PRIVATE_PRODUCT_XMLID)
        xmlid = table.get(discipline)
        if not xmlid:
            return self.env['product.template'].browse()
        return self.env.ref(xmlid, raise_if_not_found=False) \
            or self.env['product.template'].browse()

    def action_add(self):
        """Record what was agreed, then book it."""
        self.ensure_one()
        if not self.env.user.has_group('fitness_core.group_fitness_manager') \
                and not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only studio managers can add a student to a class."))

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

        if self.mode == 'charge' and (
                event.class_type_id.session_type or 'group') == 'group':
            raise UserError(_(
                "'%(name)s' is a group class, and there is no group class to "
                "charge a single booking against - the single-class packs are "
                "not on sale. Give the class instead, or sell the student a "
                "pack and let them book it.", name=event.name))
        if self.mode == 'charge' and not (self.price or 0.0) > 0.0:
            raise UserError(_(
                "Enter the price agreed, or switch to a free class."))
        if self.mode == 'courtesy' and not (self.reason or '').strip():
            raise UserError(_(
                "Say why this class is being given. It is the only record "
                "anyone will have of it later."))

        product = self.product_id or self._product_for(event, self.mode)
        if not product:
            raise UserError(_(
                "There is no %(kind)s product for this discipline, so there "
                "is nothing to book the class against.",
                kind=_("courtesy class") if self.mode == 'courtesy'
                else _("private class")))
        variant = product.product_variant_ids[:1]
        if not variant:
            raise UserError(_("%(name)s has no variant to sell.",
                              name=product.display_name))

        discipline = (event.class_type_id.classroom_type
                      or event.classroom_id.classroom_type or '')

        # The agreed price, recorded as a real confirmed sale so the credit
        # exists, the studio can invoice it, and the booking has something to
        # spend. Created as the wizard's own order rather than reusing a
        # draft: this one is already agreed.
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student_id.id,
            'order_line': [(0, 0, {
                'product_id': variant.id,
                'product_uom_qty': 1,
                # A given class is zero whatever is in the box; the studio
                # cannot accidentally charge for something it is donating.
                'price_unit': 0.0 if self.mode == 'courtesy' else self.price,
                'fitness_class_type': discipline,
            })],
        })
        order.action_confirm()
        line = order.order_line[:1]

        # Explicit source, so _select_payment_source never runs: it is the
        # helper that would refuse a student with no private credit, and the
        # credit it would have looked for is the one just created.
        booking = self.env['fitness.booking'].create({
            'student_id': self.student_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': line.id,
            # A private class is agreed weeks ahead as a matter of course, so
            # the seven-day window has to give. Through the flag the model
            # already re-checks, not around it.
            'manager_override_timewindow': True,
        })

        if (self.reason or '').strip():
            order.message_post(body=_(
                "Added to %(name)s by %(who)s. %(kind)s.<br/>Reason: %(why)s",
                name=event.name, who=self.env.user.name,
                kind=_("Free class, nothing charged")
                if self.mode == 'courtesy' else _("Charged the agreed price"),
                why=self.reason.strip()))

        _logger.info(
            "[ADD STUDENT] %s booked onto %s (%s) by %s, %s, order %s",
            self.student_id.display_name, event.name, event.start,
            self.env.user.login,
            'COURTESY (0.00)' if self.mode == 'courtesy'
            else 'charged %.2f' % (self.price or 0.0), order.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Student added"),
                'message': _(
                    "%(student)s is booked on %(name)s, charged %(price)s on "
                    "%(order)s.",
                    student=self.student_id.display_name, name=event.name,
                    price=self.price, order=order.name),
                'type': 'success',
                'sticky': False,
                # The roster behind the dialog is stale the moment this
                # returns; without a reload the studio adds the same student
                # twice because the list still shows them missing.
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
