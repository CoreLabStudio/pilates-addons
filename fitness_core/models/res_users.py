# -*- coding: utf-8 -*-
"""Weekly teaching load, read off the recurring schedule.

The studio needs to know how many hours a week each instructor is carrying.
That number is already implicit in fitness.class.schedule - a schedule is one
class on one weekday at one time, with a duration - so it is derived here
rather than typed in anywhere. Nothing to keep in step, and nothing to
recalculate when the schedule changes.

Deliberately not stored. A stored total would have to be invalidated whenever
a schedule is added, moved, retimed, archived or reassigned, and the one that
gets missed is the one that goes quietly wrong. Computing on read costs a
single search per instructor on a table with tens of rows.

Archived schedules are excluded, which is what makes "remove Saturday" show up
here immediately: archiving those schedules drops the hours without anyone
touching a number.
"""
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    fitness_schedule_ids = fields.One2many(
        'fitness.class.schedule', 'teacher_user_id',
        string="Recurring Classes",
        help="The fixed weekly slots this instructor is assigned to.",
    )
    fitness_weekly_hours = fields.Float(
        "Weekly Hours",
        compute='_compute_fitness_weekly_load',
        digits=(6, 2),
        help="Total hours a week from the recurring schedule. Calculated from "
             "the assigned classes, never entered by hand.",
    )
    fitness_weekly_class_count = fields.Integer(
        "Weekly Classes",
        compute='_compute_fitness_weekly_load',
        help="How many recurring classes a week this instructor is assigned.",
    )
    fitness_weekly_days = fields.Char(
        "Teaching Days",
        compute='_compute_fitness_weekly_load',
        help="Which weekdays the instructor is scheduled on.",
    )

    fitness_is_teacher = fields.Boolean(
        "Is an Instructor",
        compute='_compute_fitness_is_teacher',
        search='_search_fitness_is_teacher',
        help="Whether this user is in the instructor group.",
    )

    def _compute_fitness_is_teacher(self):
        group = self.env.ref('fitness_core.group_fitness_teacher',
                             raise_if_not_found=False)
        for user in self:
            user.fitness_is_teacher = bool(group) and group in user.group_ids

    def _search_fitness_is_teacher(self, operator, value):
        """Filter instructors without putting a group id in a domain.

        The Weekly Hours action needs "instructors only", and the obvious way
        to write that - ref() in the action's own domain - fails: a window
        action's domain is a string the browser evaluates, and ref() exists
        only on the server, so the menu raised "Name 'ref' is not defined" the
        moment it was clicked. Nor does %(xmlid)d help; the loader substitutes
        that in xml and html fields, not in a plain char one, so it reached the
        database still written out as %(...)d.

        Resolving the group here instead keeps the lookup on the server, where
        ref() works, and leaves the action holding a plain literal domain the
        browser can evaluate. It also stores no group id anywhere, so this
        survives the module being installed on a fresh database with different
        ids - which is exactly what odoo.sh does on every build.
        """
        # Odoo 19 rewrites ('field', '=', True) into ('field', 'in', [True])
        # before it gets here, so handling only = and != raised "Unsupported
        # operator in" on the very domain this exists to serve. Reduce whatever
        # comes in to which truth values are being asked for.
        if operator in ('=', '!='):
            accepted = {bool(value) if operator == '=' else not bool(value)}
        elif operator in ('in', 'not in'):
            given = {bool(v) for v in
                     (value if isinstance(value, (list, tuple, set)) else [value])}
            accepted = given if operator == 'in' else {True, False} - given
        else:
            raise ValueError("Unsupported operator %s" % operator)

        if accepted == {True, False}:
            return []                       # matches everyone
        if not accepted:
            return [('id', '=', False)]     # matches no one

        group = self.env.ref('fitness_core.group_fitness_teacher',
                             raise_if_not_found=False)
        if not group:
            # No group means nobody is an instructor, rather than an error on a
            # database where this module's data has not loaded yet.
            return [('id', '=', False)] if True in accepted else []
        return [('group_ids', 'in' if True in accepted else 'not in', group.ids)]

    @api.depends('fitness_schedule_ids',
                 'fitness_schedule_ids.duration',
                 'fitness_schedule_ids.weekday',
                 'fitness_schedule_ids.active')
    def _compute_fitness_weekly_load(self):
        # one weekday order for everyone, so two instructors' days read the
        # same way round rather than in whatever order their records happen to
        # come back in
        order = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        labels = dict(
            self.env['fitness.class.schedule']._fields['weekday'].selection)

        for user in self:
            # Filter explicitly rather than trusting the one2many to drop
            # archived rows. It normally does, but active_test travels with the
            # context: read this field from a view that sets active_test=False
            # and the archived Saturday slots come back too, quietly inflating
            # everyone by four hours a week. Measured that happening.
            scheds = user.fitness_schedule_ids.filtered(lambda s: s.active)
            user.fitness_weekly_hours = sum(scheds.mapped('duration'))
            user.fitness_weekly_class_count = len(scheds)
            days = {s.weekday for s in scheds}
            user.fitness_weekly_days = ', '.join(
                labels.get(d, d) for d in order if d in days)
