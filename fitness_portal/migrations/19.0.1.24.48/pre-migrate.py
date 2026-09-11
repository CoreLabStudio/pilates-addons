"""Clear the stored view translations so the reworded portal text can land.

Two changes reworded portal views in this release:

  * the studio's cancellation window moved from 2 hours to 6, and
  * the class-detail purchase prompt was renamed to the "Initiation Class"
    wording already used everywhere else.

In both cases the database already holds translated arches carrying the old
text - "2 horas", "2 hores" - and Odoo never overwrites an existing
translation, so the catalogue's new wording cannot land without clearing the
stored copy first.

The cancellation one matters more than a rename usually would. Without this,
Spanish and Catalan students would keep reading "2 horas" while the system
enforced 6, so the page would be telling them something untrue about when
their credit is safe. Verified before writing this: after the module update,
portal_terms still held es_ES and ca_ES arches saying "2 horas" / "2 hores"
while en_US already said 6.

As with .18 through .45. Fresh installs are skipped: nothing stale to clear,
and their translations come straight from the .po on first import.
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
        "fitness_portal: cleared stale translations on %s view(s) so the new "
        "cancellation window and prompt wording can land", cr.rowcount)
