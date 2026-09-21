# -*- coding: utf-8 -*-
"""Getting a stuck student into the shop, and the crash that stranded them.

Two things live here, both from the same evening.

The first is the back-office action. /corelab/verify-email was the only place
in the codebase that granted the student group, and its link is a signed
payload embedding the account's latest login time - so logging in, even only
to check whether verification had worked, invalidated the student's own
outstanding link. Somebody anxious enough to keep checking could never get
in, and the studio had no way to help: two people needed a one-off script run
against production on 2026-09-21. The action is that script made permanent.

The second is the reason one of them could not even reach the "please verify"
page. See TestAwaitingVerification.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVerifyStudentAction(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Verify Manager",
            "login": "verify.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id])],
        })
        cls.student_group = cls.env.ref("fitness_core.group_fitness_student")

    def _stuck(self, login="verify.stuck@example.invalid"):
        """A portal account that signed up and never got through."""
        user = self.env["res.users"].create({
            "name": "Stuck Student", "login": login, "email": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])]})
        user.partner_id.signup_prepare(signup_type="signup")
        return user

    # -- the thing it exists for -------------------------------------------

    def test_a_stuck_student_is_given_shop_access(self):
        user = self._stuck()
        self.assertFalse(
            user.fitness_is_verified_student,
            "the fixture already had access, so this proves nothing")

        user.with_user(self.manager).action_fitness_verify_student()
        user.invalidate_recordset()

        self.assertTrue(
            user.fitness_is_verified_student,
            "the student still cannot open the shop after being verified")
        self.assertIn(
            self.student_group, user.all_group_ids,
            "the student group was not actually granted")

    def test_the_signup_is_cancelled_so_a_stale_link_cannot_be_replayed(self):
        """Same as the email route does, and for the same reason."""
        user = self._stuck()
        self.assertEqual(user.partner_id.signup_type, "signup")
        user.with_user(self.manager).action_fitness_verify_student()
        self.assertFalse(
            user.partner_id.signup_type,
            "the signup is still live, so a link sitting in an inbox could "
            "still be replayed after access was granted by hand")

    def test_running_it_twice_changes_nothing(self):
        user = self._stuck()
        user.with_user(self.manager).action_fitness_verify_student()
        user.invalidate_recordset()
        before = user.all_group_ids
        user.with_user(self.manager).action_fitness_verify_student()
        user.invalidate_recordset()
        self.assertEqual(before, user.all_group_ids,
                         "a second run changed the account's groups")

    # -- the guard rails ---------------------------------------------------

    def test_a_non_manager_is_refused(self):
        """groups= only hides the button; the method has to refuse too."""
        user = self._stuck()
        plain = self.env["res.users"].create({
            "name": "Not a manager",
            "login": "verify.plain@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        with self.assertRaises(UserError):
            user.with_user(plain).action_fitness_verify_student()
        user.invalidate_recordset()
        self.assertFalse(
            user.fitness_is_verified_student,
            "a non-manager managed to grant shop access")

    def test_an_internal_user_is_refused(self):
        """A misclick on the wrong record must not hand out a group."""
        internal = self.env["res.users"].create({
            "name": "Internal Person",
            "login": "verify.internal@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        with self.assertRaises(UserError):
            internal.with_user(self.manager).action_fitness_verify_student()
        internal.invalidate_recordset()
        self.assertNotIn(self.student_group, internal.all_group_ids)

    # -- finding them in the first place -----------------------------------

    def test_the_stuck_can_be_searched_for(self):
        """The "Cannot open the shop" filter is a search, and a non-stored
        compute cannot be searched without a search method."""
        user = self._stuck("verify.searchable@example.invalid")
        found = self.env["res.users"].search([
            ("fitness_is_verified_student", "=", False),
            ("id", "=", user.id)])
        self.assertEqual(
            found, user,
            "a stuck student cannot be found by the filter the studio would "
            "use, so nobody would ever know to help them")

        user.with_user(self.manager).action_fitness_verify_student()
        still = self.env["res.users"].search([
            ("fitness_is_verified_student", "=", False),
            ("id", "=", user.id)])
        self.assertFalse(
            still, "a verified student still shows as unable to open the shop")

    def test_the_filter_also_works_the_other_way(self):
        user = self._stuck("verify.other@example.invalid")
        user.with_user(self.manager).action_fitness_verify_student()
        found = self.env["res.users"].search([
            ("fitness_is_verified_student", "=", True), ("id", "=", user.id)])
        self.assertEqual(found, user)


@tagged("post_install", "-at_install")
class TestAwaitingVerification(TransactionCase):
    """The crash that stranded the people this whole feature is for.

    web_login sent an unverified portal user to the "please verify" page. The
    test read:

        partner.signup_type == 'signup' and partner.signup_valid

    `signup_valid` does not exist in Odoo 19 - auth_signup was rewritten and
    validity now lives inside the signed token rather than in a stored field.
    Python short-circuits, so the missing attribute was only ever evaluated
    when signup_type was 'signup', which is exactly the state of somebody who
    signed up and has not verified. The only people who could reach it were
    the only people the branch exists to help, and what they got was a 500 on
    login. Oriol Ferran is in that state on production and his account reads
    "never logged in".

    It survived because no test could reach it: web_login returns to base
    auth_signup immediately under test_enable, so the whole override is dead
    code during a test run. The predicate is a separate method now for exactly
    that reason - this calls it directly, and would have failed with
    AttributeError on the old code.
    """

    longMessage = False

    def _controller(self):
        from odoo.addons.fitness_portal.controllers.signup_override import (
            FitnessSignup)
        return FitnessSignup

    def _portal_user(self, login, signup=False):
        user = self.env["res.users"].create({
            "name": "Awaiting Probe", "login": login, "email": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])]})
        if signup:
            user.partner_id.signup_prepare(signup_type="signup")
        return user

    def test_a_signed_up_unverified_user_is_awaiting(self):
        """The exact state that used to raise AttributeError."""
        user = self._portal_user("awaiting.yes@example.invalid", signup=True)
        self.assertEqual(user.partner_id.signup_type, "signup")
        self.assertTrue(
            self._controller()._mv_awaiting_verification(user),
            "somebody mid-verification is not being sent to the verify page")

    def test_a_user_with_no_signup_is_not_awaiting(self):
        """Precondition set here rather than trusted to create().

        Whether a freshly created portal user already carries a signup varies
        with the database's invitation settings - it does on the test DB and
        does not on the restore - so the state under test is established
        explicitly and asserted before the thing being tested is called.
        """
        user = self._portal_user("awaiting.no@example.invalid")
        user.partner_id.sudo().signup_cancel()
        user.partner_id.invalidate_recordset()
        self.assertFalse(user.partner_id.signup_type,
                         "the fixture is not in the state under test")
        self.assertFalse(
            self._controller()._mv_awaiting_verification(user),
            "somebody with no signup pending is being sent to the verify page")

    def test_signup_valid_is_not_referenced_anywhere(self):
        """The field does not exist in Odoo 19. Nothing may read it.

        Blunt on purpose, and worth being honest about: the login override is
        unreachable under test_enable, so no functional test can cover that
        branch. Pinning the name is the only guard that survives somebody
        reinstating the check from an older Odoo's habits - and the cost of it
        coming back is a 500 on login for the people least able to report it.
        """
        import ast
        import inspect
        from odoo.addons.fitness_portal.controllers import signup_override

        # Parsed, not grepped. The first version of this test read the source
        # as text and flagged its own docstring, which quotes the old line to
        # explain it - a guard that fires on the explanation of the bug is
        # worse than no guard. An Attribute node is the access itself.
        tree = ast.parse(inspect.getsource(signup_override))
        offending = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "signup_valid"
        ]
        self.assertFalse(
            offending,
            "signup_override reads .signup_valid at line(s) %s. That field "
            "does not exist on res.partner in Odoo 19, so logging in raises "
            "AttributeError for any account mid-verification - a 500 for "
            "exactly the people least able to report it." % offending)

    def test_res_partner_really_has_no_signup_valid(self):
        """The premise of the test above, asserted rather than assumed.

        If a future Odoo brings the field back, this fails and the guard above
        can be reconsidered instead of quietly forbidding something legal.
        """
        self.assertNotIn(
            "signup_valid", self.env["res.partner"]._fields,
            "res.partner has signup_valid again; revisit the guard in "
            "test_signup_valid_is_not_referenced_anywhere")
