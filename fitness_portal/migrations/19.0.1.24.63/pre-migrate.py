"""Clear the stored view translations so this batch's new text can land.

Two changes need it, and one strip covers both.

Editing yourself is a page now rather than a modal opened over whatever you
were looking at. The profile hub changed with it - the "About you" menu
section is gone and an "Edit profile" link sits under the photo, where Change
photo used to be.

And the studio can now see what a student filled in about herself, from a
Details button on the student form beside Bookings and Credits. It opens the
same res.partner record she edits on the portal, so it is her current answer
rather than a copy.

Both touch views whose translated arches are already stored, and Odoo never
overwrites an existing translation. Without this a Spanish or Catalan student
would find an English "Edit profile" under her photo, and the studio an
English "Details" beside five Spanish buttons.

As with .18 through .60. Fresh installs are skipped: nothing stale to clear.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE ir_ui_view v
           SET arch_db = jsonb_build_object('en_US', v.arch_db -> 'en_US')
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view'
           AND d.res_id = v.id
           AND d.module = 'fitness_portal'
           AND v.arch_db ? 'en_US'
           AND (SELECT count(*) FROM jsonb_object_keys(v.arch_db)) > 1
    """)
    _logger.info(
        "fitness_portal: cleared stale translations on %s view(s) so the "
        "profile sheet can land", cr.rowcount)
