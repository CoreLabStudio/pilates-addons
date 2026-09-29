# -*- coding: utf-8 -*-
"""The rule that lets an instructor read her own classes, and its adoption.

This rule decides whether the instructor portal shows anything at all,
and for months it was a record somebody had made by hand in Settings on
production. It had no xmlid, no module and no mention in the repository,
so production had it and every fresh database did not - which is exactly
how the same instructor test came out green on a restore and red on a
fresh install without either result being wrong.

Two things have to hold and neither is obvious:

  * the rule is in the repository now, and says what it said;
  * bringing it into the repository does not give production a SECOND
    copy. The loader finds records by xmlid, the hand-made one has none,
    so without the migration alongside it the XML would create a
    duplicate - two rules, same model, same group, ORed together, the
    behaviour looking perfectly correct while nothing owns one of them.

The adoption is tested by doing it: the xmlid is taken off the real rule
to put the database back into production's shape, the migration is run,
and the rule is counted.
"""

import importlib.util
import os

from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged

MIGRATION = ('19.0.2.6.70', 'pre-adopt-teacher-calendar-rule.py')
XMLID = 'fitness_core.rule_fitness_teacher_calendar_event'
RULE_NAME = 'Fitness Teachers: read own assigned classes'
# What a database being upgraded reports as its installed version. Any
# truthy value takes the migration's upgrade path rather than its
# fresh-install early return.
OLD_VERSION = '19.0.2.6.69'


def _load_migration():
    path = os.path.join(
        get_module_path('fitness_core'), 'migrations', *MIGRATION)
    spec = importlib.util.spec_from_file_location('_adopt_rule', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestTeacherCalendarRule(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher_group = cls.env.ref('fitness_core.group_fitness_teacher')
        cls.migration = _load_migration()

    # -- helpers, all read straight from SQL -----------------------------
    #
    # The ORM caches xmlid lookups, and this test removes and re-creates
    # exactly those rows. Asking the database each time is the only way
    # the answers mean anything.

    def _rules_for_teachers(self):
        """Every calendar.event rule scoped to the instructor group."""
        self.env.cr.execute("""
            SELECT r.id
              FROM ir_rule r
              JOIN ir_model m ON m.id = r.model_id
              JOIN rule_group_rel rg ON rg.rule_group_id = r.id
             WHERE m.model = 'calendar.event' AND rg.group_id = %s
             ORDER BY r.id
        """, (self.teacher_group.id,))
        return [row[0] for row in self.env.cr.fetchall()]

    def _xmlid_rows(self):
        module, name = XMLID.split('.', 1)
        self.env.cr.execute("""
            SELECT id, res_id FROM ir_model_data
             WHERE module = %s AND name = %s AND model = 'ir.rule'
        """, (module, name))
        return self.env.cr.fetchall()

    # -- the rule itself --------------------------------------------------

    def test_the_rule_is_in_the_repository(self):
        rule = self.env.ref(XMLID, raise_if_not_found=False)
        self.assertTrue(
            rule,
            "%s does not resolve. Without it an instructor can read none of "
            "her own classes and every page under /my/instructor is blank."
            % XMLID)
        self.assertEqual(rule.model_id.model, 'calendar.event')
        self.assertEqual(rule.domain_force, "[('user_id', '=', user.id)]")
        self.assertEqual(
            rule.groups.ids, self.teacher_group.ids,
            "the rule must be scoped to the instructor group and nothing "
            "else; a wider scope hands out other people's calendars")
        self.assertTrue(rule.active)
        self.assertTrue(rule.perm_read)
        for perm in ('perm_write', 'perm_create', 'perm_unlink'):
            self.assertFalse(
                rule[perm],
                "the rule grants %s. It is meant to let her READ her "
                "timetable, not edit it." % perm)

    def test_there_is_exactly_one_of_it(self):
        """The duplicate this whole exercise exists to prevent."""
        rule = self.env.ref(XMLID)
        found = self._rules_for_teachers()
        self.assertEqual(
            found, [rule.id],
            "expected exactly one calendar.event rule for the instructor "
            "group - the one in the repository - and found %d: %s. Two "
            "rules OR together, so a duplicate looks correct and is owned "
            "by nobody." % (len(found), found))

    # -- the migration ----------------------------------------------------

    def test_the_migration_adopts_the_hand_made_rule(self):
        """Production's exact shape: the rule is there, the xmlid is not."""
        rule = self.env.ref(XMLID)
        rule_id = rule.id

        rows = self._xmlid_rows()
        self.assertEqual(len(rows), 1, "fixture wrong: no xmlid to remove")
        self.env.cr.execute(
            "DELETE FROM ir_model_data WHERE id = %s", (rows[0][0],))
        self.assertEqual(
            self._xmlid_rows(), [],
            "the database is not in production's shape yet")
        self.assertEqual(
            self._rules_for_teachers(), [rule_id],
            "the rule itself must survive - only its xmlid was removed")

        self.migration.migrate(self.env.cr, OLD_VERSION)

        rows = self._xmlid_rows()
        self.assertEqual(
            len(rows), 1,
            "the migration did not give the hand-made rule an xmlid, so the "
            "XML would go on to create a second rule beside it")
        self.assertEqual(
            rows[0][1], rule_id,
            "the xmlid names rule %s, not the rule that was already there "
            "(%s). The loader would update the wrong record."
            % (rows[0][1], rule_id))
        self.assertEqual(
            self._rules_for_teachers(), [rule_id],
            "adoption created or removed a rule; it must only name one")

    def test_the_migration_adopts_a_renamed_rule_too(self):
        """Somebody edited the name in Settings. It is still the rule."""
        rule = self.env.ref(XMLID)
        rule_id = rule.id
        rows = self._xmlid_rows()
        self.env.cr.execute(
            "DELETE FROM ir_model_data WHERE id = %s", (rows[0][0],))
        self.env.cr.execute(
            "UPDATE ir_rule SET name = %s WHERE id = %s",
            ('Teachers - own classes', rule_id))

        self.migration.migrate(self.env.cr, OLD_VERSION)

        rows = self._xmlid_rows()
        self.assertEqual(len(rows), 1, "a renamed rule was not adopted")
        self.assertEqual(rows[0][1], rule_id)
        self.assertEqual(self._rules_for_teachers(), [rule_id])

    def test_running_the_migration_again_changes_nothing(self):
        """An upgrade run twice is an ordinary thing to do."""
        rule = self.env.ref(XMLID)
        before_rules = self._rules_for_teachers()
        before_rows = self._xmlid_rows()

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.migration.migrate(self.env.cr, OLD_VERSION)

        self.assertEqual(
            self._rules_for_teachers(), before_rules,
            "a second run changed the rules on the database")
        self.assertEqual(
            self._xmlid_rows(), before_rows,
            "a second run changed the xmlid row, so the upgrade is not "
            "idempotent and two upgrades do not leave one database")
        self.assertEqual(before_rows[0][1], rule.id)

    def test_a_fresh_install_is_left_to_the_xml(self):
        """version is falsy on install; the migration must not run then."""
        before_rows = self._xmlid_rows()
        self.env.cr.execute(
            "DELETE FROM ir_model_data WHERE id = %s", (before_rows[0][0],))

        self.migration.migrate(self.env.cr, None)

        self.assertEqual(
            self._xmlid_rows(), [],
            "the migration acted on a fresh install, where there is nothing "
            "to adopt and the XML creates the rule itself")
