"""Clear the stored view translations so two renamed labels can land.

Two model_terms strings changed:

  * the portal footer tab that linked to /my/studio, "Classes" -> "My Schedule"
  * the home hero CTA, "Book a Class" -> "Schedule a Class"

"Classes" was deliberately not renamed everywhere. That msgid is shared by
mv_bottom_nav, portal_packages (the Shop tab) and portal_student_studio; only
the bottom-nav occurrence changed, and the other two still say "Classes",
which is right for them.

"My Schedule" already existed in both catalogues - the Studio tab's
"Available | My Schedule" toggle uses it - so the footer now reads exactly the
same words as that toggle, in every language. Only "Schedule a Class" is a new
source string.

As with .18, .19, .20 and .21: the database already holds a translated arch for
these views and Odoo never overwrites an existing translation, so the corrected
catalogue cannot land until the stored copy is cleared. Any change to a
model_terms string in this module needs one of these.

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
