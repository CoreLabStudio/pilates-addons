# -*- coding: utf-8 -*-
"""The Home dashboard action opens the same screen, and stops warning.

The server action behind Home returned a 'flags' key asking the form to
open read-only. Odoo 19's web client has no idea what that is: there is
no 'action.flags' and no 'form_view_initial_mode' anywhere in its JS.
clean_action() keeps unknown keys rather than dropping them, and logs
one warning each time - fourteen in a single day on production, and the
only warnings we were producing.

So this file pins two things that have to stay true together: the action
still opens exactly the screen it opened before, and running it through
the very function that emitted the warning now emits nothing.
"""
from odoo.addons.web.controllers.utils import clean_action
from odoo.tests import TransactionCase, tagged

CLEAN_ACTION_LOGGER = 'odoo.addons.web.controllers.utils'


@tagged("post_install", "-at_install")
class TestHomeActionIsClean(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create({
            "name": "Home Action Manager",
            "login": "home.action.manager@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("fitness_core.group_fitness_manager").id,
            ])],
        })
        cls.action = cls.env.ref("fitness_core.action_open_fitness_dashboard")

    def _run(self):
        return self.action.with_user(self.manager).run()

    # == it still opens the same screen =============================
    def test_home_still_opens_the_dashboard_form(self):
        result = self._run()
        self.assertEqual(result.get("type"), "ir.actions.act_window")
        self.assertEqual(
            result.get("res_model"), "fitness.admin.dashboard",
            "Home no longer opens the dashboard")
        self.assertEqual(result.get("view_mode"), "form")
        self.assertEqual(result.get("target"), "current")
        self.assertTrue(
            result.get("res_id"),
            "Home opened without a dashboard record, so every counter on "
            "it would be empty")

    def test_each_visit_still_gets_its_own_record(self):
        """The action creates one per visit; that is how the counters refresh."""
        first = self._run().get("res_id")
        second = self._run().get("res_id")
        self.assertNotEqual(
            first, second,
            "Home reused a dashboard record, so its figures would be "
            "whatever they were the last time somebody looked")

    # == and it no longer warns =====================================
    def test_the_action_carries_no_custom_properties(self):
        result = self._run()
        self.assertNotIn(
            "flags", result,
            "the dead 'flags' key is back. Odoo 19 ignores it and logs a "
            "warning on every single visit to Home")

    def test_cleaning_the_action_logs_nothing(self):
        """The real test: the function that emitted the warning, run for real.

        assertNoLogs is the assertion, not assertLogs - the point is the
        absence. Asserting on the returned dict alone would pass just as
        well with a different unknown key in it.
        """
        result = self._run()
        with self.assertNoLogs(CLEAN_ACTION_LOGGER, level="WARNING"):
            cleaned = clean_action(dict(result), self.env)
        self.assertEqual(
            cleaned.get("res_model"), "fitness.admin.dashboard",
            "cleaning the action changed what it opens")

    def test_an_unknown_key_would_still_be_caught(self):
        """Proves the test above can fail - otherwise it proves nothing."""
        result = self._run()
        result["flags"] = {"mode": "readonly"}
        with self.assertLogs(CLEAN_ACTION_LOGGER, level="WARNING") as caught:
            clean_action(result, self.env)
        self.assertIn(
            "custom properties", "\n".join(caught.output),
            "clean_action no longer warns about unknown keys at all, so "
            "the test above would pass whatever we returned")

    # == nothing on the screen was editable anyway ==================
    def test_the_form_has_nothing_to_type_into(self):
        """Why dropping 'flags' cannot change what the user sees.

        'flags' asked for read-only. If any field on this form were
        editable, removing it would be a behaviour change rather than
        deleting a dead letter - so that is what this asserts.
        """
        view = self.env.ref("fitness_core.view_fitness_admin_dashboard_form")
        arch = view.arch
        self.assertIn('create="0"', arch)
        model = self.env["fitness.admin.dashboard"]
        editable = []
        for name in model._fields:
            field = model._fields[name]
            if 'name="%s"' % name not in arch:
                continue
            marked_readonly = ('name="%s" readonly="1"' % name) in arch
            invisible = ('name="%s" invisible="1"' % name) in arch
            if field.compute or field.related or marked_readonly or invisible:
                continue
            editable.append(name)
        self.assertFalse(
            editable,
            "the dashboard form now has editable field(s) %s, so whether "
            "it opens read-only started to matter and this change needs "
            "looking at again" % editable)
