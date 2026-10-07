# -*- coding: utf-8 -*-
"""The guards on joining two contacts, automatic and by hand.

Each test here removes exactly one protection's worth of safety from the
fixture and shows what stops. The failure mode being guarded against is
not a missed merge - it is two different people fused into one contact,
each carrying the other's bookings, credits and payment history, with no
way back.

The manager's Merge button has its own refusals, because a person
pressing a button has agreed the two are the same person but has not
necessarily noticed that both of them are booked into Tuesday's class.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_bookings.tests.booking_fixture import BookingFixture
from odoo.addons.fitness_portal.models.res_partner_duplicate import (
    AUTOJOIN_PARAM,
)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestDuplicateMergeGuards(BookingFixture, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')
        cls.Candidate = cls.env['fitness.duplicate.candidate'].sudo()
        cls.manager = cls.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': 'Guard Manager', 'login': 'guard.mgr@example.invalid',
                'lang': 'en_US',
                'group_ids': [(6, 0, [
                    cls.env.ref('base.group_user').id,
                    cls.env.ref(MANAGER_GROUP).id])]})
        cls.room = cls.env['fitness.classroom'].sudo().create({
            'name': 'Guard Room', 'classroom_type': 'reformer', 'capacity': 6})
        cls.ctype = cls.env['fitness.class.type'].sudo().create({
            'name': 'Guard Class', 'classroom_type': 'reformer',
            'session_type': 'group', 'level': 'all',
            'classroom_id': cls.room.id})

    # -- fixtures -----------------------------------------------------
    def _contact(self, name, email, phone=None):
        return self.env['res.partner'].sudo().create(
            {'name': name, 'email': email, 'phone': phone})

    def _user(self, name, email, phone=None, groups=None):
        groups = groups or [self.env.ref('base.group_portal').id]
        user = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': name, 'login': email, 'email': email,
                'group_ids': [(6, 0, groups)]})
        if phone:
            user.partner_id.sudo().phone = phone
        return user

    def _event(self, name='Guard event'):
        from datetime import timedelta
        from odoo import fields as f
        start = f.Datetime.now() + timedelta(days=3)
        return self.env['calendar.event'].sudo().create({
            'name': name, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'classroom_id': self.room.id,
            'is_fitness_class': True, 'capacity': 6})

    def _booking(self, partner, event, tag='guard'):
        """A booking with something that actually pays for it.

        Creating fitness.booking directly raises "No active subscription
        or package covers this class type": _select_payment_source runs
        on create and there has to be a confirmed line with credits on
        it. The shared fixture builds one, so this uses that rather than
        a second, divergent copy of the same setup.
        """
        self._a_payment_source(partner, 'pack', 'reformer', tag)
        return self.env['fitness.booking'].sudo().create({
            'student_id': partner.id, 'calendar_event_id': event.id,
            'state': 'booked'})

    def _candidate_for(self, a, b, email='row@example.invalid'):
        return self.Candidate.create({
            'email': email, 'matched_on': 'email',
            'partner_ids': [(6, 0, (a | b).ids)],
            'partner_count': 2, 'login_count': 1, 'reason': 'test row'})

    # == automatic join guards =======================================
    def test_trial_only_history_is_still_worth_joining(self):
        """A spent trial is the thing that goes missing.

        It carries no money and produces no confirmed order, so a rule
        that only looked at bookings and orders would call this contact
        empty and leave her signing in to an account that is offered the
        free class she has already had.
        """
        desk = self._contact('Nuria Planas', 'trialonly@example.invalid')
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Nuria Planas', 'email': 'trialonly@example.invalid',
            'partner_id': desk.id})
        user = self._user('Nuria Planas', 'trialonly@example.invalid')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "a contact whose only history is a used trial was treated as "
            "empty, so the student keeps being offered a free class she "
            "has already had")

    def test_a_pair_with_nothing_at_all_is_not_worth_the_risk(self):
        desk = self._contact('Empty Person', 'empty@example.invalid')
        user = self._user('Empty Person', 'empty@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "two contacts holding no history between them were merged "
            "anyway, which is all risk and no benefit")
        self.assertTrue(desk.exists())

    def test_disagreeing_phone_numbers_stop_the_join(self):
        """A shared address plus two different numbers is two people."""
        desk = self._contact('Ruiz', 'phone@example.invalid', '600111222')
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Ruiz', 'email': 'phone@example.invalid',
            'partner_id': desk.id})
        user = self._user('Ruiz', 'phone@example.invalid', '600999888')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "two contacts on one address with two different phone numbers "
            "were joined, which is the family case the rule exists to "
            "refuse")

    def test_the_same_number_written_differently_still_matches(self):
        """+34 600 111 222 and 600111222 are one number."""
        desk = self._contact('Ana Gil', 'intl@example.invalid', '600111222')
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Ana Gil', 'email': 'intl@example.invalid',
            'partner_id': desk.id})
        user = self._user('Ana Gil', 'intl@example.invalid', '+34 600 111 222')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "the same number with a country code was read as a different "
            "number, so a real duplicate is refused")

    def test_a_missing_number_is_not_evidence_against(self):
        desk = self._contact('Eva Soler', 'nophone@example.invalid', None)
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Eva Soler', 'email': 'nophone@example.invalid',
            'partner_id': desk.id})
        user = self._user('Eva Soler', 'nophone@example.invalid', '600111222')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "a contact with no phone number blocked the join, when the "
            "desk simply had not asked for one")

    def test_an_instructor_is_never_joined_automatically(self):
        teacher = self._user(
            'Masi Teacher', 'masi@example.invalid',
            groups=[self.env.ref('base.group_user').id,
                    self.env.ref(TEACHER_GROUP).id])
        desk = self._contact('Masi Teacher', 'masi@example.invalid')
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Masi Teacher', 'email': 'masi@example.invalid',
            'partner_id': desk.id})
        self.assertFalse(
            teacher.partner_id.sudo()._fitness_autojoin_target(),
            "an instructor's contact was merged automatically, which "
            "moves her studio access along with it")

    def test_a_back_office_account_is_never_joined_automatically(self):
        staff = self._user('Desk Staff', 'staff@example.invalid',
                           groups=[self.env.ref('base.group_user').id])
        desk = self._contact('Desk Staff', 'staff@example.invalid')
        self.env['fitness.trial.request'].sudo().create({
            'name': 'Desk Staff', 'email': 'staff@example.invalid',
            'partner_id': desk.id})
        self.assertFalse(
            staff.partner_id.sudo()._fitness_autojoin_target(),
            "an internal user was merged automatically")

    def test_the_survivor_is_the_one_holding_the_history(self):
        """Her record keeps its id, so references to it still resolve."""
        desk = self._contact('Laura Baussa', 'surv@example.invalid')
        event = self._event()
        self._booking(desk, event, 'surv')
        user = self._user('Laura Baussa', 'surv@example.invalid')
        new = user.partner_id

        survivor = new.sudo()._fitness_pick_survivor(desk)
        self.assertEqual(
            survivor, desk,
            "the contact holding the bookings was the one picked to be "
            "deleted, so every reference to her real record breaks")

        new.sudo()._fitness_join_into(survivor)
        self.assertEqual(
            self.env['fitness.booking'].sudo().search_count(
                [('student_id', '=', desk.id)]), 1,
            "the survivor does not hold the history after the merge")

    # == the manager's Merge =========================================
    def test_merge_refuses_without_the_tick(self):
        desk = self._contact('Tick Person', 'tick@example.invalid')
        user = self._user('Tick Person', 'tick@example.invalid')
        row = self._candidate_for(desk, user.partner_id)
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        self.assertIn("checked", str(caught.exception).lower())

    def test_merge_works_on_a_clear_pair(self):
        desk = self._contact('Clear Person', 'clear@example.invalid')
        event = self._event()
        self._booking(desk, event, 'clear')
        user = self._user('Clear Person', 'clear@example.invalid')
        gone = user.partner_id.id
        row = self._candidate_for(desk, user.partner_id)
        row.checked = True

        row.with_user(self.manager).action_merge()
        self.assertFalse(
            self.env['res.partner'].sudo().browse(gone).exists(),
            "Merge left both contacts in place")
        self.assertTrue(row.resolved, "the row was not marked dealt with")
        self.assertEqual(user.partner_id, desk)

    def test_merge_refuses_a_class_both_of_them_are_booked_into(self):
        """One student in one class twice, and the seat count wrong."""
        desk = self._contact('Double Booked', 'double@example.invalid')
        user = self._user('Double Booked', 'double@example.invalid')
        event = self._event('Tuesday Reformer')
        self._booking(desk, event, 'dbl_a')
        self._booking(user.partner_id, event, 'dbl_b')
        row = self._candidate_for(desk, user.partner_id)
        row.checked = True
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        self.assertIn("same class", str(caught.exception))
        self.assertIn("Tuesday Reformer", str(caught.exception),
                      "the refusal does not name the class, so nobody "
                      "knows which booking to cancel")

    def test_merge_refuses_two_running_memberships(self):
        """Otherwise one person pays twice, on two billing dates."""
        desk = self._contact('Two Plans', 'plans@example.invalid')
        user = self._user('Two Plans', 'plans@example.invalid')
        for partner in (desk, user.partner_id):
            order = self.env['sale.order'].sudo().create(
                {'partner_id': partner.id})
            order.sudo().write({'subscription_state': '3_progress'})
        row = self._candidate_for(desk, user.partner_id)
        row.checked = True
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        self.assertIn("membership", str(caught.exception).lower())

    def test_merge_refuses_a_staff_account(self):
        teacher = self._user(
            'Staff Merge', 'staffmerge@example.invalid',
            groups=[self.env.ref('base.group_user').id,
                    self.env.ref(TEACHER_GROUP).id])
        desk = self._contact('Staff Merge', 'staffmerge@example.invalid')
        row = self._candidate_for(desk, teacher.partner_id)
        row.checked = True
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        self.assertIn("staff", str(caught.exception).lower())

    def test_a_student_cannot_merge_over_rpc(self):
        """The model is reachable by name by anyone who can guess it."""
        student = self._user(
            'Nosy Student', 'nosy@example.invalid',
            groups=[self.env.ref('base.group_portal').id,
                    self.env.ref(STUDENT_GROUP).id])
        desk = self._contact('Nosy Student', 'nosy@example.invalid')
        row = self._candidate_for(desk, student.partner_id)
        row.sudo().checked = True
        # A single class, not a tuple: Odoo's assertRaises override calls
        # issubclass() on the argument and a tuple raises TypeError there,
        # which reads as the test erroring rather than the guard holding.
        with self.assertRaises(AccessError):
            row.with_user(student).action_merge()

    def test_merge_still_works_with_the_automatic_switch_off(self):
        """The switch stops the system acting, not a person."""
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '0')
        desk = self._contact('Switch Off', 'switchoff@example.invalid')
        user = self._user('Switch Off', 'switchoff@example.invalid')
        gone = user.partner_id.id
        row = self._candidate_for(desk, user.partner_id)
        row.checked = True

        row.with_user(self.manager).action_merge()
        self.assertFalse(
            self.env['res.partner'].sudo().browse(gone).exists(),
            "a manager who had looked at both records was refused "
            "because an automatic-join switch was off")

    def test_a_manual_merge_is_recorded_as_manual(self):
        desk = self._contact('Recorded Person', 'rec@example.invalid')
        user = self._user('Recorded Person', 'rec@example.invalid')
        gone = user.partner_id.id
        row = self._candidate_for(desk, user.partner_id)
        row.checked = True
        row.with_user(self.manager).action_merge()

        log = self.env['fitness.duplicate.join.log'].sudo().search(
            [('merged_ref', '=', gone)])
        self.assertTrue(log, "the manual merge left no audit record")
        self.assertFalse(
            log.was_automatic,
            "a merge a manager pressed is recorded as something the "
            "system did on its own")
        self.assertEqual(log.merged_by_id, self.manager)
