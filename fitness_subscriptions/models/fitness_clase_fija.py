import pytz

from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging

# The studio is in Spain and calendar.event.start is stored in UTC. A slot
# reserved for 18:00 in Matadepera is 16:00 UTC in summer, so the label has to
# convert or it names an hour the class does not run at - and it is read at
# exactly the moment somebody is checking the slot is the right one.
STUDIO_TZ = 'Europe/Madrid'
_logger = logging.getLogger(__name__)


class FitnessClaseFija(models.Model):
    _name = 'fitness.clase.fija'
    _description = 'Clase Fija — Fixed Weekly Class Slot'
    _order = 'subscription_id, sequence'

    subscription_id = fields.Many2one(
        'sale.order', "Subscription",
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer("Sequence", default=10)
    calendar_event_id = fields.Many2one(
        'calendar.event', "Anchor Class Event",
        required=True,
        domain=[('is_fitness_class', '=', True)],
        help="Any occurrence of the recurring class slot reserved for this member. "
             "Auto-placement finds all occurrences in the billing period via "
             "recurrence_id (if part of a series) or this exact event if not recurring.",
    )
    active = fields.Boolean("Active", default=True)
    name = fields.Char("Label", compute='_compute_name', store=True)

    @api.depends('calendar_event_id', 'calendar_event_id.start', 'calendar_event_id.name')
    def _compute_name(self):
        for rec in self:
            ev = rec.calendar_event_id
            if ev and ev.start:
                tz = pytz.timezone(self.env.context.get('tz') or STUDIO_TZ)
                local = pytz.utc.localize(ev.start).astimezone(tz)
                rec.name = f"{ev.name} ({local.strftime('%a %H:%M')})"
            elif ev:
                rec.name = ev.name or "Unset"
            else:
                rec.name = "Unset"

    # ── B1 guard: active slot count must not exceed effective weekly allowance ──

    @api.constrains('active', 'subscription_id', 'calendar_event_id')
    def _check_slot_count_vs_allowance(self):
        for slot in self:
            if not slot.active:
                continue
            sub = slot.subscription_id
            if not sub:
                continue
            if sub.fitness_is_unlimited:
                continue
            eff = sub.fitness_effective_weekly_allowance()
            if eff <= 0:
                continue
            active_count = len(sub.fitness_clase_fija_ids.filtered('active'))
            if active_count > eff:
                raise ValidationError(
                    f"Cannot activate this slot: {sub.name} would have "
                    f"{active_count} active fixed slot(s), but the effective "
                    f"weekly allowance is {eff}. "
                    "Deactivate an existing slot first, or increase the member's "
                    "Weekly Allowance Override."
                )
