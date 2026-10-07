# -*- coding: utf-8 -*-
"""Where the automatic join stops, and what it leaves behind when it does.

The clauses in test_duplicate_merge_guards are about who may be joined.
These are about the edges around the act itself: when it may happen at
all, what happens when it fails, and who is allowed to see the result.

The money clause is the sharpest of them. A trial and a booking are a
history worth rescuing and the join does that on its own. A paid order,
an invoice, a payment or a running membership mean somebody has been
charged, and a wrong merge there moves money onto a person it does not
belong to - in the system the studio uses to decide who has paid. So
money does not stop the pair being dealt with, it stops it being dealt
with by a redirect.
"""
import logging

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_portal.models.res_partner_duplicate import (
    AUTOJOIN_PARAM,
)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestDuplicateJoinBoundaries(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        cls.Candidate = cls.env['fitness.duplicate.candidate'].sudo()
        cls.Log = cls.env['fitness.duplicate.join.log'].sudo()

    def _contact(self, name, email, trial=True, phone=None):
        partner = self.env['res.partner'].sudo().create(
            {'name': name, 'email': email, 'phone': phone})
        if trial:
            self.env['fitness.trial.request'].sudo().create({
                'name': name or 'x', 'email': email,
                'partner_id': partner.id})
        return partner

    def _user(self, name, email, groups=None):
        groups = groups or [self.env.ref('base.group_portal').id]
        return self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': name, 'login': email, 'email': email,
                'group_ids': [(6, 0, groups)]})

    def _paid_order(self, partner):
        order = self.env['sale.order'].sudo().create(
            {'partner_id': partner.id})
        order.sudo().write({'state': 'sale'})
        return order

    # == (1) money goes to a person ==================================
    def test_a_paid_order_on_the_other_contact_is_not_joined(self):
        desk = self._contact('Carles Perez', 'money1@example.invalid')
        self._paid_order(desk)
        user = self._user('Carles Perez', 'money1@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a contact that has been charged was merged by a redirect; a "
            "wrong merge there moves money onto the wrong person")

    def test_a_running_membership_on_the_other_contact_is_not_joined(self):
        desk = self._contact('Member Person', 'money2@example.invalid')
        order = self.env['sale.order'].sudo().create({'partner_id': desk.id})
        order.sudo().write({'subscription_state': '3_progress'})
        user = self._user('Member Person', 'money2@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a contact with a running membership was merged automatically")

    def test_a_payment_on_the_other_contact_is_not_joined(self):
        desk = self._contact('Paid Person', 'money3@example.invalid')
        provider = self.env['payment.provider'].sudo().search([], limit=1)
        method = self.env['payment.method'].sudo().with_context(
            active_test=False).search([], limit=1)
        if not provider or not method:
            self.skipTest("no payment provider on this database")
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': provider.id, 'payment_method_id': method.id,
            'reference': 'DUP-MONEY-3', 'amount': 10.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': desk.id})
        tx.sudo().write({'state': 'done'})
        user = self._user('Paid Person', 'money3@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a contact with a completed payment against it was merged "
            "automatically")

    def test_money_puts_the_pair_on_the_managers_list(self):
        """Refused is not the same as forgotten."""
        desk = self._contact('Listed Person', 'money4@example.invalid')
        self._paid_order(desk)
        self._user('Listed Person', 'money4@example.invalid')
        self.Candidate._scan()
        row = self.Candidate.search([('email', '=', 'money4@example.invalid')])
        self.assertTrue(
            row, "a pair refused for money vanished instead of being shown "
                 "to anybody")
        self.assertIn("charged", row.reason)

    # == (2) two candidates ==========================================
    def test_two_candidates_are_listed_not_joined(self):
        self._contact('Eva Morales', 'two@example.invalid')
        self._contact('Eva Morales', 'two@example.invalid')
        user = self._user('Eva Morales', 'two@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "with two possible contacts it picked one anyway")
        self.Candidate._scan()
        row = self.Candidate.search([('email', '=', 'two@example.invalid')])
        self.assertTrue(row, "the ambiguous group is not on the list")
        self.assertIn("more than one", row.reason)

    # == (3) relatives ===============================================
    def test_relatives_with_different_first_names_are_listed(self):
        self._contact('Carmen Ruiz', 'family@example.invalid')
        self._user('Lucia Ruiz', 'family@example.invalid')
        self.Candidate._scan()
        row = self.Candidate.search([('email', '=', 'family@example.invalid')])
        self.assertTrue(
            row, "two people sharing an address were neither joined nor "
                 "shown to anybody, so nothing happens at all")
        self.assertIn("names do not match", row.reason)

    # == (4) nothing happens before verification =====================
    def test_signing_up_alone_links_nothing(self):
        """The join is at verification, not at signup.

        Until she has followed the link there is no proof she controls
        the address, and an unverified signup is the easiest thing in
        the world to make with somebody else's email.
        """
        desk = self._contact('Unverified Person', 'unver@example.invalid')
        user = self._user('Unverified Person', 'unver@example.invalid')
        before = self.Log.search_count([])
        self.assertTrue(desk.exists(), "the desk contact is already gone")
        self.assertTrue(user.partner_id.exists())
        self.assertEqual(
            self.Log.search_count([]), before,
            "something was joined merely by signing up, before she had "
            "proved the address was hers")

    # == (5) the back office never joins =============================
    def test_the_back_office_student_action_never_joins(self):
        """A manager granting access is not her proving anything.

        make_student_wizard gives somebody the student role from the
        back office. That is a studio decision about access, not a
        statement about who controls the mailbox, so it must not drag a
        merge along with it.
        """
        import inspect
        from odoo.addons.fitness_portal.models import make_student_wizard
        source = inspect.getsource(make_student_wizard)
        self.assertNotIn(
            '_fitness_join_into', source,
            "the back-office student action merges contacts; granting "
            "access is not proof that an address belongs to anybody")
        self.assertNotIn('_fitness_autojoin_target', source)

    # == (5b) only OUR token may trigger a join =====================
    def test_only_our_own_token_can_trigger_a_join(self):
        """Odoo's signup token is not proof that she controls the inbox.

        verify_email accepts two tokens. Ours is emailed to her and
        spent on use, so following it proves she reads that mailbox.
        Odoo's signup token is also minted when a manager grants access
        from the back office, and a link a manager can paste anywhere
        says nothing about who holds the address - so the join must sit
        INSIDE the branch that only our own token reaches.

        Structural rather than behavioural: the distinction lives in the
        control flow of one endpoint, and this asserts the shape of it.
        It is here because reverting the guard previously broke nothing.
        """
        import inspect
        from odoo.addons.fitness_portal.controllers import signup_override
        src = inspect.getsource(signup_override)
        start = src.index('def verify_email')
        body = src[start:]
        nxt = body.find(chr(10) + '    @http.route', 1)
        if nxt > 0:
            body = body[:nxt]

        # find(), not index(). index() RAISES when the line is gone,
        # which reports as an error rather than a failed assertion - and
        # an error reads like the test is broken rather than like the
        # guard is. Measured: reverting the guard errored instead of
        # failing until this was changed.
        flag = body.find('verified_herself = bool(partner_user)')
        guard = body.find('if verified_herself:')
        join = body.find('_fitness_autojoin_target')

        self.assertNotEqual(
            join, -1,
            "verify_email no longer attempts the join at all")
        self.assertNotEqual(
            flag, -1,
            "verify_email no longer records WHICH token verified her, so "
            "it cannot tell our own single-use link from Odoo's signup "
            "token - which a manager can mint and paste anywhere")
        self.assertNotEqual(
            guard, -1,
            "the join is no longer guarded by verified_herself, so a "
            "back-office grant would trigger an automatic merge")
        self.assertLess(flag, join, "the flag is set after the join")
        self.assertLess(
            guard, join,
            "the join is NOT inside the our-own-token branch, so Odoo's "
            "signup token would join duplicates too")

    # == (6) verifying twice ========================================
    def test_joining_twice_does_nothing_the_second_time(self):
        desk = self._contact('Twice Person', 'twice@example.invalid')
        user = self._user('Twice Person', 'twice@example.invalid')
        partner = user.partner_id.sudo()

        target = partner._fitness_autojoin_target()
        self.assertTrue(target, "the fixture is not joinable at all")
        partner._fitness_join_into(target)
        after_first = self.Log.search_count([])

        again = user.partner_id.sudo()._fitness_autojoin_target()
        self.assertFalse(
            again, "a second verification found something to merge again, "
                   "so a forwarded link could keep merging contacts")
        self.assertEqual(
            self.Log.search_count([]), after_first,
            "a second audit record was written for one join")

    # == (7) a failing merge is survivable ===========================
    def test_a_failing_join_leaves_both_contacts_and_logs_a_warning(self):
        """Verification matters more than tidiness.

        A student who followed a valid link and met a 500 would be
        unable to verify at all - which is worse than the duplicate, and
        is the exact fault the whole verification flow was rewritten to
        fix. It also must not log at ERROR: the release gate counts
        ERROR lines, so a survivable failure would turn a green build
        red.
        """
        import inspect
        from odoo.addons.fitness_portal.controllers import signup_override
        source = inspect.getsource(signup_override.FitnessSignupOverride
                                   if hasattr(signup_override,
                                              'FitnessSignupOverride')
                                   else signup_override)
        self.assertIn(
            '_fitness_autojoin_target', source,
            "the verification endpoint no longer attempts the join")
        joining = source[source.index('_fitness_autojoin_target'):]
        self.assertNotIn(
            '_logger.exception', joining[:1200],
            "a failing join logs at ERROR, which fails the release gate "
            "for something designed to be survivable")
        self.assertIn(
            '_logger.warning', joining[:1200],
            "a failing join says nothing at all, so nobody would know")

    def test_a_failing_join_really_leaves_both_contacts(self):
        from unittest.mock import patch as mock_patch
        desk = self._contact('Boom Person', 'boom@example.invalid')
        user = self._user('Boom Person', 'boom@example.invalid')
        partner = user.partner_id.sudo()
        target = partner._fitness_autojoin_target()
        self.assertTrue(target)

        Wizard = type(self.env['base.partner.merge.automatic.wizard'])
        with mock_patch.object(Wizard, '_merge',
                               side_effect=ValueError('boom')):
            with self.assertRaises(ValueError):
                partner._fitness_join_into(target)
        self.assertTrue(desk.exists(), "the survivor was removed anyway")
        self.assertTrue(
            user.partner_id.exists(),
            "the contact that failed to merge was removed anyway, which "
            "is the worst of both outcomes")

    # == (8) the audit record ========================================
    def test_the_audit_record_holds_enough_to_reconstruct(self):
        desk = self._contact('Reconstruct Person', 'recon@example.invalid')
        user = self._user('Reconstruct Person', 'recon@example.invalid')
        self._paid_order(user.partner_id)
        gone = user.partner_id.id
        gone_name = user.partner_id.name

        user.partner_id.sudo()._fitness_join_into(desk)
        row = self.Log.search([('merged_ref', '=', gone)])
        self.assertTrue(row, "no record of the join at all")
        self.assertEqual(row.merged_name, gone_name)
        self.assertEqual(row.merged_ref, gone)
        self.assertEqual(row.survivor_id, desk)
        self.assertEqual(row.email, 'recon@example.invalid')
        self.assertEqual(
            row.orders_moved, 1,
            "the record says nothing moved when a paid order did, so it "
            "cannot be used to work out what was lost")

    # == (9) a quiet day =============================================
    def test_the_morning_note_is_silent_on_a_quiet_day(self):
        from unittest.mock import patch as mock_patch
        manager = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'Quiet Manager', 'login': 'quiet.mgr@example.invalid',
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref(MANAGER_GROUP).id])]})
        Notification = self.env['fitness.notification'].sudo()
        before = Notification.search_count([
            ('user_id', '=', manager.id),
            ('notification_type', '=', 'duplicate_contacts')])

        empty = self.Candidate.browse()
        with mock_patch.object(type(self.Candidate), '_scan',
                               return_value=empty):
            self.Candidate._cron_scan_and_notify()

        self.assertEqual(
            Notification.search_count([
                ('user_id', '=', manager.id),
                ('notification_type', '=', 'duplicate_contacts')]), before,
            "the studio was told about duplicates on a day with none, "
            "which is how a daily note becomes noise nobody reads")

    # == (10) who may see the list ===================================
    def test_a_student_cannot_see_the_list(self):
        student = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'Nosy Student', 'login': 'nosy.list@example.invalid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref(STUDENT_GROUP).id])]})
        row = self.Candidate.create({
            'email': 'secret@example.invalid', 'matched_on': 'email',
            'partner_count': 2, 'login_count': 1, 'reason': 'test'})
        with self.assertRaises(AccessError):
            row.with_user(student).read(['email'])

    def test_a_student_cannot_see_the_audit_log(self):
        student = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'Nosy Student 2', 'login': 'nosy.log@example.invalid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref(STUDENT_GROUP).id])]})
        row = self.Log.create({
            'email': 'secret2@example.invalid', 'merged_name': 'Somebody',
            'merged_ref': 999999})
        with self.assertRaises(AccessError):
            row.with_user(student).read(['merged_name'])
