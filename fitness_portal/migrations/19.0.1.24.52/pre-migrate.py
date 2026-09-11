"""Clear the stored view translations so the Balance page's trial line can land.

The Balance page gained a line naming the unclaimed trial, so a student is not
told "1 free trial available" on the home page and "0" on the page that number
links to. New text in a view whose translated arches are already stored, and
Odoo never overwrites an existing translation - so without this the line would
appear in English to Spanish and Catalan students.

As with .18 through .48. Fresh installs are skipped: nothing stale to clear.
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
        "Balance page's trial line can land", cr.rowcount)
