# -*- coding: utf-8 -*-
"""The duplicates a person has to look at, and the note that says so.

The automatic join handles exactly one shape and refuses everything
else. Those refusals are correct, but silent on their own: the student
still signs in to an empty account and nobody at the studio knows there
is anything to do. This list is where the refusals go.

What matters here is that the list is neither empty nor noisy. A list
that misses the pair carrying somebody's bookings is useless; a list
that reopens decisions a manager has already made is worse, because she
stops reading it.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_portal.models.res_partner_duplicate import (
    AUTOJOIN_PARAM,
)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestDuplicateCandidateList(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        cls.Candidate = cls.env['fitness.duplicate.candidate'].sudo()
        cls.manager = cls.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'Duplicate Manager',
                'login': 'dup.manager@example.invalid',
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    cls.env.ref('base.group_user').id,
                    cls.env.ref(MANAGER_GROUP).id])]})

    def _contact(self, name, email, history=True, **vals):
        """A desk contact, carrying a trial unless told otherwise.

        The rule refuses a pair holding nothing between them, so a
        fixture without history exercises that refusal rather than the
        shape the test is named for.
        """
        partner = self.env['res.partner'].sudo().create(
            dict({'name': name, 'email': email}, **vals))
        if history:
            self.env['fitness.trial.request'].sudo().create({
                'name': name or 'x', 'email': email,
                'partner_id': partner.id})
        return partner

    def _user(self, name, email):
        return self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': name, 'login': email, 'email': email,
                'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})

    def _rows_for(self, email):
        return self.Candidate.search([('email', '=', email)])

    # -- what has to be on the list ----------------------------------
    def test_two_accounts_on_one_address_are_listed(self):
        self._user('Sara Vidal', 'two@example.invalid')
        second = self._user('Sara Vidal', 'two.b@example.invalid')
        second.partner_id.sudo().write({'email': 'two@example.invalid'})
        self.Candidate._scan()
        row = self._rows_for('two@example.invalid')
        self.assertTrue(
            row, "two logins on one address did not reach the manager's "
                 "list, so nobody will ever look at it")
        self.assertEqual(row.login_count, 2)
        self.assertIn("two accounts", row.reason)

    def test_mismatched_names_are_listed_not_joined(self):
        """The mother-and-daughter pair. Refused, and surfaced."""
        self._contact('Carmen Ruiz', 'family@example.invalid')
        self._user('Lucia Ruiz', 'family@example.invalid')
        self.Candidate._scan()
        row = self._rows_for('family@example.invalid')
        self.assertTrue(
            row, "a pair the automatic join refused on the name check "
                 "vanished instead of being shown to anybody")
        self.assertIn("names do not match", row.reason)

    def _verified(self, user):
        """Mark an account as having verified - what verify_email does."""
        user.sudo().write(
            {'group_ids': [(4, self.env.ref(STUDENT_GROUP).id)]})
        return user

    def test_a_clear_pair_on_a_VERIFIED_account_is_still_listed(self):
        """The shape most of the studio's real duplicates are in.

        Verification grants group_fitness_student, and it happens once.
        An account that already has it will never pass through
        verify_email again, so nothing will ever join its duplicate on
        its own. Leaving it off the list hid it for ever - and these
        are exactly the pairs where a student is signing in and not
        seeing her own history.
        """
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        self._contact('Haley Fearnley', 'verified@example.invalid')
        user = self._user('Haley Fearnley', 'verified@example.invalid')
        self._verified(user)
        self.Candidate._scan()
        row = self._rows_for('verified@example.invalid')
        self.assertTrue(
            row, "a clear pair whose account has already verified was left "
                 "off the list, so nothing will ever join it and nobody "
                 "will ever see it")
        self.assertIn("clear match", row.reason)
        self.assertIn("already verified", row.reason)

    def test_a_clear_pair_is_listed_while_the_switch_is_off(self):
        """Switch off means nothing joins, so everything needs a person."""
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '0')
        self._contact('Marta Munoz', 'switchoff@example.invalid')
        self._user('Marta Munoz', 'switchoff@example.invalid')
        self.Candidate._scan()
        row = self._rows_for('switchoff@example.invalid')
        self.assertTrue(
            row, "with the automatic join switched off, a clear pair was "
                 "still left off the list - so it would never be dealt "
                 "with at all")
        self.assertIn("clear match", row.reason)
        self.assertIn("switched off", row.reason)

    def test_the_pair_that_joins_itself_is_not_listed(self):
        """No busywork: this one really does resolve on its own.

        Only true when the switch is ON and her account has NOT verified
        yet - both conditions, because either one missing means the
        automatic join will never run for her.
        """
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        self._contact('Marta Munoz', 'auto@example.invalid')
        self._user('Marta Munoz', 'auto@example.invalid')
        self.Candidate._scan()
        self.assertFalse(
            self._rows_for('auto@example.invalid'),
            "a pair the system joins on its own was put on a manager's "
            "list as well, which is work she does not need to do")

    def test_a_pair_carrying_bookings_is_flagged(self):
        """The difference between tidying and a student locked out.

        Deliberately a pair the system will NOT join itself - the names
        differ, so it needs a person. A pair with matching names never
        reaches this list at all, which is what the first version of
        this test got wrong: it built the auto-joinable shape and then
        complained the list was empty.
        """
        desk = self._contact('Rosa Gil', 'hist@example.invalid')
        self._user('Marcos Pena', 'hist.b@example.invalid').partner_id.sudo(
        ).write({'email': 'hist@example.invalid'})
        order = self.env['sale.order'].sudo().create({'partner_id': desk.id})
        order.sudo().write({'state': 'sale'})
        self.Candidate._scan()
        row = self._rows_for('hist@example.invalid')
        self.assertTrue(row, "the pair is missing from the list entirely")
        self.assertTrue(
            row.has_history,
            "a pair where one side holds a paid order was not flagged as "
            "carrying history, so it sorts with the empty tidying jobs")
        self.assertEqual(
            row.order_count, 1,
            "the confirmed order on the desk contact was not counted")

    def test_a_phone_pair_with_different_emails_is_listed(self):
        """The pair an email search cannot see at all.

        Same student, work address on one contact and personal on the
        other. Nothing about her email matches, so until the scan looked
        at phone numbers she was invisible - and she is never joined
        automatically, because a number is not proof the way a verified
        address is.
        """
        a = self._contact('Clara Font', 'clara.work@example.invalid')
        a.sudo().phone = '600555444'
        b = self._user('Clara Font', 'clara.home@example.invalid')
        b.partner_id.sudo().phone = '+34 600 555 444'
        self.Candidate._scan()
        row = self.Candidate.search([('matched_on', '=', 'phone')]).filtered(
            lambda r: a in r.partner_ids and b.partner_id in r.partner_ids)
        self.assertTrue(
            row, "a student with two different addresses and one phone "
                 "number is invisible to the list, so nobody ever joins "
                 "her two contacts")
        self.assertIn("same phone number", row.reason)

    # -- what must stay off it ---------------------------------------
    def test_a_single_contact_is_not_a_duplicate(self):
        self._contact('Alone Person', 'alone@example.invalid')
        self.Candidate._scan()
        self.assertFalse(self._rows_for('alone@example.invalid'))

    def test_a_resolved_row_is_not_reopened_by_the_next_scan(self):
        """A manager's decision has to survive the nightly rebuild.

        The scan deletes and rebuilds the open rows, which is what keeps
        it from drifting out of step with the data. If it also wiped the
        ticked ones, every duplicate she dismissed would be back the
        next morning and she would stop reading the list.
        """
        self._user('Sara Vidal', 'keep@example.invalid')
        second = self._user('Sara Vidal', 'keep.b@example.invalid')
        second.partner_id.sudo().write({'email': 'keep@example.invalid'})
        self.Candidate._scan()
        row = self._rows_for('keep@example.invalid')
        self.assertTrue(row)
        row.resolved = True

        self.Candidate._scan()
        again = self._rows_for('keep@example.invalid')
        self.assertEqual(
            len(again), 1,
            "the rebuild created a second row for something already "
            "dealt with")
        self.assertTrue(
            again.resolved,
            "a duplicate a manager had ticked off came back open")

    # -- the morning note --------------------------------------------
    def test_the_managers_are_told_once_not_once_per_pair(self):
        """One bell for the list. Eleven bells is a bell nobody reads."""
        for n in range(3):
            a = self._user('Dup %d' % n, 'note%d@example.invalid' % n)
            b = self._user('Dup %d' % n, 'note%db@example.invalid' % n)
            b.partner_id.sudo().write({'email': 'note%d@example.invalid' % n})

        Notification = self.env['fitness.notification'].sudo()
        before = Notification.search_count([
            ('user_id', '=', self.manager.id),
            ('notification_type', '=', 'duplicate_contacts')])

        self.env['fitness.duplicate.candidate'].sudo()._cron_scan_and_notify()

        after = Notification.search_count([
            ('user_id', '=', self.manager.id),
            ('notification_type', '=', 'duplicate_contacts')])
        self.assertEqual(
            after, before + 1,
            "three duplicate pairs produced %d notifications; it must be "
            "one note about the list" % (after - before))

    def test_no_duplicates_means_no_note(self):
        """Silence when there is nothing to say.

        The scan is global, so this cannot be done by emptying the list
        and hoping: a database with real contacts in it has real
        duplicates, and the first version of this test passed on the
        fresh-install shape and failed on the upgrade shape for exactly
        that reason. What is under test is the branch - no open rows,
        no note - so the scan is made to return nothing and the branch
        is exercised directly.
        """
        Candidate = self.env['fitness.duplicate.candidate'].sudo()
        Notification = self.env['fitness.notification'].sudo()
        before = Notification.search_count([
            ('user_id', '=', self.manager.id),
            ('notification_type', '=', 'duplicate_contacts')])

        empty = Candidate.browse()
        with patch.object(type(Candidate), '_scan', return_value=empty):
            Candidate._cron_scan_and_notify()

        after = Notification.search_count([
            ('user_id', '=', self.manager.id),
            ('notification_type', '=', 'duplicate_contacts')])
        self.assertEqual(
            after, before,
            "the studio was told about duplicates when the scan found "
            "none, which is how a daily note becomes noise")
