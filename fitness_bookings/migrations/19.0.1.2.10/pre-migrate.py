"""Clear the stored view translations so the wizard's warning can land.

The late-cancellation wizard's warning banner - the sentence telling a manager
the student's credit will not come back - rendered in English whatever language
the back office was in. It now has Spanish and Catalan, but the database
already holds translated arches for this module's views and Odoo never
overwrites an existing translation, so the new text cannot land until the
stored copy is cleared.

Worth the migration for one sentence: it is the line that says what the action
costs the student, shown at the moment someone decides whether to take it.

Fresh installs are skipped: nothing stale to clear.
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
           AND d.module = 'fitness_bookings'
           AND v.arch_db ? 'en_US'
           AND (SELECT count(*) FROM jsonb_object_keys(v.arch_db)) > 1
    """)
    _logger.info(
        "fitness_bookings: cleared stale translations on %s view(s) so the "
        "late-cancellation warning can land", cr.rowcount)
