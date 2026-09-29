# -*- coding: utf-8 -*-
"""Archive the hand-made copy of the signup password-labels view.

THE SITUATION
-------------
Production carries TWO views with the key
fitness_portal.signup_fields_i18n, both active, both inheriting
auth_signup.fields, both at priority 16, and both containing the same
two xpaths:

  * one made by hand in the back office on 2026-08-17, with no xmlid and
    in no module;
  * the module's own, from views/signup_consent.xml.

The hand-made one came first. When the same view was later added to the
module properly, the loader had no way to recognise it - records are
matched by xmlid and that one has none - so it created a second copy
beside it. The signup form therefore applies the same replacement twice.

Nothing visibly breaks today, because position="replace" leaves a label
the second xpath can still match. What does break is maintenance: edit
the labels in signup_consent.xml and production keeps the stale copy
applied alongside the new one, with no way to tell from the repository
that it is there.

ARCHIVE, NOT DELETE
-------------------
It is set inactive and left in place. An archived view is skipped
entirely when a template is built, so the duplication stops at once and
the record stays readable, attributable and reversible - untick Archived
and it is exactly as it was. Deleting a view somebody made by hand
destroys the only evidence of what was on the page and when, and if this
turns out to have been the wrong call there is nothing to put back.

THE GUARD
---------
It archives the hand-made view ONLY when the module's own view exists
and is active. Otherwise archiving would not remove a duplicate, it
would remove the behaviour: the signup form would lose its Spanish and
Catalan password labels entirely, which is worse than applying the right
ones twice.

It is re-runnable. A view already archived is left alone, so an upgrade
run twice changes nothing.
"""

import logging

_logger = logging.getLogger(__name__)

XMLID = ('fitness_portal', 'signup_fields_i18n')
KEY = 'fitness_portal.signup_fields_i18n'


def migrate(cr, version):
    if not version:
        # Fresh install: only the module's view can exist.
        return

    module, name = XMLID
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND name = %s AND model = 'ir.ui.view'
    """, (module, name))
    row = cr.fetchone()
    if not row:
        _logger.info(
            "[SIGNUP-VIEW] %s.%s does not exist on this database; nothing "
            "is archived, because that would remove the labels rather than "
            "a duplicate of them", module, name)
        return
    owned_id = row[0]

    cr.execute("SELECT active, inherit_id FROM ir_ui_view WHERE id = %s",
               (owned_id,))
    owned = cr.fetchone()
    if not owned or not owned[0]:
        _logger.info(
            "[SIGNUP-VIEW] the module's own view %s is inactive; leaving "
            "the hand-made one alone so the signup form keeps its labels",
            owned_id)
        return
    owned_inherit = owned[1]

    # Same key, same thing inherited, no module owns it, still active.
    cr.execute("""
        SELECT v.id FROM ir_ui_view v
         WHERE v.key = %s
           AND v.id <> %s
           AND v.active
           AND v.inherit_id IS NOT DISTINCT FROM %s
           AND NOT EXISTS (SELECT 1 FROM ir_model_data d
                            WHERE d.model = 'ir.ui.view' AND d.res_id = v.id)
         ORDER BY v.id
    """, (KEY, owned_id, owned_inherit))
    duplicates = [r[0] for r in cr.fetchall()]

    if not duplicates:
        _logger.info(
            "[SIGNUP-VIEW] no unowned active duplicate of %s; nothing to do",
            KEY)
        return

    cr.execute(
        "UPDATE ir_ui_view SET active = FALSE WHERE id IN %s",
        (tuple(duplicates),))
    _logger.info(
        "[SIGNUP-VIEW] archived %d hand-made duplicate(s) of %s: %s. The "
        "module's view %s is now the only one applied. Nothing was deleted; "
        "untick Archived to restore any of them.",
        len(duplicates), KEY,
        ', '.join(str(i) for i in duplicates), owned_id)
