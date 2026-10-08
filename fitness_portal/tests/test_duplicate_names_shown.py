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


@tagged("post_install", "-at_install")
class TestMergeGuardSeesArchivedContacts(TransactionCase):
    """A row of three is refused however many of them are archived.

    The guard says Merge handles two contacts at a time. It used to read
    the many2many before applying active_test=False, so archived
    contacts had already been dropped by the time it counted - and a row
    of three containing one archived counted as two and merged.

    Three shapes, because each one failed differently: none archived was
    the only case that ever worked, one archived slipped through the
    count, and two archived made a row of three look like a row of one.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Cand = cls.env["fitness.duplicate.candidate"].sudo()
        cls.Partner = cls.env["res.partner"].sudo()
        cls.manager = cls.env["res.users"].create({
            "name": "Guard Manager",
            "login": "guard.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id,
            ])],
        })

    def _three(self, archived):
        """Three contacts on one address, `archived` of them archived."""
        email = "guard.three.%d@example.invalid" % archived
        people = self.Partner.browse()
        for i in range(3):
            p = self.Partner.create(
                {"name": "Guard Person %d" % (i + 1), "email": email})
            if i >= 3 - archived:
                p.active = False
            people |= p
        return self.Cand.create({
            "email": email,
            "partner_ids": [(6, 0, people.ids)],
            "partner_count": 3,
            "checked": True,
        })

    def _refusal(self, row):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError) as caught:
            row.with_user(self.manager).action_merge()
        return str(caught.exception)

    def test_three_active_contacts_are_refused(self):
        msg = self._refusal(self._three(archived=0))
        self.assertIn("3", msg, "the refusal does not say how many: %r" % msg)
        self.assertIn("Guard Person 1", msg)
        self.assertIn("Guard Person 3", msg)
        self.assertNotIn(
            "(archived)", msg,
            "nothing is archived here, so nothing should be marked: %r" % msg)

    def test_two_active_and_one_archived_are_refused(self):
        """The shape that used to merge: the archived one was invisible."""
        row = self._three(archived=1)
        msg = self._refusal(row)
        self.assertIn(
            "3", msg,
            "the row counted fewer than three, which is the bug: %r" % msg)
        self.assertIn(
            "Guard Person 3 (archived)", msg,
            "the refusal does not name the archived contact, so the "
            "manager still cannot tell what the third one is: %r" % msg)
        self.assertEqual(
            row.archived_names, "Guard Person 3",
            "the archived contact is not reported on the row either")

    def test_one_active_and_two_archived_are_refused(self):
        """A row of three that looked like a row of one on screen."""
        row = self._three(archived=2)
        msg = self._refusal(row)
        self.assertIn("3", msg)
        self.assertIn("Guard Person 2 (archived)", msg)
        self.assertIn("Guard Person 3 (archived)", msg)
        self.assertIn(
            "Guard Person 1", msg,
            "the one active contact is missing from the refusal: %r" % msg)

    def test_a_genuine_pair_is_still_allowed_through_the_count(self):
        """The negative: the guard must not refuse everything.

        Two contacts, one archived - the shape the feature exists for.
        It must get PAST the count and be judged on its merits, not
        bounced by the fix.
        """
        email = "guard.pair@example.invalid"
        live = self.Partner.create({"name": "Pair Live", "email": email})
        gone = self.Partner.create({"name": "Pair Archived", "email": email})
        gone.active = False
        row = self.Cand.create({
            "email": email, "partner_ids": [(6, 0, (live | gone).ids)],
            "partner_count": 2, "checked": True})
        from odoo.exceptions import UserError
        try:
            row.with_user(self.manager).action_merge()
        except UserError as e:
            self.assertNotIn(
                "two contacts at a time", str(e),
                "a genuine pair is being refused by the count guard, so "
                "the fix broke the thing it was protecting")
