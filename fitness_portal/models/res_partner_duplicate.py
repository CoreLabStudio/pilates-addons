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
a single-use link sent to it. That is still not enough on its own, so
every clause below has to agree as well.

WHAT IT REFUSES

  * a contact that has a login of its own. Two logins are two accounts,
    which is a manager's decision and not a redirect's.
  * more than one candidate. Guessing between two is how the wrong
    history gets attached.
  * names that are not compatible. This is the clause that keeps mother
    and daughter apart.
  * two phone numbers that are both present and disagree. The address
    may be shared; a second differing number is the strongest signal
    available that these are two people, and it costs nothing to stop.
  * staff. An instructor or anyone with back-office access is never
    merged automatically - the blast radius is their access, not a
    booking history.
  * a pair where neither side holds any history at all. There is
    nothing to rescue, so there is no reason to take the risk.

A trial - even a spent one with no money attached - counts as history.
It is the specific thing that goes missing: she signs in, the contact
that used the free class is the other one, and the shop offers it to
her again.

OFF BY DEFAULT. fitness.signup_autojoin_enabled must be set to '1'.
The manager's Merge button is deliberately NOT governed by it: a person
who has looked at two records may always act.
"""
import logging
import unicodedata

from odoo import models

_logger = logging.getLogger(__name__)

AUTOJOIN_PARAM = 'fitness.signup_autojoin_enabled'

#: Spanish mobiles are nine digits; anything longer is a country code or
#: punctuation. Comparing the last nine makes +34 600 123 456 and
#: 600123456 the same number, which they are.
PHONE_SIGNIFICANT_DIGITS = 9


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

    # -- phone comparison -----------------------------------------------
    def _fitness_phone_digits(self):
        """The significant tail of any number on this contact.

        """
        self.ensure_one()
        # res.partner has no `mobile` in Odoo 19 - it was removed, and
        # reading it here would have raised in production. phone is the
        # only number a contact carries.
        out = set()
        digits = ''.join(c for c in (self.phone or '') if c.isdigit())
        if len(digits) >= PHONE_SIGNIFICANT_DIGITS:
            out.add(digits[-PHONE_SIGNIFICANT_DIGITS:])
        return out

    def _fitness_phones_disagree(self, other):
        """Both sides carry a number and none of them match.

        Only a positive disagreement counts. A contact with no number is
        not evidence against the join - the desk does not always ask.
        """
        self.ensure_one()
        mine, theirs = self._fitness_phone_digits(), other._fitness_phone_digits()
        if not mine or not theirs:
            return False
        return not (mine & theirs)

    # -- who must never be touched automatically -------------------------
    def _fitness_users(self):
        self.ensure_one()
        return self.env['res.users'].sudo().with_context(
            active_test=False).search([('partner_id', '=', self.id)])

    def _fitness_has_login(self):
        self.ensure_one()
        return bool(self._fitness_users())

    def _fitness_is_staff(self):
        """An instructor, a manager, or anyone with back-office access.

        Merging one of these automatically would move their access
        along with everything else, and an account that can see the
        whole studio is not something a verification redirect should be
        rearranging.
        """
        self.ensure_one()
        for user in self._fitness_users():
            if user._is_internal():
                return True
            for xmlid in ('fitness_core.group_fitness_teacher',
                          'fitness_core.group_fitness_manager'):
                if user.has_group(xmlid):
                    return True
        return False

    # -- history ---------------------------------------------------------
    def _fitness_history_counts(self):
        """What this contact is carrying, as (bookings, orders, trials).

        Trials are counted on purpose. A spent free trial has no money
        against it and produces no confirmed order, but it is exactly
        the thing that goes missing when a student ends up with two
        contacts: the shop offers her the free class again because the
        contact that used it is the other one.
        """
        self.ensure_one()
        bookings = self.env['fitness.booking'].sudo().search_count(
            [('student_id', '=', self.id)])
        orders = self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.id), ('state', 'in', ('sale', 'done'))])
        trials = self.env['fitness.trial.request'].sudo().search_count(
            [('partner_id', '=', self.id)])
        return bookings, orders, trials

    def _fitness_history_weight(self):
        self.ensure_one()
        return sum(self._fitness_history_counts())

    def _fitness_holds_money(self):
        """Anything financial on this contact.

        A trial and a booking are a history worth rescuing, and the join
        does that on its own. Money is different: a paid order, a
        payment, an invoice or a running membership all mean somebody
        has been charged, and if the merge turns out to have been wrong
        the money has moved onto a person it does not belong to.

        The asymmetry is the whole argument. Getting it wrong on a
        booking costs a roster correction. Getting it wrong on an
        invoice is somebody else's money against somebody else's name,
        in a system the studio uses to decide who has paid.

        So money does not stop the pair being dealt with - it stops it
        being dealt with by a redirect. It goes to the manager's list
        instead, where a person ticks to say she has looked.
        """
        self.ensure_one()
        if self.env['sale.order'].sudo().search_count([
                ('partner_id', '=', self.id),
                ('state', 'in', ('sale', 'done'))]):
            return True
        if self.env['sale.order'].sudo().search_count([
                ('partner_id', '=', self.id),
                ('subscription_state', '=', '3_progress')]):
            return True
        if self.env['account.move'].sudo().search_count([
                ('partner_id', '=', self.id),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '!=', 'cancel')]):
            return True
        if self.env['payment.transaction'].sudo().search_count([
                ('partner_id', '=', self.id),
                ('state', 'in', ('authorized', 'done'))]):
            return True
        return False

    # -- finding the one safe target --------------------------------------
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

    def _fitness_autojoin_refusal(self):
        """Why this contact may not be joined, or None if it may.

        Returns the reason so the caller can log it and the manager's
        list can show it. A join that silently does not happen is
        indistinguishable from one that was never attempted, and the
        studio would be left wondering why a student still signs in to
        an empty account.
        """
        self.ensure_one()
        if self.is_company or not self.email_normalized:
            return "no address to match on"
        if self._fitness_is_staff():
            return "staff account - never merged automatically"

        others = self._fitness_same_email_contacts()
        if not others:
            return "nothing else on this address"

        joinable = others.filtered(
            lambda p: not p._fitness_has_login() and not p._fitness_is_staff())
        if not joinable:
            return ("two accounts on one address - merging would take "
                    "somebody's login with it, so a person must decide")
        if len(joinable) > 1:
            return "more than one possible match - a person must choose"

        target = joinable
        if not self._fitness_names_compatible(target):
            return ("the names do not match - check these are not two "
                    "different people sharing an address")
        if self._fitness_phones_disagree(target):
            return ("the phone numbers disagree - a shared address with "
                    "two different numbers is two people, not one")
        if not (self._fitness_history_weight()
                or target._fitness_history_weight()):
            return "neither contact holds any history - nothing to rescue"
        if target._fitness_holds_money() or self._fitness_holds_money():
            return ("one of these has been charged - a paid order, an "
                    "invoice, a payment or a running membership. Money "
                    "moving onto the wrong person is not something a "
                    "redirect should decide, so a manager ticks for it")
        return None

    def _fitness_autojoin_target(self):
        """The one contact this may be joined into, or an empty set."""
        self.ensure_one()
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            AUTOJOIN_PARAM)
        if str(enabled).strip() not in ('1', 'True', 'true'):
            return self.browse()

        refusal = self._fitness_autojoin_refusal()
        if refusal:
            if 'nothing else on this address' not in refusal:
                _logger.info("[DUPLICATE] not joining %s (%s): %s",
                             self.display_name, self.email_normalized, refusal)
            return self.browse()
        return self._fitness_same_email_contacts().filtered(
            lambda p: not p._fitness_has_login() and not p._fitness_is_staff())

    # -- which record survives ---------------------------------------------
    def _fitness_pick_survivor(self, other):
        """The contact that keeps its id: the one holding the history.

        Her history is referenced from everywhere - bookings, order
        lines, invoices, the trial she already used. Keeping the record
        that already owns it means the merge moves the smaller side, and
        anything that cached the id of the real one still resolves.

        On a tie the older record wins, because it is the one the studio
        has been looking at.
        """
        self.ensure_one()
        other.ensure_one()
        mine, theirs = self._fitness_history_weight(), other._fitness_history_weight()
        if mine != theirs:
            return self if mine > theirs else other
        return self if self.id < other.id else other

    # -- the join -----------------------------------------------------------
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
        bookings, orders, trials = self._fitness_history_counts()
        _logger.warning(
            "[DUPLICATE] joining contact %s (id=%s) into %s (id=%s) on "
            "verified address %s",
            self.display_name, self.id, survivor.display_name, survivor.id,
            self.email_normalized)

        # Written BEFORE the merge, because afterwards there is nothing
        # left to read: _merge deletes this contact, and its name and id
        # go with it. See fitness_duplicate_join_log.py for why a log
        # line was not enough.
        self.env['fitness.duplicate.join.log'].sudo().create({
            'email': self.email_normalized or '',
            'survivor_id': survivor.id,
            'survivor_name': survivor.name or '',
            'merged_name': self.name or '',
            'merged_ref': self.id,
            'bookings_moved': bookings,
            'orders_moved': orders,
            'trials_moved': trials,
            'user_login': ', '.join(survivor._fitness_users().mapped('login')
                                    or self._fitness_users().mapped('login')),
        })

        self.env['base.partner.merge.automatic.wizard'].sudo()._merge(
            (survivor | self).ids, dst_partner=survivor)
        return survivor
