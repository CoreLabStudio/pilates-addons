# -*- coding: utf-8 -*-
"""The Weekly Hours list must not become the default list for every user.

It had no priority, so it defaulted to 16 and beat every other res.users
list in the repo - all of which carry 32 deliberately. That made it THE
default list view for res.users, so any picker that did not name a view
rendered people in instructor columns: the Organizer dialog showed 136
accounts under "Classes / week" and "Hours / week", reading 0 and 0.00
for every student, because it was asking an instructor question of a
student.

One line, and the fix is easy to lose again - a sibling file carries a
comment explaining exactly this, which is how we know it was understood
and simply missed here. So it is pinned.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUserListViewPriority(TransactionCase):

    longMessage = False

    def test_the_weekly_hours_list_is_not_the_default(self):
        view = self.env.ref("fitness_core.view_fitness_teacher_hours_list")
        self.assertEqual(
            view.model, "res.users", "fixture wrong: not a res.users view")
        self.assertGreater(
            view.priority, 16,
            "the Weekly Hours list has default priority, so it is the "
            "default list view for res.users and every user picker renders "
            "students in instructor columns")

    def test_no_fitness_res_users_list_outranks_odoo_s_own(self):
        """The general rule, so a new view cannot repeat it."""
        ours = self.env["ir.ui.view"].search([
            ("model", "=", "res.users"),
            ("type", "=", "list"),
            ("mode", "=", "primary"),
        ]).filtered(
            lambda v: (v.name or "").startswith("fitness."))
        self.assertTrue(ours, "no fitness res.users list views found at all")
        for view in ours:
            self.assertGreater(
                view.priority, 16,
                "%s has priority %d, so it competes to be the default list "
                "view for every user picker in the database"
                % (view.name, view.priority))

    def test_the_default_user_list_is_still_odoo_s(self):
        """What the studio actually sees when nothing names a view."""
        default = self.env["ir.ui.view"]._get_view_id("res.users") \
            if hasattr(self.env["ir.ui.view"], "_get_view_id") else None
        arch = self.env["res.users"].get_view(view_type="list")["arch"]
        self.assertNotIn(
            "fitness_weekly_hours", arch,
            "the default user list is the instructor Weekly Hours view, so "
            "students are shown teaching columns")
        self.assertIsNot(default, False)
