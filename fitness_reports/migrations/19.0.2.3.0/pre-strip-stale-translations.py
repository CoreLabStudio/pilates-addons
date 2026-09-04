# -*- coding: utf-8 -*-
"""Drop stale es_ES/ca_ES arch on the report views so they rebuild from the .po.

This module's labels were written Spanish-first and have been rewritten to
English. Odoo does not overwrite an existing translation when it imports a
catalogue, so on any database that already carries the old values the Spanish
and Catalan arch keeps whatever it had - "Bookings" went on rendering as the
old "Analitica de reservas" no matter how correct the new .po entries were.

Removing the non-English keys first lets this same update repopulate them from
the catalogue, which is exactly what the manual fix did on the development
database.

Deliberately a PRE-migration. Odoo's update order is:

    pre-migration -> load views -> import translations -> post-migration

so stripping here is followed by the import that refills the values. Doing it
post-migration would strip the translations *after* they had been loaded and
leave the reports rendering English in every language until some later
upgrade happened to reload them.

Fresh installs are skipped: they have no stale values to clear, and their
translations come straight from the .po on first import.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # fresh install - nothing stale to clean up
        return

    # Scoped by xmlid to views this module owns, so a view another module
    # merely inherits or extends is left alone. Rows that only carry en_US
    # are skipped, which keeps the migration a no-op on a database that has
    # never had the other languages loaded.
    cr.execute("""
        UPDATE ir_ui_view v
           SET arch_db = jsonb_build_object('en_US', v.arch_db -> 'en_US')
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view'
           AND d.res_id = v.id
           AND d.module = 'fitness_reports'
           AND v.arch_db ? 'en_US'
           AND (SELECT count(*) FROM jsonb_object_keys(v.arch_db)) > 1
    """)
    _logger.info(
        "fitness_reports: cleared stale translations on %s view(s); "
        "this update rebuilds them from the catalogue", cr.rowcount)
