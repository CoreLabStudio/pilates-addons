# -*- coding: utf-8 -*-
"""Give the hand-made instructor rule an xmlid, so the module owns it.

THE SITUATION
-------------
Production carries a record rule called "Fitness Teachers: read own
assigned classes" on calendar.event, domain [('user_id','=',user.id)],
scoped to group_fitness_teacher. It is the only thing that lets an
instructor read her own classes, and therefore the only thing that makes
the instructor portal show anything at all.

It was made by hand in Settings > Technical > Record Rules on
2026-07-24. It has no ir_model_data row: no module owns it, no xmlid
names it, and nothing in the repository creates it. A fresh install has
never had it - which is why the same instructor test is green on a
restore of production and red on a fresh database.

WHY THE XML CANNOT SIMPLY BE ADDED
----------------------------------
Loading security/ir_rule.xml creates a record for an xmlid it cannot
find. On production it would not find the hand-made rule - an xmlid is
the only handle the loader has - so it would create a SECOND rule with
the same domain and the same group. Two rules on one model for one group
OR together, so the behaviour would look correct while the database
quietly carried a duplicate that nothing owns and nobody would think to
look for.

WHAT THIS DOES
--------------
It finds the existing rule and writes the ir_model_data row the loader
is about to look for. The loader then finds it and UPDATES it - one
rule, now owned by fitness_core, with its id, its name and anything else
on it preserved.

Matching is by name, model and group, exactly as the rule was described.
If that finds nothing, it falls back to any unowned rule on
calendar.event scoped to the instructor group, because that is the same
rule under a name somebody edited, and adopting it is what keeps the
count at one.

noupdate is left False on purpose, so a later correction to the domain
in the XML reaches production instead of stopping at the database that
needs it most.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
  * It creates no rule. On a database with no hand-made rule it does
    nothing at all and the XML creates one, which is the fresh-install
    path and is already correct.
  * It deletes nothing and deactivates nothing. If more than one unowned
    rule matches, it adopts one and LOGS the others rather than removing
    them: a record rule is an access control, and a migration that
    silently drops one is worse than a duplicate somebody has been told
    about.
  * It is re-runnable. If the xmlid already exists it returns without
    touching anything, so an upgrade run twice changes nothing.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = 'fitness_core'
XMLID = 'rule_fitness_teacher_calendar_event'
RULE_NAME = 'Fitness Teachers: read own assigned classes'


def migrate(cr, version):
    if not version:
        # Fresh install: there is nothing to adopt and the XML does it all.
        return

    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'fitness_core'
           AND name = 'group_fitness_teacher'
           AND model = 'res.groups'
    """)
    row = cr.fetchone()
    if not row:
        _logger.info(
            "[TEACHER-RULE] group_fitness_teacher not found; nothing to adopt")
        return
    group_id = row[0]

    # Already owned? Then this has run, or the rule was always ours.
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND name = %s AND model = 'ir.rule'
    """, (MODULE, XMLID))
    owned = cr.fetchone()
    if owned:
        _logger.info(
            "[TEACHER-RULE] %s.%s already names rule %s; nothing to do",
            MODULE, XMLID, owned[0])
        return

    # Every rule on calendar.event for the instructor group that no module
    # owns. An owned one is somebody else's and is left strictly alone.
    cr.execute("""
        SELECT r.id, r.name
          FROM ir_rule r
          JOIN ir_model m ON m.id = r.model_id
          JOIN rule_group_rel rg ON rg.rule_group_id = r.id
         WHERE m.model = 'calendar.event'
           AND rg.group_id = %s
           AND NOT EXISTS (
                 SELECT 1 FROM ir_model_data d
                  WHERE d.model = 'ir.rule' AND d.res_id = r.id)
         ORDER BY r.id
    """, (group_id,))
    candidates = cr.fetchall()

    if not candidates:
        _logger.info(
            "[TEACHER-RULE] no unowned instructor rule on calendar.event; "
            "the XML will create it")
        return

    exact = [c for c in candidates if (c[1] or '').strip() == RULE_NAME]
    chosen = (exact or candidates)[0]
    rule_id, rule_name = chosen
    if not exact:
        _logger.info(
            "[TEACHER-RULE] no rule named %r; adopting rule %s (%r) instead, "
            "which is the same rule under an edited name",
            RULE_NAME, rule_id, rule_name)

    cr.execute("""
        INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
             VALUES (%s, %s, 'ir.rule', %s, FALSE)
    """, (MODULE, XMLID, rule_id))
    _logger.info(
        "[TEACHER-RULE] adopted rule %s (%r) as %s.%s; the XML will now "
        "update it instead of creating a duplicate",
        rule_id, rule_name, MODULE, XMLID)

    leftovers = [c for c in candidates if c[0] != rule_id]
    if leftovers:
        _logger.info(
            "[TEACHER-RULE] %d further unowned rule(s) on calendar.event for "
            "the instructor group, left exactly as they are: %s",
            len(leftovers),
            ', '.join('%s (%r)' % (i, n) for i, n in leftovers))
