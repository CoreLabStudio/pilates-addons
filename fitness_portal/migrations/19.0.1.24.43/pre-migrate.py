"""Clear the stored view translations for the audit fixes.

Five strings were reaching Spanish and Catalan readers in English because
they had never been exported into the catalogue at all. Adding them is only
half the job: the database still holds a translated arch for these views and
Odoo never overwrites an existing translation, so the stored copy has to go
first.

Fresh installs are skipped: nothing stale to clear, and their translations
come straight from the .po on first import.
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
        "fitness_portal: cleared stale translations on %s view(s); "
        "this update rebuilds them from the catalogue", cr.rowcount)
