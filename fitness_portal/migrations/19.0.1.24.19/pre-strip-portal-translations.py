# -*- coding: utf-8 -*-
"""Clear the stored view translations again, for two msgids corrected after .18.

The .18 migration stripped and rebuilt every view in this module, which fixed
eight entries per language. It did not fix two more - including the booking
window's subtext, "Classes open for booking a week ahead." - because the tool
that repaired the msgids reconstructed each entry as a single line in order to
find it, and gettext had wrapped those two across continuation lines:

    msgid ""
    "Classes open for booking a week ahead. Come back then to reserve your spot."

so the match failed and the entry was silently left alone. The msgids are now
correct, but the database already holds a Spanish arch from the .18 rebuild and
Odoo never overwrites an existing translation - so the corrected catalogue
cannot land without clearing the stored copy first. Same reasoning as .18,
applied to the two entries that pass missed.

If this keeps recurring it is worth saying plainly: any change to a
model_terms msgid in this module needs one of these, because the catalogue can
never win against a value already in the database.

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
