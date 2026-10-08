# -*- coding: utf-8 -*-
"""Both duplicate menus live under Students, and only a manager sees them.

They used to sit loose at the bottom of the CoreLab menu, between
sections that had nothing to do with them. They belong next to Student
List, because that is what they are about: the same student, twice.

The ids and the actions do not change, so anything already linking to
them still resolves - that is asserted here rather than assumed, because
renaming a menu is exactly when an id gets "tidied" by accident.
"""
from odoo.tests import TransactionCase, tagged

MANAGER = "fitness_core.group_fitness_manager"
STUDENT = "fitness_core.group_fitness_student"
TEACHER = "fitness_core.group_fitness_teacher"


@tagged("post_install", "-at_install")
class TestDuplicateMenusUnderStudents(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.students_menu = cls.env.ref("fitness_core.menu_group_bookings")
        cls.student_list = cls.env.ref("fitness_portal.menu_fitness_student_list")
        cls.candidates = cls.env.ref(
            "fitness_portal.menu_fitness_duplicate_candidate")
        cls.history = cls.env.ref(
            "fitness_portal.menu_fitness_duplicate_join_log")

    def _visible_to(self, user):
        """The ids the web client would actually show this user.

        ir.ui.menu.search() does NOT filter by group - the filtering lives
        in _visible_menu_ids, which is what the web client calls. Asserting
        on a plain search would have reported an instructor seeing a
        manager-only menu that she cannot in fact reach.
        """
        return set(self.env["ir.ui.menu"].with_user(user)._visible_menu_ids())

    def _user(self, tag, groups):
        return self.env["res.users"].create({
            "name": "Menu %s" % tag,
            "login": "menu.%s@example.invalid" % tag,
            "group_ids": [(6, 0, [self.env.ref(g).id for g in groups])],
        })

    # == where they are ==============================================
    def test_both_sit_under_students(self):
        for menu in (self.candidates, self.history):
            self.assertEqual(
                menu.parent_id, self.students_menu,
                "%r is under %r, not Students"
                % (menu.name, menu.parent_id.name))

    def test_neither_is_loose_in_the_corelab_menu_any_more(self):
        """The negative: the old home must actually be empty of them."""
        root = self.env.ref("fitness_core.menu_fitness_root")
        loose = root.child_id.filtered(
            lambda m: m.id in (self.candidates.id, self.history.id))
        self.assertFalse(
            loose,
            "still hanging directly off CoreLab: %s" % loose.mapped('name'))

    def test_they_come_after_student_list(self):
        self.assertGreater(
            self.candidates.sequence, self.student_list.sequence,
            "Possible duplicates sorts above Student List")
        self.assertGreater(
            self.history.sequence, self.candidates.sequence,
            "Merge history sorts above Possible duplicates")

    def test_the_history_menu_is_renamed(self):
        self.assertEqual(self.history.name, "Merge history")

    # == the ids and actions are untouched ===========================
    def test_the_actions_still_resolve_by_their_old_ids(self):
        """A kept link, a bookmark, or anything referencing these."""
        for xmlid, model in (
                ("fitness_portal.action_fitness_duplicate_candidate",
                 "fitness.duplicate.candidate"),
                ("fitness_portal.action_fitness_duplicate_join_log",
                 "fitness.duplicate.join.log")):
            action = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(action, "%s no longer exists" % xmlid)
            self.assertEqual(
                action.res_model, model,
                "%s now opens %s" % (xmlid, action.res_model))

    def test_each_menu_still_points_at_its_own_action(self):
        self.assertEqual(
            self.candidates.action.id,
            self.env.ref("fitness_portal.action_fitness_duplicate_candidate").id)
        self.assertEqual(
            self.history.action.id,
            self.env.ref("fitness_portal.action_fitness_duplicate_join_log").id)

    # == who can see them ============================================
    def test_a_manager_sees_both(self):
        mgr = self._user("mgr", ["base.group_user", MANAGER])
        visible = self._visible_to(mgr)
        for menu in (self.candidates, self.history):
            self.assertIn(
                menu.id, visible,
                "a manager cannot see %r" % menu.name)

    def test_an_instructor_sees_neither(self):
        teacher = self._user("teacher", ["base.group_user", TEACHER])
        visible = self._visible_to(teacher)
        for menu in (self.candidates, self.history):
            self.assertNotIn(
                menu.id, visible,
                "an instructor can see %r, which lists other students' "
                "contact details" % menu.name)

    def test_a_student_cannot_reach_the_back_office_menus_at_all(self):
        """A portal account is a stronger case than "not in her list".

        _visible_menu_ids raises AccessError for a portal user - she
        cannot enumerate back-office menus in the first place, so there
        is no list for these to be absent from. Asserting the refusal
        says more than asserting an absence, and it is the refusal that
        actually protects the data.
        """
        from odoo.exceptions import AccessError
        student = self._user("student", ["base.group_portal", STUDENT])
        with self.assertRaises(AccessError):
            self._visible_to(student)
        self.assertFalse(
            student.has_group(MANAGER),
            "a student holds the manager group, which would let her read "
            "every other student's contact details")

    def test_the_groups_are_still_manager_only(self):
        manager_group = self.env.ref(MANAGER)
        for menu in (self.candidates, self.history):
            # group_ids, not groups_id: renamed in Odoo 19.
            self.assertEqual(
                menu.group_ids, manager_group,
                "%r is restricted to %s, not the manager group alone"
                % (menu.name, menu.group_ids.mapped('name')))
