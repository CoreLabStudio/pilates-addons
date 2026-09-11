"""Clear the stored view translations so the profile sheet's text can land.

Students can now tell the studio a few things about themselves - time of day
they prefer, music, a mobile number, an emergency contact - from a sheet opened
either by the pencil beside the greeting or from the profile page. That sheet
is new text in views whose translated arches are already stored, and Odoo never
overwrites an existing translation, so without this it would open in English
for Spanish and Catalan students.

The emergency contact is the one that matters here. A student who cannot read
the label is a student whose emergency contact the studio does not have.

As with .18 through .52. Fresh installs are skipped: nothing stale to clear.
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
