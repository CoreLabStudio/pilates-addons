# -*- coding: utf-8 -*-
"""Drop the stale es_ES/ca_ES arch on the Terms view so it rebuilds from the .po.

The English source of portal_terms was corrected twice - the operator became
"Core Lab Studio, S.L." instead of "Yoleyva Studio", and the "Last updated"
line stopped calling the document a draft pending legal review - but Odoo does
not overwrite an existing translation when it imports a catalogue. So on every
database that already carried the old values, the Spanish and Catalan pages
went on telling the reader that the studio was operated by Yoleyva Studio and
that the terms were a BORRADOR, no matter how correct the .po became.

Removing the non-English keys first lets this same update repopulate them from
the catalogue. Same shape as the fitness_reports migration that fixed the
report labels, and for the same reason.

Deliberately a PRE-migration. Odoo's update order is:

    pre-migration -> load views -> import translations -> post-migration

so stripping here is followed by the import that refills the values. Stripping
post-migration would clear them after the load and leave the Terms rendering
English in every language until some later upgrade happened to reload them.

Scoped to this one view. The public Terms and Privacy pages carry their own
per-language markup rather than translations, so they have nothing to strip and
are deliberately left alone.

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
           AND d.name = 'portal_terms'
           AND v.arch_db ? 'en_US'
           AND (SELECT count(*) FROM jsonb_object_keys(v.arch_db)) > 1
    """)
    _logger.info(
        "fitness_portal: cleared stale Terms translations on %s view(s); "
        "this update rebuilds them from the catalogue", cr.rowcount)
