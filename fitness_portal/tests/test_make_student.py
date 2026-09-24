# -*- coding: utf-8 -*-
"""Turning a desk contact into a student, including one with no email.

The case this exists for is the walk-in: somebody types her name and phone
into a contact and there is no further step on screen, so she sits in the
database as a plain contact - not a student, no login, invisible to the
student list. Finishing her off meant Settings > Users by hand, which is
how Eli's account ended up being made twice.

The awkward half is the login. Odoo's own portal wizard derives it from the
email and a student with no address therefore cannot be given one at all.
These tests pin that a username works, because the students a manager types
in by hand are exactly the ones least likely to have an email address.
"""

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMakeStudent(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.student_group = cls.env.ref("fitness_core.group_fitness_student")
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Make Student Manager",
                "login": "make.student.mgr@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })

    def _wizard(self, partner, user=None, **vals):
        wiz = self.env["fitness.make.student.wizard"].with_user(
            user or self.manager).with_context(
                active_id=partner.id, active_model="res.partner")
        defaults = wiz.default_get(
            ["partner_id", "login", "password", "lang"])
        defaults.update(vals)
        defaults.setdefault("password", "made-student-pw-1")
        return wiz.create(defaults)

    # ── the case it exists for ──────────────────────────────────────────────

    def test_a_contact_with_no_email_becomes_a_student(self):
        partner = self.env["res.partner"].create({
            "name": "Walk In Student", "email": False, "phone": "600111222"})
        self.assertFalse(partner.fitness_is_student,
                         "a plain contact should not read as a student")

        wiz = self._wizard(partner)
        self.assertTrue(wiz.login, "no login was suggested")
        self.assertNotIn("@", wiz.login,
                         "a contact with no email was given an address-shaped "
                         "login, which is what we are trying to avoid")
        wiz.action_make_student()

        partner.invalidate_recordset()
        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1)
        self.assertTrue(user, "no account was created")
        self.assertEqual(user.partner_id, partner,
                         "the account was attached to a different contact")
        self.assertIn(self.student_group, user.group_ids,
                      "the account is not a student")
        self.assertFalse(user.email,
                         "an email address was invented for her")
        self.assertTrue(partner.fitness_is_student,
                        "the contact still does not read as a student")

    def test_the_suggested_login_comes_from_her_name(self):
        partner = self.env["res.partner"].create({
            "name": "Núria Mundó Guixà", "email": False})
        wiz = self._wizard(partner)
        self.assertEqual(
            wiz.login, "nuria.mundo",
            "accents should be stripped - the studio reads this down a phone")

    def test_a_second_person_with_the_same_name_gets_a_free_login(self):
        first = self.env["res.partner"].create({"name": "Same Name"})
        self._wizard(first).action_make_student()
        second = self.env["res.partner"].create({"name": "Same Name"})
        wiz = self._wizard(second)
        self.assertNotEqual(wiz.login, "same.name",
                            "the suggested login collides with an existing one")
        wiz.action_make_student()
        self.assertTrue(second.fitness_is_student)

    # ── when she does have an address ───────────────────────────────────────

    def test_an_email_is_used_as_the_login_when_she_has_one(self):
        partner = self.env["res.partner"].create({
            "name": "Emailed Student", "email": "emailed@example.invalid"})
        wiz = self._wizard(partner)
        self.assertEqual(wiz.login, "emailed@example.invalid",
                         "her own address is the login she will expect")
        wiz.action_make_student()
        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1)
        self.assertEqual(user.email, "emailed@example.invalid")

    # ── it refuses the things it should ─────────────────────────────────────

    def test_a_taken_login_is_refused(self):
        partner = self.env["res.partner"].create({"name": "Clash Student"})
        with self.assertRaises(ValidationError):
            self._wizard(partner, login=self.manager.login)

    def test_only_a_manager_can_do_it(self):
        """Two layers, and both are checked because either alone is thin.

        The ACL stops a non-manager reaching the wizard at all. The guard
        inside the method stops one who got a wizard some other way - a
        record created for them, an id passed in. Testing only the ACL would
        pass against a method with no guard in it.
        """
        partner = self.env["res.partner"].create({"name": "Guarded Student"})
        plain = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Not A Manager",
                "login": "not.manager@example.invalid",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            })

        # 1. she cannot even open it
        with self.assertRaises(AccessError):
            self._wizard(partner, user=plain)

        # 2. and handed one, the method still refuses her
        wiz = self._wizard(partner)
        with self.assertRaises(UserError):
            wiz.with_user(plain).action_make_student()
        self.assertFalse(
            partner.fitness_is_student,
            "a non-manager managed to create a student account")

    def test_an_existing_account_gains_the_role_rather_than_a_second_one(self):
        """She already signed up as a portal user but was never a student -
        making her one must not leave her with two accounts."""
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Already Has Login",
                "login": "already.login@example.invalid",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            })
        partner = user.partner_id
        before = self.env["res.users"].sudo().search_count(
            [("partner_id", "=", partner.id)])

        self._wizard(partner).action_make_student()

        after = self.env["res.users"].sudo().search_count(
            [("partner_id", "=", partner.id)])
        self.assertEqual(after, before, "a second account was created for her")
        user.invalidate_recordset()
        self.assertIn(self.student_group, user.group_ids)

    # ── the flag the contact form reads ─────────────────────────────────────

    def test_the_contact_list_can_be_filtered_on_it(self):
        made = self.env["res.partner"].create({"name": "Filter Student"})
        self._wizard(made).action_make_student()
        plain = self.env["res.partner"].create({"name": "Filter Plain"})

        # Every shape the UI can send. Odoo rewrites a boolean filter on
        # its way in - "=" can arrive as "in" - and the first version of
        # this search inverted itself on that, listing every non-student as
        # a student. One assertion per operator, because passing on "="
        # alone is exactly what hid it.
        for domain in ([("fitness_is_student", "=", True)],
                       [("fitness_is_student", "in", [True])],
                       [("fitness_is_student", "!=", False)]):
            students = self.env["res.partner"].search(domain)
            self.assertIn(made, students, "%s missed a student" % domain)
            self.assertNotIn(plain, students,
                             "%s called a plain contact a student" % domain)

        for domain in ([("fitness_is_student", "=", False)],
                       [("fitness_is_student", "!=", True)]):
            non_students = self.env["res.partner"].search(domain)
            self.assertIn(plain, non_students, "%s missed a contact" % domain)
            self.assertNotIn(made, non_students,
                             "%s listed a student as a non-student" % domain)

    def test_the_column_and_the_filter_agree(self):
        """A record the column calls a student must be one the filter finds.

        They were computed two different ways - one on explicitly assigned
        groups, the other on assigned-plus-implied - so a person could read
        as a student on their own form and be missing from the filtered
        list."""
        made = self.env["res.partner"].create({"name": "Agree Student"})
        self._wizard(made).action_make_student()
        made.invalidate_recordset()

        found = self.env["res.partner"].search(
            [("fitness_is_student", "=", True)])
        self.assertEqual(
            made.fitness_is_student, made in found,
            "the contact form and the contact list disagree about her")
