"""Clear the stored view translations so the plan selector can land.

The membership checkout gained a billing-plan selector and a registration-fee
line on the order summary. Most of what it renders comes from the controller
and is translated through odoo-python entries, but the no-JS fallback button
is a literal in the arch, and the arch is what this clears.

As with .18 through .25: the database already holds a translated arch for this
view and Odoo never overwrites an existing translation, so new catalogue
entries cannot land until the stored copy is cleared.

Fresh installs are skipped: nothing stale to clear, and their translations come
straight from the .po on first import.
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
