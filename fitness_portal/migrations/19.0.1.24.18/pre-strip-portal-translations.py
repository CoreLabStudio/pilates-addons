# -*- coding: utf-8 -*-
"""Rebuild every stale portal view translation from the catalogue.

The Spanish class detail page showed "You don't have credit for this class
yet." and "Explore memberships, packages & classes" in English. Both were
already translated in es_ES.po and ca_ES.po - correctly, and long before this.
They had simply never reached the database, because Odoo does not overwrite a
translation that already exists: once a view has an es_ES arch, a later
catalogue import leaves it alone, and every string added after that first
import stays in English forever.

So this is not a missing translation. It is a delivery problem, and the two
strings that were noticed are not the only ones. Comparing every translated
es_ES entry against the arch actually stored found the English source still
sitting in SEVEN views:

    portal_active_orders          Active Orders
    portal_checkout_payment       Bank Transfer
    portal_credit_history         No credit activity in the selected month.
    portal_package_detail         Price, classes
    portal_packages               Private, Price on request, Active
    portal_student_class_detail   the two reported, plus the booking-opens line
    portal_student_home           Browse classes

Rather than strip the one view that was reported and leave the other six to be
found one at a time by whoever next reads a page in Spanish, this clears the
non-English arch on every view this module owns. The catalogue is the source
of truth for all of them; dropping the stored copies makes the same update
rebuild each one from it.

Deliberately a PRE-migration. Odoo's order is:

    pre-migration -> load views -> import translations -> post-migration

so stripping here is followed by the import that refills it. Post-migration
would clear the values after the load and leave the whole portal English in
every language until some later upgrade happened to reload it.

The cost of being broad: a translation edited by hand in the web UI on one of
these views would be replaced by the catalogue's wording. Nothing here is
maintained that way - the studio edits its details in Settings, not view
translations - and a catalogue that loses to an invisible database edit is the
thing that caused this bug twice already.

Fresh installs are skipped: nothing stale to clear, and their translations
come straight from the .po on first import.
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
