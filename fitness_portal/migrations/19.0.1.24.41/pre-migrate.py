"""Clear the stored view translations for the trial redesign.

The trial is no longer taken off a shelf: its page and its shop card both
open the timetable instead, so the buttons read View and the copy above the
cards no longer asks the student to choose there.

As with .18 through .39: the database already holds a translated arch for
these views and Odoo never overwrites an existing translation, so the new
catalogue entries cannot land until the stored copy is cleared.

Fresh installs are skipped: nothing stale to clear, and their translations
come straight from the .po on first import.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # fresh install - nothing stale to clean up
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
        "fitness_portal: cleared stale translations on %s view(s); "
        "this update rebuilds them from the catalogue", cr.rowcount)
