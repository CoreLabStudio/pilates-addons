"""Clear the stored view translations so the cancel dialog's title can land.

The confirmation title was a lone inline <span>. Odoo folds one of those into
its parent's term, so the msgid carried the span markup and the plain
"Cancel this class?" translation never matched: a Spanish student saw an
English heading over a Spanish body and Spanish buttons. It is a block element
now, which makes it its own term - but the view already holds stored
translations, and Odoo never overwrites one.

As with .18 through .63. Fresh installs are skipped: nothing stale to clear.
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
