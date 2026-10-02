# -*- coding: utf-8 -*-
"""A studio manager can actually open Instructor List.

WHAT WENT WRONG
---------------
The Instructors menu is shown to group_fitness_manager, and the action
behind it refused them: "You don't have enough access rights to run this
action." The menu was there, it just did not work - for anybody except a
full administrator, which is why nobody noticed. Yoleyva is one.

Two causes, both in the server action:

  * it declared no group_ids. Odoo's _can_execute_action_on_records
    checks group membership WHEN an action names groups, and otherwise
    falls back to demanding write access on the action's model - here
    res.users, which only an Access Rights user has;
  * it read the underlying act_window with env.ref(...).read(), and
    reading ir.actions.act_window needs Administrator.

Found while adding the Student List submenu beside it: the new action
hit both in turn, which is how the old one came to be looked at.

WHY THE MANAGER IS BUILT THE WAY SHE IS
---------------------------------------
She holds base.group_user and group_fitness_manager and nothing else -
no Settings, no Access Rights - because an administrator passes these
tests whatever the action says, and a test that cannot fail is the
thing being guarded against. The fixture asserts she is not an
administrator rather than trusting the group list to stay that way.

The caches are cleared after she is made: group membership is ormcached,
and a user created and queried in the same transaction can otherwise be
read back with the groups she had a moment ago.
"""

from odoo.tests import TransactionCase, tagged

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
SERVER_ACTION = 'fitness_core.action_fitness_teacher_list_server'


@tagged("post_install", "-at_install")
class TestInstructorListOpensForAManager(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = cls.env["res.users"].with_context(no_reset_password=True).create
        cls.manager = mk({
            "name": "Instr Menu Manager", "login": "instrmenu.manager",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref(MANAGER_GROUP).id])]})
        cls.teacher = mk({
            "name": "Instr Menu Teacher", "login": "instrmenu.teacher",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref(TEACHER_GROUP).id])]})
        cls.outsider = mk({
            "name": "Instr Menu Outsider", "login": "instrmenu.outsider",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])]})
        # Group membership is ormcached; without this she can be read back
        # with the groups she had before the write.
        cls.env.invalidate_all()
        cls.env.registry.clear_cache()

    def test_the_fixture_manager_is_not_an_administrator(self):
        """Otherwise every assertion below passes for the wrong reason."""
        self.assertFalse(
            self.manager.has_group('base.group_system'),
            "the fixture manager is an administrator, so these tests would "
            "pass even with the access fault back in place")
        self.assertTrue(
            self.manager.has_group(MANAGER_GROUP),
            "fixture wrong: she is not a studio manager")

    def test_a_manager_can_open_the_instructor_list(self):
        action = self.env.ref(SERVER_ACTION).sudo()
        try:
            result = action.with_user(self.manager).run()
        except Exception as exc:                                # noqa: BLE001
            self.fail(
                "a studio manager is shown the Instructor List menu and "
                "refused when she clicks it: %s: %s"
                % (type(exc).__name__, exc))
        self.assertTrue(
            isinstance(result, dict) and result.get('domain') is not None,
            "the action returned %r rather than a window action with a "
            "domain" % (result,))

    def test_it_lists_instructors_and_nobody_else(self):
        result = self.env.ref(SERVER_ACTION).sudo().with_user(
            self.manager).run()
        listed = self.env['res.users'].sudo().search(result['domain'])
        self.assertIn(
            self.teacher, listed, "an instructor is missing from the list")
        self.assertNotIn(
            self.outsider, listed,
            "somebody who is not an instructor is on the instructor list")
        self.assertNotIn(
            self.manager, listed,
            "the manager is listed as one of her own instructors")

    def test_the_action_names_the_group_rather_than_relying_on_write_access(self):
        """The fix itself, stated so a later edit cannot quietly undo it.

        Dropping group_ids sends Odoo back to demanding write access on
        res.users, and the menu silently stops working for everyone who is
        not an administrator - which is exactly the state this was in.
        """
        action = self.env.ref(SERVER_ACTION).sudo()
        self.assertIn(
            self.env.ref(MANAGER_GROUP), action.group_ids,
            "the server action does not name the manager group, so Odoo "
            "will fall back to requiring write access on res.users")
