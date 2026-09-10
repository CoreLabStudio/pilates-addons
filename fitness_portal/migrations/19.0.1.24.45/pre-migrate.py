"""Clear the stored view translations so the renamed tab can land.

The shop's first tab is now "Initiation Class" rather than "Class Types".
The old name promised one thing and delivered another: "class type" means
Barre Groove or Reformer FlowLab everywhere else in the product - on the
timetable, on the class detail page, in the back office - while the tab it
named holds one-class purchases. A student who clicked it looking for Barre
Sculpt found a price list.

The heading above the tab and the home page's tile and links move with it,
so the name is the same wherever it is read.

As with .18 through .39: the database already holds a translated arch for
these views and Odoo never overwrites an existing translation, so the new
catalogue entries cannot land until the stored copy is cleared. Verified
before writing this - portal_packages had es_ES and ca_ES arches carrying
the old wording.

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
