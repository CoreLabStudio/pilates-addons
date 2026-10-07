# -*- coding: utf-8 -*-
"""A row never shows a contact count with fewer names than it.

On production the manager opened a row reading "Contacts 4" with no
names at all beside it. partner_count is counted at scan time over every
contact sharing the address; the many2many tag widget renders only the
active ones. So an archived contact is counted and not shown, and a
merge gets decided on a screen that will not say who is being merged.

These pin the fix at the level that broke: the names, with archived ones
marked, and the refusal that quotes them.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDuplicateNamesShown(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Cand = cls.env["fitness.duplicate.candidate"].sudo()
        cls.Partner = cls.env["res.partner"].sudo()
        cls.manager = cls.env["res.users"].create({
            "name": "Names Manager",
            "login": "names.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id,
            ])],
        })

    def _row(self, partners, **extra):
        vals = {"email": "names.row@example.invalid",
                "partner_ids": [(6, 0, partners.ids)],
                "partner_count": len(partners)}
        vals.update(extra)
        return self.Cand.create(vals)

    def _pair(self, archive_second=True):
        live = self.Partner.create({"name": "Anna Live",
                                    "email": "names.row@example.invalid"})
        gone = self.Partner.create({"name": "Anna Archived",
                                    "email": "names.row@example.invalid"})
        if archive_second:
            gone.active = False
        return live, gone

    # == the bug itself ==============================================
    def test_an_archived_contact_is_named(self):
        live, gone = self._pair()
        row = self._row(live | gone)

        self.assertIn(
            "Anna Live", row.partner_names,
            "the active contact is missing from the names")
        self.assertIn(
            "Anna Archived", row.partner_names,
            "the archived contact is counted but not named - this is the "
            "screen the manager could not read")
        self.assertIn(
            "(archived)", row.partner_names,
            "the archived contact is named but not marked, so it reads "
            "like any other and gets merged away without a thought")

    def test_the_names_account_for_every_one_counted(self):
        """The count and the names must not be able to disagree again."""
        live, gone = self._pair()
        row = self._row(live | gone)
        self.assertEqual(
            len(row.partner_names.split(",")), row.partner_count,
            "%d contacts counted but %r named"
            % (row.partner_count, row.partner_names))

    def test_archived_names_is_only_the_archived_ones(self):
        live, gone = self._pair()
        row = self._row(live | gone)
        self.assertEqual(row.archived_names, "Anna Archived")
        self.assertNotIn(
            "Anna Live", row.archived_names,
            "an active contact is being reported as archived, so the "
            "warning cries wolf on every row")

    def test_a_row_with_nothing_archived_raises_no_warning(self):
        """The negative: the alert must stay off when it should."""
        live, other = self._pair(archive_second=False)
        row = self._row(live | other)
        self.assertFalse(
            row.archived_names,
            "the archived warning would show on a row with no archived "
            "contact, which teaches the manager to ignore it")
        self.assertNotIn("(archived)", row.partner_names)

    # == the refusal quotes them =====================================
    def test_the_refusal_names_the_contacts_it_counted(self):
        live, gone = self._pair()
        third = self.Partner.create({"name": "Anna Third",
                                     "email": "names.row@example.invalid"})
        row = self._row(live | gone | third, checked=True)

        from odoo.exceptions import UserError
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        msg = str(caught.exception)
        self.assertIn("3", msg, "the refusal does not say how many")
        self.assertIn(
            "Anna Archived", msg,
            "the refusal counts a contact it will not name, which is the "
            "same complaint one layer down")
        self.assertIn("(archived)", msg)
