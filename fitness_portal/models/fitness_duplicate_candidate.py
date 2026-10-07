# -*- coding: utf-8 -*-
"""The duplicates a human has to look at, and a note each morning.

The automatic join at verification deliberately refuses most of what it
sees: two contacts that both have logins, three contacts on one address,
names that do not match. Those refusals are the right answer, but on
their own they are silent - the student still signs in to an empty
account and nobody at the studio knows there is anything to do.

So every refusal lands here instead, where a manager can see it. This
list is the other half of the rule: the automatic join handles the one
unambiguous shape, and everything else becomes work somebody has chosen
to do rather than something the system did quietly.

Rebuilt by a daily cron rather than maintained live. A duplicate is not
urgent - it is a tidying job with a student attached - and recomputing
the whole picture once a day cannot drift out of step with the data the
way an incrementally maintained flag does.
"""
import logging

from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError

from odoo.addons.fitness_subscriptions.models.sale_order import (
    ACTIVE_SUBSCRIPTION_STATE,
)

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'


class FitnessDuplicateCandidate(models.Model):
    _name = 'fitness.duplicate.candidate'
    _description = 'Possible duplicate contacts'
    _order = 'has_history desc, partner_count desc, email'
    _rec_name = 'email'

    email = fields.Char("Shared address or number", required=True, index=True)
    matched_on = fields.Selection(
        [('email', 'Email'), ('phone', 'Phone')],
        default='email', required=True, string="Matched on",
        help="Phone matches are the ones an email search cannot find: "
             "the same student with a work address on one contact and a "
             "personal one on the other.")
    partner_ids = fields.Many2many('res.partner', string="Contacts")
    partner_count = fields.Integer("Contacts", default=0)
    login_count = fields.Integer("With a login", default=0)
    reason = fields.Char(
        "Why it needs a person",
        help="What stopped this being joined automatically at verification.")
    has_history = fields.Boolean(
        "Carries history",
        help="At least one of these contacts has bookings or confirmed "
             "orders, so somebody is signing in and not seeing them.")
    booking_count = fields.Integer("Bookings", default=0)
    order_count = fields.Integer("Confirmed orders", default=0)
    resolved = fields.Boolean("Dealt with", default=False)
    checked = fields.Boolean(
        "I have checked these are the same person",
        help="Merge will not run until this is ticked. The tick is the "
             "record that a person looked, which is the only thing "
             "standing between a shared family address and two people "
             "being fused into one.")

    # -- building the list ---------------------------------------------
    @api.model
    def _scan(self):
        """Recompute the whole list. Returns the open records.

        active_test=False throughout: an archived contact is still a
        duplicate and still holds the history. Leaving archived records
        out is what made the first version of the production probe
        report a clean database that had duplicates in it.
        """
        Partner = self.env['res.partner'].sudo().with_context(
            active_test=False)
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        Booking = self.env['fitness.booking'].sudo()
        Order = self.env['sale.order'].sudo()

        everyone = Partner.search([('is_company', '=', False)])

        groups = {}
        for partner in everyone:
            if not partner.email_normalized:
                continue
            groups.setdefault(partner.email_normalized, self.env['res.partner'])
            groups[partner.email_normalized] |= partner

        # Phone as well, because a student with a work address on one
        # contact and a personal one on the other shares NO email, and an
        # email-only search cannot see her at all. Those pairs are never
        # joined automatically - a number is not proof of anything the
        # way a verified address is - but a manager should be told they
        # exist.
        by_phone = {}
        for partner in everyone:
            for digits in partner._fitness_phone_digits():
                by_phone.setdefault(digits, self.env['res.partner'])
                by_phone[digits] |= partner

        # Keep whatever a manager has already ticked off, so a nightly
        # rebuild does not reopen yesterday's decisions.
        settled = {
            r.email for r in self.sudo().search([('resolved', '=', True)])}

        autojoin_on = str(self.env['ir.config_parameter'].sudo().get_param(
            'fitness.signup_autojoin_enabled')).strip() in ('1', 'True', 'true')

        self.sudo().search([('resolved', '=', False)]).unlink()

        rows = []
        for email, partners in groups.items():
            if len(partners) < 2 or email in settled:
                continue
            with_login = partners.filtered(
                lambda p: Users.search_count([('partner_id', '=', p.id)]))
            no_login = partners - with_login

            # Asked of the rule itself rather than restated here. The
            # list and the join have to agree about what is joinable; two
            # copies of the clauses would drift the first time one of
            # them changed, and the list would start showing pairs the
            # system had already merged.
            if len(with_login) == 1:
                refusal = with_login._fitness_autojoin_refusal()
                if not refusal:
                    # Joinable in principle. It is left OFF the list only
                    # when a future verification could actually join it:
                    # the switch is on AND her account has not verified
                    # yet. An account that has already verified will
                    # never pass through that door again, so leaving its
                    # pair off would hide it for ever - which is the
                    # shape most of the studio's real duplicates are in.
                    if autojoin_on and with_login._fitness_awaits_verification():
                        continue
                    reason = ("clear match - %s. Nothing is stopping these "
                              "being one contact; press Merge when you have "
                              "checked."
                              % ("her account has already verified, so the "
                                 "automatic join will never see it again"
                                 if not with_login._fitness_awaits_verification()
                                 else "the automatic join is switched off"))
                else:
                    reason = refusal
            elif len(with_login) >= 2:
                reason = ("two accounts on one address - merging would take "
                          "somebody's login with it, so a person must decide")
            elif len(no_login) == len(partners):
                reason = ("no login on any of them - tidying, not a student "
                          "locked out of her own history")
            else:
                reason = "more than one possible match - a person must choose"

            bookings = sum(
                Booking.search_count([('student_id', '=', p.id)])
                for p in partners)
            orders = sum(
                Order.search_count([('partner_id', '=', p.id),
                                    ('state', 'in', ('sale', 'done'))])
                for p in partners)
            rows.append({
                'email': email,
                'matched_on': 'email',
                'partner_ids': [(6, 0, partners.ids)],
                'partner_count': len(partners),
                'login_count': len(with_login),
                'reason': reason,
                'has_history': bool(bookings or orders),
                'booking_count': bookings,
                'order_count': orders,
            })

        # Phone-only pairs: same number, no shared address, so the
        # email pass above has not already covered them.
        seen = {tuple(sorted(r['partner_ids'][0][2])) for r in rows}
        for digits, partners in by_phone.items():
            if len(partners) < 2:
                continue
            key = tuple(sorted(partners.ids))
            if key in seen:
                continue
            addresses = {p.email_normalized for p in partners if p.email_normalized}
            if len(addresses) < 2:
                continue
            label = 'phone ...%s' % digits[-4:]
            if label in settled:
                continue
            bookings = sum(
                Booking.search_count([('student_id', '=', p.id)])
                for p in partners)
            orders = sum(
                Order.search_count([('partner_id', '=', p.id),
                                    ('state', 'in', ('sale', 'done'))])
                for p in partners)
            rows.append({
                'email': label,
                'matched_on': 'phone',
                'partner_ids': [(6, 0, partners.ids)],
                'partner_count': len(partners),
                'login_count': len(partners.filtered(
                    lambda p: Users.search_count([('partner_id', '=', p.id)]))),
                'reason': ("same phone number, different email addresses - "
                           "never joined automatically, because a number is "
                           "not proof of anything the way a verified address "
                           "is"),
                'has_history': bool(bookings or orders),
                'booking_count': bookings,
                'order_count': orders,
            })
            seen.add(key)

        created = self.sudo().create(rows) if rows else self.browse()
        _logger.info("[DUPLICATE] scan found %d group(s) needing a person",
                     len(created))
        return created

    # -- the manager's merge --------------------------------------------
    def action_merge(self):
        """Merge this pair, because a person has looked at it and said so.

        Deliberately NOT governed by fitness.signup_autojoin_enabled.
        That switch exists to stop the system acting on its own; it has
        no business stopping a manager who has both records in front of
        her. The tick below is this path's safety, and it is a stronger
        one - it is a human assertion rather than a rule.
        """
        self.ensure_one()
        # Explicit, because this is reachable over RPC by anybody who can
        # guess the model name. Relying on the access rules alone would
        # mean a portal account could call it the moment somebody adds a
        # read right for the list.
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(self.env._(
                "Only a studio manager can merge contacts."))

        if not self.checked:
            raise UserError(self.env._(
                "Tick \"I have checked these are the same person\" first. "
                "Merging cannot be undone, and a shared address is "
                "ordinary in a family."))

        partners = self.partner_ids.sudo().with_context(active_test=False)
        if len(partners) != 2:
            raise UserError(self.env._(
                "Merge handles two contacts at a time; this row has "
                "%(count)s. Sort it out from the contacts screen.",
                count=len(partners)))

        first, second = partners[0], partners[1]
        if first._fitness_is_staff() or second._fitness_is_staff():
            raise UserError(self.env._(
                "One of these is a staff account. Merging it would move "
                "its access as well, so it is not done from here."))

        # Two logins is two accounts. Merging them moves one user's
        # partner_id onto the other's contact, leaving two logins
        # pointing at one person and no way to tell afterwards which
        # history belonged to whom. The list already says a person must
        # decide; deciding means closing one account first, not pressing
        # Merge.
        if first._fitness_has_login() and second._fitness_has_login():
            raise UserError(self.env._(
                "Both of these contacts have their own login (%(a)s, "
                "%(b)s). Merging would leave two accounts pointing at one "
                "contact. Close or archive one account first, then merge.",
                a=', '.join(first._fitness_users().mapped('login')),
                b=', '.join(second._fitness_users().mapped('login'))))

        clash = self._fitness_booking_clash(first, second)
        if clash:
            raise UserError(self.env._(
                "Both contacts hold a booking in the same class (%(name)s). "
                "Merging would put one student in that class twice and the "
                "seat count would be wrong. Cancel one booking first.",
                name=clash))

        if (self._fitness_active_memberships(first)
                and self._fitness_active_memberships(second)):
            raise UserError(self.env._(
                "Both contacts have a running membership. Merging would "
                "leave one person paying twice, with two billing dates. "
                "End one of them first."))

        survivor = first._fitness_pick_survivor(second)
        doomed = (partners - survivor)
        log = doomed._fitness_join_into(survivor)
        self.env['fitness.duplicate.join.log'].sudo().search(
            [('merged_ref', '=', doomed.id)], limit=1).write({
                'was_automatic': False,
                'merged_by_id': self.env.user.id,
            })
        self.resolved = True
        _logger.warning("[DUPLICATE] %s merged %s by hand",
                        self.env.user.login, self.email)
        return log

    @staticmethod
    def _fitness_booking_clash(first, second):
        """A class both contacts hold a live booking in, or None.

        Merging those would leave one student booked twice into one
        class. booked_seats is a plain integer the booking engine
        maintains, so the seat count goes wrong and the roster shows a
        person twice - which is exactly the shape of the bug that made
        deleting a booking corrupt the counts.
        """
        Booking = first.env['fitness.booking'].sudo()
        live = ('booked', 'attended')
        mine = Booking.search([('student_id', '=', first.id),
                               ('state', 'in', live)])
        theirs = Booking.search([('student_id', '=', second.id),
                                 ('state', 'in', live)])
        shared = set(mine.mapped('calendar_event_id').ids) & set(
            theirs.mapped('calendar_event_id').ids)
        if not shared:
            return None
        event = first.env['calendar.event'].sudo().browse(sorted(shared)[0])
        return event.name or str(event.id)

    @staticmethod
    def _fitness_active_memberships(partner):
        """Running subscriptions on this contact."""
        return partner.env['sale.order'].sudo().search_count([
            ('partner_id', '=', partner.id),
            ('subscription_state', '=', ACTIVE_SUBSCRIPTION_STATE),
        ])

    # -- the morning note ----------------------------------------------
    @api.model
    def _cron_scan_and_notify(self):
        """Rebuild the list and tell the managers, once, if it is not empty.

        One notification for the whole list rather than one per pair. A
        bell that fires eleven times for eleven duplicates is a bell
        nobody reads, and this is the least urgent thing the studio is
        told all day.
        """
        open_rows = self._scan()
        if not open_rows:
            return
        carrying = open_rows.filtered('has_history')
        managers = self.env['res.users'].sudo().search(
            [('group_ids', 'in', self.env.ref(MANAGER_GROUP).id)])
        if not managers:
            return
        Notification = self.env['fitness.notification'].sudo()
        for manager in managers:
            tr = self.env(context=dict(
                self.env.context, lang=manager.lang or 'es_ES'))._
            Notification._create_for_user(
                manager.id,
                'duplicate_contacts',
                # PAIRS, not contacts. len(open_rows) is one row per
                # shared address or number - two or more contacts each.
                # Calling them contacts made the number read as people
                # and disagreed with the list beside it.
                tr("%(count)s possible duplicates to check",
                   count=len(open_rows)),
                tr("%(carrying)s of them hold bookings or paid orders, so "
                   "somebody may be signing in and not seeing her own "
                   "history.", carrying=len(carrying)),
                '/odoo/action-fitness_portal.action_fitness_duplicate_candidate',
            )
