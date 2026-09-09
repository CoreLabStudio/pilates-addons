# -*- coding: utf-8 -*-
"""Drop the stale Barre-specific label for the slot field.

The field used to be called "Barre Class Slot" because the picker was only
ever shown on Barre requests. It is now used for every discipline and the
English label says so, but Odoo never overwrites an existing translation - so
Spanish and Catalan kept reading "Franja de clase de Barre" on a Reformer
request. Clearing the two stale values lets this update write the new ones
from the catalogue.

Only the non-English values are touched, and only for this one field.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return          # fresh install: the catalogue is loaded as-is

    cr.execute("""
        UPDATE ir_model_fields
           SET field_description = field_description - 'es_ES' - 'ca_ES'
         WHERE model = 'fitness.trial.request'
           AND name  = 'occurrence_id'
    """)
    _logger.info(
        "fitness_trials: cleared stale es/ca labels on %s field(s); this "
        "update rebuilds them from the catalogue", cr.rowcount)
