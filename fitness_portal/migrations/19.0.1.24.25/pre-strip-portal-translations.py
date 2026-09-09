"""Clear the stored view translations so the matricula block can land.

Eight new model_terms strings on the Shop page: a heading, the fee line, and
the six benefits the client listed. They describe what the 39 EUR matricula
includes, and they appear on the Memberships tab only - the fee applies to
memberships, and the sheet is explicit that bonos carry none.

Nothing on any model changed. The matricula still has no field anywhere; this
is static copy describing it, which was the decision taken rather than
modelling the charge.

As with .18 through .22: the database already holds a translated arch for this
view and Odoo never overwrites an existing translation, so the new catalogue
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
