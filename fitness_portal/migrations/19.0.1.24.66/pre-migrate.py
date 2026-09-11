"""Clear stored view translations so the rebuilt photo control can land.

The photo picker on the edit profile page changed shape - the file input is
visually hidden rather than display:none, and there is a line showing which
file was picked - and the view around "Change photo" changed with it. That
view already holds stored translations, and Odoo never overwrites one.

As with .18 through .64. Fresh installs are skipped: nothing stale to clear.
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
