# -*- coding: utf-8 -*-
"""What a timetable edit does to the members standing on that slot.

A Clase Fija member is attached to the recurring *series*, not to a day and a
time: the slot holds one anchor event and placement books every occurrence of
its recurrence. So she follows this row wherever it goes, and two perfectly
ordinary admin actions land on her without saying so.

  * Change the class type, day or time and her class changes under her from
    the next generated week onward. Nothing propagates to classes already
    generated, so her weeks stop matching each other.
  * Close the row and her slot points at a retired series. Her existing
    bookings survive, but her next renewal places nothing and fails with
    "no occurrences found - add to schedule then re-confirm".

Neither was visible from the schedule form. This does not stop either - the
studio is allowed to change its own timetable - it makes the consequence
arrive with the action instead of three weeks later as a support message.

Lives here rather than in fitness_core because fitness.clase.fija is defined
in this module, and fitness_core must keep installing without it.
"""
from odoo import _, api, fields, models


class FitnessClassSchedule(models.Model):
    _inherit = 'fitness.class.schedule'

    # Not stored: it is a question about live subscriptions, and a stored
    # answer would go stale the moment one of them ended.
    fixed_slot_ids = fields.Many2many(
        'fitness.clase.fija', string="Members On This Slot",
        compute='_compute_fixed_slots',
        help="Members whose fixed weekly class is this slot. Editing or "
             "closing this row changes or breaks their class.")
    fixed_slot_count = fields.Integer(compute='_compute_fixed_slots')
    fixed_slot_names = fields.Char(compute='_compute_fixed_slots')

    @api.depends('recurrence_id')
    def _compute_fixed_slots(self):
        """The members whose weekly class is this row.

        Matched through recurrence_id because that is what placement follows.
        Only subscriptions actually running count: a finished one is not
        somebody an edit can still hurt.

        sudo() is narrow and deliberate. A studio admin may hold no rights on
        sale.order, and the entire point is that she sees who she is about to
        affect before she affects them.
        """
        Slot = self.env['fitness.clase.fija'].sudo()
        for rec in self:
            slots = Slot.browse()
            if rec.recurrence_id:
                slots = Slot.search([
                    ('active', '=', True),
                    ('calendar_event_id.recurrence_id', '=', rec.recurrence_id.id),
                    ('subscription_id.subscription_state', '=', '3_progress'),
                ])
            rec.fixed_slot_ids = slots
            rec.fixed_slot_count = len(slots)
            rec.fixed_slot_names = ', '.join(
                slots.mapped('subscription_id.partner_id.name')) or ''

    def _fixed_slot_sentence(self, consequence):
        """Who this lands on, and what it does to them.

        One builder, so the warning shown while editing and the note shown
        after closing cannot drift into describing the same consequence
        differently.
        """
        self.ensure_one()
        if not self.fixed_slot_count:
            return ''
        return _(
            "%(count)s member(s) have this slot as their fixed weekly class: "
            "%(names)s.\n\n%(consequence)s\n\n"
            "Classes they are already booked into are not changed. Tell them, "
            "or give them a new slot on their subscription."
        ) % {
            'count': self.fixed_slot_count,
            'names': self.fixed_slot_names,
            'consequence': consequence,
        }

    def _fixed_slot_note(self):
        """Filled-in answer to the hook fitness_core leaves for this module."""
        notes = []
        for rec in self:
            if not rec.fixed_slot_count:
                continue
            notes.append(_(
                "%(slot)s - %(names)s now have no fixed class. Their existing "
                "bookings are untouched, but nothing new will be placed until "
                "they are given another slot."
            ) % {'slot': rec.name, 'names': rec.fixed_slot_names})
        return "\n".join(notes)

    @api.onchange('class_type_id', 'weekday', 'start_time', 'duration',
                  'classroom_id', 'date_end')
    def _onchange_warn_fixed_slot_members(self):
        """Name the members before the change is saved.

        Deliberately a warning rather than a block. The studio is allowed to
        move its own classes; what it should not be able to do is move
        somebody's fixed class without being told whose.

        Read from _origin, the unmodified record: the edit in front of her has
        not been saved, and the question is who is standing on the row as it
        exists now. A row still being created has nobody on it.
        """
        self.ensure_one()
        if not self._origin.id:
            return
        message = self._origin._fixed_slot_sentence(_(
            "Changing this slot moves the class they are booked into from now "
            "on. Classes already generated keep the old details, so their "
            "weeks will not all match."))
        if message:
            return {'warning': {
                'title': _("Members have this as their fixed class"),
                'message': message,
            }}
