# -*- coding: utf-8 -*-
"""Clear the stored view translations so the reworded Shop heading can land.

The Shop page heading was "Packages, Memberships & Classes" and is now
"Classes, Memberships & Packages", to match the tab order beneath it after the
tabs were reordered to Classes -> Memberships -> Packages.

Rewording it changes the msgid, so es_ES and ca_ES have new entries in the
catalogue. That alone is not enough. The database already holds a translated
arch for this view from an earlier update, and Odoo never overwrites a
translation that already exists - so without this the page would keep serving
the old Spanish and Catalan heading, in the old order, and the corrected
catalogue would sit there unused.

Same reasoning and same statement as .18 and .19. As noted when .19 was
written: any change to a model_terms msgid in this module needs one of these,
because the catalogue can never win against a value already in the database.

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
