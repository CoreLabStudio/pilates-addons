# -*- coding: utf-8 -*-
"""The Students menu has a Student List, and it lists students.

WHAT THIS IS FOR
----------------
The dashboard's Students tile opens a list of everyone who is a student.
That list was reachable only by going Home and clicking the number -
the Instructors section had an Instructor List and the Students section
had no equivalent, so the same records had one way in and the other
kind had two.

WHY IT IS A SERVER ACTION, AND WHY THAT NEEDS TESTING
-----------------------------------------------------
The domain cannot be written in XML. Teachers on this database are
portal users as well, so filtering on share=True alone lists them among
the students, and group membership is not searchable in Odoo 19 - the
teacher ids have to come from SQL. That is three chances to list the
wrong people, and all of them fail quietly: the menu still opens, the
list still has rows, and only somebody who knows the roll would notice
that an instructor is in it.

So these assert on WHO comes back, not that the action returns.
"""

from odoo.tests import TransactionCase, tagged

TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
STUDENT_GROUP = 'fitness_core.group_fitness_student'
MANAGER_GROUP = 'fitness_core.group_fitness_manager'


@tagged("post_install", "-at_install")
class TestStudentListMenu(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref("base.group_portal").id
        internal = cls.env.ref("base.group_user").id
        teacher = cls.env.ref(TEACHER_GROUP).id
        student = cls.env.ref(STUDENT_GROUP).id

        mk = cls.env["res.users"].with_context(no_reset_password=True).create
        cls.student = mk({
            "name": "Menu List Student", "login": "menulist.student",
            "group_ids": [(6, 0, [portal, student])]})
        cls.teacher = mk({
            "name": "Menu List Teacher", "login": "menulist.teacher",
            "group_ids": [(6, 0, [portal, teacher])]})
        cls.manager = mk({
            "name": "Menu List Manager", "login": "menulist.manager",
            "group_ids": [(6, 0, [internal, cls.env.ref(MANAGER_GROUP).id])]})
        cls.archived = mk({
            "name": "Menu List Archived", "login": "menulist.archived",
            "group_ids": [(6, 0, [portal, student])]})
        cls.archived.active = False

    def _listed(self):
        """The users the menu's action actually puts on screen."""
        action = self.env.ref(
            'fitness_portal.action_fitness_student_list_server').sudo()
        result = action.with_user(self.manager).run()
        self.assertTrue(
            isinstance(result, dict) and result.get('domain') is not None,
            "the server action returned %r rather than an action with a "
            "domain" % (result,))
        return self.env['res.users'].sudo().search(result['domain'])

    # ── the menu itself ─────────────────────────────────────────────────

    def test_the_students_menu_has_a_student_list(self):
        menu = self.env.ref('fitness_portal.menu_fitness_student_list',
                            raise_if_not_found=False)
        self.assertTrue(menu, "there is no Student List menu item")
        self.assertEqual(
            menu.parent_id, self.env.ref('fitness_core.menu_group_bookings'),
            "Student List is not under the Students menu")

    def test_it_sits_first_like_the_instructor_list_does(self):
        menu = self.env.ref('fitness_portal.menu_fitness_student_list')
        siblings = self.env['ir.ui.menu'].with_context(
            active_test=False).search(
                [('parent_id', '=', menu.parent_id.id)], order='sequence, id')
        self.assertEqual(
            siblings[:1], menu,
            "Student List is not the first entry under Students; it is "
            "behind %r" % (siblings[:1].name,))

    # ── who it lists ────────────────────────────────────────────────────

    def test_a_student_is_listed(self):
        self.assertIn(
            self.student, self._listed(),
            "the student list does not contain a student")

    def test_an_instructor_is_not_listed(self):
        """The one the share=True filter alone gets wrong.

        Instructors hold a portal login on this database, so without the
        group exclusion they appear among the students and the count
        disagrees with the dashboard.
        """
        self.assertNotIn(
            self.teacher, self._listed(),
            "an instructor is listed as a student - the teacher exclusion "
            "is not working, and nothing about the screen would say so")

    def test_an_internal_user_is_not_listed(self):
        self.assertNotIn(
            self.manager, self._listed(),
            "a staff account is listed as a student")

    def test_an_archived_student_is_not_listed(self):
        self.assertNotIn(
            self.archived, self._listed(),
            "an archived student is still on the list")

    # ── it agrees with the dashboard ────────────────────────────────────

    def test_it_lists_exactly_what_the_dashboard_tile_counts(self):
        """Two ways in, one answer.

        The tile and the menu are separate code reading the same idea, and
        separate code reading the same idea is how this project has got
        two different answers before. If they ever disagree, the number on
        Home stops meaning the list behind it.
        """
        dash = self.env['fitness.admin.dashboard'].with_user(
            self.manager).create({})
        self.assertEqual(
            len(self._listed()), dash.active_students,
            "the menu lists %d students and the dashboard tile counts %d"
            % (len(self._listed()), dash.active_students))
