# -*- coding: utf-8 -*-
"""Joining a duplicate at verification, and - mostly - refusing to.

The join itself is three lines. What matters is everything it declines
to do, because the failure mode is not a missed merge: it is two
different people fused into one contact, carrying each other's bookings,
credits and payment history, with no undo.

So the refusals get the coverage. Every clause of the rule has a test
that removes only that clause's protection and shows the join stops.

The mother-and-daughter case is the one to read first:
test_two_people_on_one_address_are_never_joined.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_portal.models.res_partner_duplicate import (
    AUTOJOIN_PARAM,
)

STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestSignupDuplicateJoin(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '1')

    def _desk_contact(self, name, email, history=True, **vals):
        """A contact the studio made at the desk: no login of its own.

        It carries a trial by default, because the rule refuses a pair
        that holds nothing at all between them - there is nothing to
        rescue, so there is no reason to take the risk. A desk contact
        with no history whatsoever is not the case this feature exists
        for, and a fixture without one tests a refusal rather than a
        join. Pass history=False where that refusal IS the point.
        """
        partner = self.env['res.partner'].sudo().create(
            dict({'name': name, 'email': email}, **vals))
        if history:
            self.env['fitness.trial.request'].sudo().create({
                'name': name or 'x', 'email': email,
                'partner_id': partner.id})
        return partner

    def _signup_user(self, name, email):
        """A contact that arrived by signing up: it has a login."""
        user = self.env['res.users'].with_context(
            no_reset_password=True).sudo().create({
                'name': name,
                'login': email,
                'email': email,
                'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        return user

    # -- the case this exists for ------------------------------------
    def test_a_desk_contact_is_joined_into_on_verification(self):
        desk = self._desk_contact('Marta Munoz', 'marta@example.invalid')
        user = self._signup_user('Marta Munoz', 'marta@example.invalid')
        new = user.partner_id

        target = new.sudo()._fitness_autojoin_target()
        self.assertEqual(
            target, desk,
            "the desk contact carrying her history was not found as the "
            "one safe thing to join into")

        new.sudo()._fitness_join_into(target)
        self.assertFalse(
            new.exists(),
            "the duplicate contact is still there after the join")
        self.assertEqual(
            user.partner_id, desk,
            "her login no longer points at the contact holding her "
            "history, which is the whole point of joining them")

    def test_the_login_survives_the_join(self):
        """Same login, same password - only the contact underneath moves."""
        desk = self._desk_contact('Ana Lopez', 'ana@example.invalid')
        user = self._signup_user('Ana Lopez', 'ana@example.invalid')
        login_before = user.login
        user.partner_id.sudo()._fitness_join_into(desk)
        self.assertEqual(user.login, login_before,
                         "her login changed underneath her")
        self.assertTrue(user.active, "her account was deactivated")

    def test_accents_and_case_do_not_prevent_the_join(self):
        """The desk types accents; a signup form often does not."""
        desk = self._desk_contact('Nuria Planas', 'nuria@example.invalid')
        user = self._signup_user('NURIA  planas', 'Nuria@Example.Invalid')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "the same name in different case was treated as two people")

    def test_a_second_surname_still_counts_as_the_same_person(self):
        desk = self._desk_contact('Marta Munoz Garcia',
                                  'mmg@example.invalid')
        user = self._signup_user('Marta Munoz', 'mmg@example.invalid')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "a student recorded once with both surnames and once with "
            "one was treated as two people")

    # -- the audit record --------------------------------------------
    def test_the_join_is_written_down_before_it_happens(self):
        """The merge deletes the evidence. This is what is left.

        Written before, not after, because _merge unlinks the other
        contact: afterwards its name and id are gone and there is
        nothing to record. If an automatic join ever turns out to have
        fused two people, this row is what says which bookings and
        which orders came from the contact that no longer exists.
        """
        desk = self._desk_contact('Carles Perez', 'carles@example.invalid')
        order = self.env['sale.order'].sudo().create({'partner_id': desk.id})
        order.sudo().write({'state': 'sale'})
        user = self._signup_user('Carles', 'carles@example.invalid')
        new_partner = user.partner_id
        merged_id = new_partner.id

        Log = self.env['fitness.duplicate.join.log'].sudo()
        before = Log.search_count([])
        new_partner.sudo()._fitness_join_into(desk)

        rows = Log.search([('merged_ref', '=', merged_id)])
        self.assertEqual(
            Log.search_count([]), before + 1,
            "the automatic join left no record of itself at all")
        self.assertEqual(rows.survivor_id, desk)
        self.assertEqual(
            rows.merged_name, 'Carles',
            "the record does not say what the deleted contact was called, "
            "which is the one thing that cannot be looked up afterwards")
        self.assertEqual(rows.email, 'carles@example.invalid')

    def test_the_record_outlives_the_contact_it_describes(self):
        """The merged contact is gone; the row still reads correctly."""
        desk = self._desk_contact('Haley Fearnley', 'haley@example.invalid')
        user = self._signup_user('Haley Fearnley', 'haley@example.invalid')
        merged_id = user.partner_id.id
        user.partner_id.sudo()._fitness_join_into(desk)

        self.assertFalse(
            self.env['res.partner'].sudo().browse(merged_id).exists(),
            "the duplicate contact is still there, so this proves nothing")
        row = self.env['fitness.duplicate.join.log'].sudo().search(
            [('merged_ref', '=', merged_id)])
        self.assertTrue(
            row, "the record went with the contact it was describing")
        self.assertEqual(row.merged_name, 'Haley Fearnley')
        self.assertEqual(
            row.survivor_id, desk,
            "the surviving contact is no longer named on the record")

    def test_the_record_counts_what_moved(self):
        """A count taken after the merge would read zero and say nothing."""
        desk = self._desk_contact('Laura Baussa', 'laura@example.invalid')
        user = self._signup_user('Laura Baussa', 'laura@example.invalid')
        order = self.env['sale.order'].sudo().create(
            {'partner_id': user.partner_id.id})
        order.sudo().write({'state': 'sale'})
        merged_id = user.partner_id.id

        user.partner_id.sudo()._fitness_join_into(desk)
        row = self.env['fitness.duplicate.join.log'].sudo().search(
            [('merged_ref', '=', merged_id)])
        self.assertEqual(
            row.orders_moved, 1,
            "the record says nothing moved, when a confirmed order did - "
            "so it cannot be used to work out what was lost")

    # -- the refusals ------------------------------------------------
    def test_two_people_on_one_address_are_never_joined(self):
        """A family shares an address. They are not the same person.

        If this ever starts passing a join, a mother and daughter get
        fused into one contact and each inherits the other's bookings,
        credits and payments. There is no undo.
        """
        mother = self._desk_contact('Carmen Ruiz', 'family@example.invalid')
        daughter = self._signup_user('Lucia Ruiz', 'family@example.invalid')
        self.assertFalse(
            daughter.partner_id.sudo()._fitness_autojoin_target(),
            "two different names on one address were about to be merged "
            "into a single person")
        self.assertTrue(mother.exists())

    def test_a_contact_with_its_own_login_is_never_joined(self):
        """Two logins are two accounts. A manager decides, not a redirect."""
        other = self._signup_user('Sara Vidal', 'sara@example.invalid')
        second = self._signup_user('Sara Vidal', 'sara2@example.invalid')
        second.partner_id.sudo().write({'email': 'sara@example.invalid'})
        second.partner_id.sudo().flush_recordset()
        self.assertFalse(
            second.partner_id.sudo()._fitness_autojoin_target(),
            "a contact that has its own login was offered up to be "
            "merged away, which would take somebody's account with it")
        self.assertTrue(other.exists())

    def test_two_candidates_are_left_for_a_human(self):
        """Ambiguity is not resolved by guessing."""
        self._desk_contact('Eva Morales', 'eva@example.invalid')
        self._desk_contact('Eva Morales', 'eva@example.invalid')
        user = self._signup_user('Eva Morales', 'eva@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "with two possible contacts it picked one anyway, so half "
            "the time it attaches the wrong history")

    def test_a_nameless_contact_is_not_evidence(self):
        self._desk_contact('', 'noname@example.invalid')
        user = self._signup_user('Alba Serra', 'noname@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a contact with no name was treated as a match, when it is "
            "not evidence of anything")

    def test_a_company_is_never_joined(self):
        self._desk_contact('CoreLab SL', 'billing@example.invalid',
                           is_company=True)
        user = self._signup_user('CoreLab SL', 'billing@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a company contact was offered up for an automatic merge")

    def test_an_archived_duplicate_is_still_seen(self):
        """Archived does not mean gone: it still holds the history.

        search() hides archived records by default, and that alone turned
        the first version of the production probe into a clean bill of
        health on a database that had duplicates.
        """
        desk = self._desk_contact('Rosa Gil', 'rosa@example.invalid')
        desk.sudo().write({'active': False})
        user = self._signup_user('Rosa Gil', 'rosa@example.invalid')
        self.assertEqual(
            user.partner_id.sudo()._fitness_autojoin_target(), desk,
            "an archived duplicate was invisible, so she would sign in "
            "to an empty account and nothing would say why")

    # -- the switch --------------------------------------------------
    def test_it_does_nothing_until_it_is_switched_on(self):
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, '0')
        self._desk_contact('Clara Font', 'clara@example.invalid')
        user = self._signup_user('Clara Font', 'clara@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "it joined contacts while the parameter was off, so the "
            "safety switch does not switch anything")

    def test_a_pair_holding_nothing_is_not_worth_the_risk(self):
        """Nothing to rescue, so no reason to merge anything."""
        self._desk_contact('Hollow Person', 'hollow@example.invalid',
                           history=False)
        user = self._signup_user('Hollow Person', 'hollow@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "two contacts holding no history between them were merged, "
            "which is all risk and no benefit")

    def test_an_unset_parameter_means_off(self):
        """Unset must be OFF here - the opposite of the trial gate.

        The trial offer treats an unset deadline as "no deadline", which
        is right for an offer and wrong for this: a parameter nobody has
        set must not start merging customer records.
        """
        self.env['ir.config_parameter'].sudo().set_param(AUTOJOIN_PARAM, False)
        self._desk_contact('Ines Mas', 'ines@example.invalid')
        user = self._signup_user('Ines Mas', 'ines@example.invalid')
        self.assertFalse(
            user.partner_id.sudo()._fitness_autojoin_target(),
            "a database where nobody configured this started merging "
            "contacts on its own")
