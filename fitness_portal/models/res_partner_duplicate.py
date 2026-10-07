# -*- coding: utf-8 -*-
"""One person, one contact - decided at the only moment it is safe to.

THE FAULT

The studio makes a contact at the desk when somebody first comes in:
name, email, phone, and from then on her bookings, her credits and her
payments hang off it. Later she signs up on the app herself, and Odoo
makes her a SECOND contact, because nothing was looking. She signs in
and the account is empty: no history, no credits, and the free trial on
offer again, because the contact that spent it is the other one.

Three of those were merged by hand before this existed - Olga Sganzerla,
Aran, Ariadna - each one a script run against production.

WHY VERIFICATION IS THE ONLY SAFE MOMENT

Joining on a matching email alone is dangerous, and the studio's own
duplicate report already says why: a shared address is ordinary in a
family. If a mother is a contact under her address and her daughter
signs up with the same one, joining on email fuses two real people, and
the bookings, credits and history of both go with them. There is no undo.

At verification she has PROVED she controls that address - she followed
a single-use link sent to it. That is the strongest statement this
system ever gets about an address, and it is still not enough on its
own, so three more clauses narrow it:

  * the other contact must have NO login of its own. That is the shape
    this exists for: the desk made it. Two contacts that both have
    logins are two accounts, which is a manager's decision and not a
    redirect's.
  * there must be exactly ONE such contact. Any ambiguity goes to a
    human; guessing between two is how the wrong history gets attached.
  * the names must be compatible. This is the clause that keeps mother
    and daughter apart, and it is why the probe reports how many pairs
    it blocks - that number must be read before this is switched on.

OFF BY DEFAULT. fitness.signup_autojoin_enabled must be set to '1'.

The rule's safety depends on the real distribution of duplicates, and
that cannot be read off a local copy: the restore holds two duplicate
addresses and both are the developer's own test accounts. Run
scripts/duplicate_signup_probe.py against production first and read
"BLOCKED by the name check" - it must be zero, or there are pairs this
would have joined wrongly.
"""
import logging
import unicodedata

from odoo import models

_logger = logging.getLogger(__name__)

AUTOJOIN_PARAM = 'fitness.signup_autojoin_enabled'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # -- name comparison ------------------------------------------------
    def _fitness_name_words(self):
        """The name as a comparable set of words.

        Lowercased, accents stripped and punctuation dropped, because
        "Marta Munoz" from a signup form and the accented spelling at
        the desk are the same student. Single letters are dropped: an
        initial carries no evidence either way.
        """
        self.ensure_one()
        flat = unicodedata.normalize('NFKD', self.name or '')
        flat = ''.join(c for c in flat if not unicodedata.combining(c)).lower()
        cleaned = ''.join(c if c.isalnum() else ' ' for c in flat)
        return {w for w in cleaned.split() if len(w) > 1}

    def _fitness_names_compatible(self, other):
        """Whether two contacts can be the same person, by name alone.

        Equal word sets, or one contained in the other: a student
        recorded once with both surnames and once with one is the same
        student.

        Disjoint sets are two different people and must never be joined.
        An empty name on either side answers False - a contact with no
        name is not evidence of anything, and silence is not consent.
        """
        self.ensure_one()
        mine = self._fitness_name_words()
        theirs = other._fitness_name_words()
        if not mine or not theirs:
            return False
        return mine == theirs or mine <= theirs or theirs <= mine

    # -- finding the one safe target ------------------------------------
    def _fitness_same_email_contacts(self):
        """Every OTHER contact sharing this one's normalised email.

        active_test=False on purpose: an archived contact is still a
        duplicate and still holds the history. Leaving it out was a real
        bug in the first version of the probe, where it turned the two
        duplicate addresses on the local copy into "no duplicates".
        """
        self.ensure_one()
        if not self.email_normalized:
            return self.browse()
        return self.sudo().with_context(active_test=False).search([
            ('email_normalized', '=', self.email_normalized),
            ('id', '!=', self.id),
            ('is_company', '=', False),
            ('company_id', 'in', (False, self.company_id.id)),
        ])

    def _fitness_has_login(self):
        self.ensure_one()
        return bool(self.env['res.users'].sudo().with_context(
            active_test=False).search_count([('partner_id', '=', self.id)]))

    def _fitness_autojoin_target(self):
        """The one contact this may be joined into, or an empty set.

        Every refusal is logged with its reason. A join that silently
        does not happen is indistinguishable from one that was never
        attempted, and the studio would be left wondering why a student
        still signs in to an empty account.
        """
        self.ensure_one()
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            AUTOJOIN_PARAM)
        if str(enabled).strip() not in ('1', 'True', 'true'):
            return self.browse()
        if self.is_company or not self.email_normalized:
            return self.browse()

        others = self._fitness_same_email_contacts()
        if not others:
            return self.browse()

        joinable = others.filtered(lambda p: not p._fitness_has_login())
        if len(joinable) != 1:
            _logger.info(
                "[DUPLICATE] not joining %s (%s): %d contacts share the "
                "address, %d of them without a login - a human decides",
                self.display_name, self.email_normalized, len(others),
                len(joinable))
            return self.browse()

        target = joinable
        if not self._fitness_names_compatible(target):
            _logger.warning(
                "[DUPLICATE] NOT joining %s into %s: same address (%s) but "
                "the names do not match. This is the case the rule exists "
                "to refuse - two people on one address.",
                self.display_name, target.display_name, self.email_normalized)
            return self.browse()
        return target

    # -- the join -------------------------------------------------------
    def _fitness_join_into(self, survivor):
        """Merge this contact into the survivor, using Odoo's own wizard.

        base.partner.merge.automatic.wizard._merge moves every foreign
        key and every reference field, including the ones nobody
        remembered. A hand-written list of tables to repoint is a list
        that is wrong the first time somebody adds one.

        res.users.partner_id is one of those foreign keys, so the login
        is never touched: same login, same password, same session - it
        simply points at the surviving contact afterwards.
        """
        self.ensure_one()
        survivor.ensure_one()
        _logger.warning(
            "[DUPLICATE] joining contact %s (id=%s) into %s (id=%s) on "
            "verified address %s",
            self.display_name, self.id, survivor.display_name, survivor.id,
            self.email_normalized)

        # Written BEFORE the merge, because afterwards there is nothing
        # left to read: _merge deletes this contact, and its name and id
        # go with it. See fitness_duplicate_join_log.py for why a log
        # line was not enough.
        Booking = self.env['fitness.booking'].sudo()
        Order = self.env['sale.order'].sudo()
        self.env['fitness.duplicate.join.log'].sudo().create({
            'email': self.email_normalized or '',
            'survivor_id': survivor.id,
            'survivor_name': survivor.name or '',
            'merged_name': self.name or '',
            'merged_ref': self.id,
            'bookings_moved': Booking.search_count(
                [('student_id', '=', self.id)]),
            'orders_moved': Order.search_count(
                [('partner_id', '=', self.id),
                 ('state', 'in', ('sale', 'done'))]),
            'user_login': ', '.join(self.env['res.users'].sudo().with_context(
                active_test=False).search(
                    [('partner_id', '=', survivor.id)]).mapped('login')),
        })

        self.env['base.partner.merge.automatic.wizard'].sudo()._merge(
            (survivor | self).ids, dst_partner=survivor)
        return survivor
