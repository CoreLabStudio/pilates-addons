# -*- coding: utf-8 -*-
"""Give the hand-made CoreLab dashboard and its group their xmlids.

THE SITUATION
-------------
Production carries a spreadsheet dashboard called "CoreLab — Resumen
Mensual" in a group called "CoreLab Analytics". Both were made by hand
in the Spreadsheet UI. Neither has an ir_model_data row: no module owns
them, no xmlid names them, and until now nothing in the repository
created them.

The JSON was exported and committed to
fitness_reports/data/files/corelab_dashboard.json at some point, but
that file is referenced nowhere - not in the manifest, not in any view,
not in any model. It has never been loaded. A fresh install has no
CoreLab dashboard, and a rebuilt staging would have lost it silently.

WHY THE XML CANNOT SIMPLY BE ADDED
----------------------------------
Loading data/spreadsheet_dashboards.xml creates a record for an xmlid it
cannot find. On production it would not find the hand-made rows - an
xmlid is the only handle the loader has - so it would create a SECOND
dashboard and a SECOND group with the same names. Yoleyva would open
Dashboards and see "CoreLab Analytics" twice, each with its own copy,
one of which nothing owns and nobody would think to delete.

Exactly the shape of the instructor record rule adopted in
fitness_core/migrations/19.0.2.6.70, and handled the same way.

WHAT THIS DOES
--------------
Finds each row by name and writes the ir_model_data the loader is about
to look for. After this the XML UPDATES what is already there - keeping
its id, so nobody's favourite or share link breaks - instead of making a
duplicate beside it.

Matched on name because that is the only stable handle these rows have;
they have no xmlid, which is the whole problem. Narrow on purpose: if
the name has been changed, nothing is adopted and the XML creates a
fresh record, which is the safe failure - a spare dashboard is visible
and fixable, a silently rewritten one is not.

ON A FRESH DATABASE
-------------------
There is nothing to adopt and this does nothing. The XML then creates
both records normally. That is why `if not version` returns early: on a
fresh install Odoo passes no version and the tables may not even exist
yet.
"""

import logging

_logger = logging.getLogger(__name__)

ADOPT = [
    # (model, name to match, module, xmlid)
    ('spreadsheet.dashboard.group', 'CoreLab Analytics',
     'fitness_reports', 'spreadsheet_dashboard_group_corelab'),
    ('spreadsheet.dashboard', 'CoreLab — Resumen Mensual',
     'fitness_reports', 'dashboard_corelab_monthly'),
]


def migrate(cr, version):
    if not version:
        return

    for model, name, module, xmlid in ADOPT:
        table = model.replace('.', '_')

        cr.execute("SELECT to_regclass(%s)", (table,))
        if not cr.fetchone()[0]:
            _logger.info(
                "[DASHBOARD] %s does not exist on this database; nothing "
                "to adopt", table)
            continue

        # Already owned? Then a previous run did this, or the module has
        # always had it. Either way, leave it alone.
        cr.execute("""
            SELECT res_id FROM ir_model_data
             WHERE module = %s AND name = %s
        """, (module, xmlid))
        if cr.fetchone():
            _logger.info("[DASHBOARD] %s.%s already owned", module, xmlid)
            continue

        # name is a translated column on these models, so it is jsonb:
        # ->>'en_US' first, then any value, because the studio's rows
        # were typed in Spanish.
        cr.execute("""
            SELECT id FROM %s
             WHERE name->>'en_US' = %%s
                OR EXISTS (
                    SELECT 1 FROM jsonb_each_text(name)
                     WHERE value = %%s)
             ORDER BY id
             LIMIT 2
        """ % table, (name, name))
        found = [r[0] for r in cr.fetchall()]

        if not found:
            _logger.info(
                "[DASHBOARD] no %s named %r to adopt; the data file will "
                "create it", model, name)
            continue
        if len(found) > 1:
            _logger.warning(
                "[DASHBOARD] %d rows of %s named %r. Adopting none - "
                "which one the module should own is not a guess worth "
                "making. Resolve by hand, then upgrade again.",
                len(found), model, name)
            continue

        cr.execute("""
            INSERT INTO ir_model_data (module, name, model, res_id,
                                       noupdate, create_date, write_date)
            VALUES (%s, %s, %s, %s, false, now(), now())
        """, (module, xmlid, model, found[0]))
        _logger.info(
            "[DASHBOARD] adopted %s %s as %s.%s - the data file will now "
            "update it rather than create a duplicate",
            model, found[0], module, xmlid)
