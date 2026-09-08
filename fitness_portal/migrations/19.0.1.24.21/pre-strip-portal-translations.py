# -*- coding: utf-8 -*-
"""Clear the stored view translations so the reworded Shop heading can land.

The heading and the tab beneath it named the same thing with two different
words: the heading said "Paquetes"/"Paquets" while the tab said "Bonos"/"Bons".
The Spanish and Catalan translations now use the tab's word.

Only the msgstr changed - the English msgid is unchanged, because the English
heading and the English tab already agreed on "Packages". That makes no
difference to what has to happen here: the database holds a translated arch for
this view from the .20 rebuild, and Odoo never overwrites a translation that
already exists, so without this the page would keep serving "Paquetes" no
matter what the catalogue says.

Worth stating plainly, since this is the fourth of these: in this module, ANY
change to a translated view string needs one of these migrations - a new msgid
or merely a new msgstr. The catalogue can never win against a value already in
the database.

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
