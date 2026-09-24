import pytz

from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging

# The studio is in Spain and calendar.event.start is stored in UTC. A slot
# reserved for 18:00 in Matadepera is 16:00 UTC in summer, so the label has to
# convert or it names an hour the class does not run at - and it is read at
# exactly the moment somebody is checking the slot is the right one.
#
# Always this clock, never the reader's. This used to fall back to the context
# timezone first, which is the timezone of whoever happened to write the
# record: a member picking her own slot in the portal stamped the label in
# *her* account's timezone. Most accounts here carry no timezone at all and a
# large minority carry Asia/Calcutta, set by whoever created them - so an
# 18:00 class was being labelled "21:30", three and a half hours out, on a
# stored field that then showed that hour to everybody who read it afterwards.
# The portal's _user_tz() answers the studio clock for everybody for exactly
# this reason; this is the same rule for the same reason.
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
                local = pytz.utc.localize(ev.start).astimezone(
                    pytz.timezone(STUDIO_TZ))
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
            # Counted per discipline, not in total.
            #
            # A combined plan - "1 Barre + 1 Reformer per week" - carries the
            # Barre number in weekly_class_allowance and names Reformer as the
            # secondary discipline. Comparing every slot against that single
            # number made one Barre slot plus one Reformer slot look like two
            # against an allowance of one, so a member on a combined plan
            # could not have her two fixed classes at all - the exact thing
            # she bought. fitness_effective_weekly_allowance already answers
            # per discipline; this now asks it that way.
            by_discipline = {}
            for other in sub.fitness_clase_fija_ids.filtered('active'):
                ev = other.calendar_event_id
                room = (ev.class_type_id.classroom_type
                        or ev.class_type_id.fitness_class_type
                        or '') if ev.class_type_id else ''
                by_discipline.setdefault(room, 0)
                by_discipline[room] += 1

            for room, count in by_discipline.items():
                eff = sub.fitness_effective_weekly_allowance(discipline=room)
                if eff <= 0:
                    continue
                if count > eff:
                    raise ValidationError(
                        f"Cannot activate this slot: {sub.name} would have "
                        f"{count} active {room or 'class'} slot(s), but the "
                        f"weekly allowance for {room or 'that discipline'} is "
                        f"{eff}. Deactivate one first, or increase the "
                        "member's Weekly Allowance Override."
                    )
