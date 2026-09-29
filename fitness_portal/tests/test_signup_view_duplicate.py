# -*- coding: utf-8 -*-
"""One signup password-labels view applies, not two.

Production had two: a copy Yoleyva made by hand in the back office on
2026-08-17, and the module's own, added to signup_consent.xml later. The
loader matches records by xmlid, the hand-made one has none, so adding
it to the module could not update it and created a second copy instead.
Both active, both inheriting auth_signup.fields, both replacing the same
two labels.

The visible damage is nil, which is why it sat there: position="replace"
leaves a label the second xpath still matches. The real cost is that
editing the labels in the repository no longer decides what the signup
page shows.

The duplicate is ARCHIVED rather than deleted, so these check that the
record survives - a migration that destroys the only evidence of a
hand-made change is not a fix.
"""

import importlib.util
import os

from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged

MIGRATION = ('19.0.1.25.7', 'post-archive-duplicate-signup-view.py')
XMLID = 'fitness_portal.signup_fields_i18n'
KEY = 'fitness_portal.signup_fields_i18n'
OLD_VERSION = '19.0.1.25.6'


def _load_migration():
    path = os.path.join(
        get_module_path('fitness_portal'), 'migrations', *MIGRATION)
    spec = importlib.util.spec_from_file_location('_archive_signup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestSignupViewDuplicate(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owned = cls.env.ref(XMLID)
        cls.migration = _load_migration()

    # -- helpers: SQL, because the ORM caches what these tests change ----

    def _views_with_the_key(self, active_only=True):
        self.env.cr.execute("""
            SELECT v.id, v.active FROM ir_ui_view v
             WHERE v.key = %s AND (NOT %s OR v.active)
             ORDER BY v.id
        """, (KEY, active_only))
        return self.env.cr.fetchall()

    def _make_a_hand_made_copy(self):
        """What the back office leaves behind: no xmlid."""
        copy = self.env['ir.ui.view'].sudo().create({
            'name': 'Signup - Multilingual Password Labels',
            'type': 'qweb',
            'mode': 'extension',
            'key': KEY,
            'inherit_id': self.owned.inherit_id.id,
            'priority': self.owned.priority,
            'arch_db': self.owned.arch_db,
        })
        self.env.cr.execute(
            "DELETE FROM ir_model_data WHERE model = 'ir.ui.view' "
            "AND res_id = %s", (copy.id,))
        return copy

    # -- the invariant, on whatever shape this runs -----------------------

    def test_only_one_of_these_views_is_applied(self):
        """True on a fresh install, and true on the restore after upgrade."""
        active = self._views_with_the_key(active_only=True)
        self.assertEqual(
            [v[0] for v in active], [self.owned.id],
            "%d active views carry the key %s. The signup form applies "
            "every one of them, and only %s is in the repository."
            % (len(active), KEY, self.owned.id))

    def test_the_module_view_is_the_one_that_survives(self):
        self.assertTrue(
            self.owned.active,
            "the module's own signup view is archived, so the password "
            "labels on the signup form come from nothing in the repository")

    # -- the migration ----------------------------------------------------

    def test_a_hand_made_duplicate_is_archived(self):
        copy = self._make_a_hand_made_copy()
        self.assertEqual(
            len(self._views_with_the_key()), 2,
            "fixture wrong: the duplicate was not created")

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        active = self._views_with_the_key(active_only=True)
        self.assertEqual(
            [v[0] for v in active], [self.owned.id],
            "the hand-made duplicate is still being applied")

    def test_it_is_archived_and_not_deleted(self):
        copy = self._make_a_hand_made_copy()
        copy_id = copy.id

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT active FROM ir_ui_view WHERE id = %s", (copy_id,))
        row = self.env.cr.fetchone()
        self.assertTrue(
            row,
            "the hand-made view was DELETED. It is the only record of what "
            "was on the signup page and when; it must be archived.")
        self.assertFalse(
            row[0], "it was left active, so it is still being applied")

    def test_the_module_view_is_never_touched(self):
        self._make_a_hand_made_copy()

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT active FROM ir_ui_view WHERE id = %s", (self.owned.id,))
        self.assertTrue(
            self.env.cr.fetchone()[0],
            "the migration archived the module's own view")

    def test_running_it_again_changes_nothing(self):
        self._make_a_hand_made_copy()
        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()
        after_once = self._views_with_the_key(active_only=False)

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        self.assertEqual(
            self._views_with_the_key(active_only=False), after_once,
            "a second upgrade changed the views again, so two upgrades do "
            "not leave one database")

    # -- the guards -------------------------------------------------------

    def test_it_will_not_strip_the_labels_when_ours_is_inactive(self):
        """Archiving the only working copy is worse than the duplicate."""
        copy = self._make_a_hand_made_copy()
        self.env.cr.execute(
            "UPDATE ir_ui_view SET active = FALSE WHERE id = %s",
            (self.owned.id,))

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT active FROM ir_ui_view WHERE id = %s", (copy.id,))
        self.assertTrue(
            self.env.cr.fetchone()[0],
            "with the module's view switched off, the hand-made one is the "
            "only thing giving the signup form its Spanish and Catalan "
            "password labels, and it was archived anyway")

    def test_a_view_a_module_owns_is_left_alone(self):
        """Only UNOWNED duplicates are its business."""
        owned_copy = self.env['ir.ui.view'].sudo().create({
            'name': 'Someone Else Labels', 'type': 'qweb',
            'mode': 'extension', 'key': KEY,
            'inherit_id': self.owned.inherit_id.id,
            'arch_db': self.owned.arch_db,
        })
        self.env['ir.model.data'].sudo().create({
            'module': 'fitness_portal', 'name': 'probe_owned_signup_copy',
            'model': 'ir.ui.view', 'res_id': owned_copy.id})

        self.migration.migrate(self.env.cr, OLD_VERSION)
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT active FROM ir_ui_view WHERE id = %s", (owned_copy.id,))
        self.assertTrue(
            self.env.cr.fetchone()[0],
            "it archived a view that a module owns. Whatever created that "
            "one will recreate it, and the two will fight every upgrade.")

    def test_a_fresh_install_is_left_alone(self):
        copy = self._make_a_hand_made_copy()

        self.migration.migrate(self.env.cr, None)
        self.env.invalidate_all()

        self.env.cr.execute(
            "SELECT active FROM ir_ui_view WHERE id = %s", (copy.id,))
        self.assertTrue(
            self.env.cr.fetchone()[0],
            "the migration acted on a fresh install, where no hand-made "
            "view can exist and the only view with this key is ours")
