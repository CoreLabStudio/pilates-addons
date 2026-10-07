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

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'


class FitnessDuplicateCandidate(models.Model):
    _name = 'fitness.duplicate.candidate'
    _description = 'Possible duplicate contacts'
    _order = 'has_history desc, partner_count desc, email'
    _rec_name = 'email'

    email = fields.Char("Shared address", required=True, index=True)
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

        groups = {}
        for partner in Partner.search([
                ('email_normalized', '!=', False),
                ('is_company', '=', False)]):
            groups.setdefault(partner.email_normalized, self.env['res.partner'])
            groups[partner.email_normalized] |= partner

        # Keep whatever a manager has already ticked off, so a nightly
        # rebuild does not reopen yesterday's decisions.
        settled = {
            r.email for r in self.sudo().search([('resolved', '=', True)])}

        self.sudo().search([('resolved', '=', False)]).unlink()

        rows = []
        for email, partners in groups.items():
            if len(partners) < 2 or email in settled:
                continue
            with_login = partners.filtered(
                lambda p: Users.search_count([('partner_id', '=', p.id)]))
            no_login = partners - with_login

            # The one shape the automatic join handles on its own. It is
            # only listed here when it was refused, and the reason it was
            # refused is the useful part.
            if len(partners) == 2 and len(no_login) == 1 and len(with_login) == 1:
                if with_login._fitness_names_compatible(no_login):
                    # Joinable automatically; it will go at her next
                    # verification. Nothing for a manager to do.
                    continue
                reason = ("the names do not match - check these are not two "
                          "different people sharing an address")
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
                'partner_ids': [(6, 0, partners.ids)],
                'partner_count': len(partners),
                'login_count': len(with_login),
                'reason': reason,
                'has_history': bool(bookings or orders),
                'booking_count': bookings,
                'order_count': orders,
            })

        created = self.sudo().create(rows) if rows else self.browse()
        _logger.info("[DUPLICATE] scan found %d group(s) needing a person",
                     len(created))
        return created

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
                tr("%(count)s possible duplicate contacts",
                   count=len(open_rows)),
                tr("%(carrying)s of them hold bookings or paid orders, so "
                   "somebody may be signing in and not seeing her own "
                   "history.", carrying=len(carrying)),
                '/odoo/action-fitness_portal.action_fitness_duplicate_candidate',
            )
