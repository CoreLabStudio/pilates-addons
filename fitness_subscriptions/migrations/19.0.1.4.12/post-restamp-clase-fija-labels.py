"""Re-stamp Clase Fija labels that were written in the wrong timezone.

`name` is a stored computed field, so a label written while the context
carried a member's own timezone keeps that hour for everybody who reads it
afterwards - a class at 18:00 reading "21:30" for an account on
Asia/Calcutta. The compute now always answers the studio clock, but stored
rows keep whatever they were given, and recompute only fires when a
dependency changes. Nothing about the events changed here, so this asks for
the recompute directly.

Idempotent, and cheap: there are a handful of these rows, not thousands.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    slots = env['fitness.clase.fija'].with_context(active_test=False).search([])
    if not slots:
        return
    before = {s.id: s.name for s in slots}
    env.add_to_compute(slots._fields['name'], slots)
    slots.flush_recordset(['name'])
    changed = [(before[s.id], s.name) for s in slots if before[s.id] != s.name]
    for old, new in changed:
        _logger.info("[CLASE FIJA] label re-stamped: %r -> %r", old, new)
    _logger.info("[CLASE FIJA] %d label(s) checked, %d corrected",
                 len(slots), len(changed))
