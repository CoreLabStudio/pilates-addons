# -*- coding: utf-8 -*-
"""The Weekly Hours menu.

This action broke in a way nothing server-side could see. Its domain filtered
instructors with ref('fitness_core.group_fitness_teacher'), which reads like
ordinary Odoo data - except a window action's domain is a string the *browser*
evaluates, and ref() exists only on the server. The record loaded fine, the
module installed fine, and the menu raised "Name 'ref' is not defined" the
moment anyone clicked it.

So the test is the client's half of the contract: evaluate the stored domain
with nothing in scope, exactly as the browser does, and then search with the
result. Anything that needs a server-side name to make sense fails here.
"""
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestTeacherHoursAction(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.action = cls.env.ref("fitness_core.action_fitness_teacher_hours")
        cls.group = cls.env.ref("fitness_core.group_fitness_teacher")
        cls.teacher = cls.env["res.users"].create({
            "name": "Hours Test Instructor",
            "login": "hours.test.teacher@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id, cls.group.id])],
        })
        cls.student = cls.env["res.users"].create({
            "name": "Hours Test Student",
            "login": "hours.test.student@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })

    def test_the_domain_evaluates_with_nothing_in_scope(self):
        """No ref(), no %(xmlid)d, nothing the browser cannot resolve."""
        self.assertNotIn("ref(", self.action.domain)
        self.assertNotIn("%(", self.action.domain)
        # safe_eval with an empty namespace is what the client does
        parsed = safe_eval(self.action.domain, {})
        self.assertTrue(parsed, "the action lost its domain")

    def test_it_lists_instructors_and_nobody_else(self):
        found = self.env["res.users"].search(safe_eval(self.action.domain, {}))
        self.assertIn(self.teacher, found)
        self.assertNotIn(self.student, found)

    def test_an_archived_instructor_stays_out(self):
        """Archived is a decision the studio made; the report has to respect it."""
        self.teacher.action_archive()
        found = self.env["res.users"].search(safe_eval(self.action.domain, {}))
        self.assertNotIn(self.teacher, found)
        self.assertEqual(self.action.context, "{'active_test': True}",
                         "the action stopped asking for active records only")

    def test_every_operator_the_client_may_send(self):
        """Odoo rewrites ('field', '=', True) to ('field', 'in', [True]).

        Supporting only = and != raised "Unsupported operator in" on the one
        domain this field exists for, so each form is exercised here.
        """
        Users = self.env["res.users"]
        yes = Users.search([("fitness_is_teacher", "=", True)])
        self.assertEqual(yes, Users.search([("fitness_is_teacher", "in", [True])]))
        no = Users.search([("fitness_is_teacher", "=", False)])
        self.assertEqual(no, Users.search([("fitness_is_teacher", "not in", [True])]))
        self.assertEqual(no, Users.search([("fitness_is_teacher", "!=", True)]))
        self.assertIn(self.teacher, yes)
        self.assertIn(self.student, no)
        self.assertFalse(yes & no, "a user counted as both instructor and not")

    def test_the_flag_agrees_with_the_search(self):
        found = self.env["res.users"].search([("fitness_is_teacher", "=", True)])
        self.assertTrue(all(u.fitness_is_teacher for u in found))
        self.assertFalse(self.student.fitness_is_teacher)

    def test_the_report_views_are_the_ones_that_open(self):
        """Unpinned, base's own res.users list can win on a fresh database.

        The report would then render as a plain list of users with none of the
        hours on it - and only on odoo.sh, where the database is built by
        installing rather than upgrading.
        """
        modes = {v.view_mode: v.view_id for v in self.action.view_ids}
        self.assertEqual(
            modes.get("list"),
            self.env.ref("fitness_core.view_fitness_teacher_hours_list"))
        self.assertEqual(
            modes.get("form"),
            self.env.ref("fitness_core.view_fitness_teacher_hours_form"))
