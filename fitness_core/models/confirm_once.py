# -*- coding: utf-8 -*-
"""One dialog, one confirmation.

Independent QA opened one desk dialog for one free class and confirmed it
twice at the same moment, then once more: three orders, three free
classes, no error. A cash sale went the same way. Nothing marked the
dialog as used, so every press of its button did the whole job again -
a double click, a second tab, or a retry over RPC.

This is not a limit on giving. The owner gives free classes to family
and friends as often as she likes; a new dialog is a new gift, and
nothing here counts per student, product or day. What it stops is ONE
dialog doing its work twice.

How: the dialog's own row is locked (SELECT ... FOR UPDATE), checked and
marked inside the transaction that does the work. A second confirm of the
same dialog waits on the lock; when the first commits, Postgres refuses
the waiter's snapshot with a serialization failure, Odoo retries it, and
the retry reads the mark and is refused with a sentence. If the first
fails, its mark rolls back with everything else and the dialog can be
confirmed again. Call it AFTER the checks that may refuse, right before
the work, so a refusal never leaves a dialog marked.
"""
from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL


class FitnessConfirmOnce(models.AbstractModel):
    _name = 'fitness.confirm.once.mixin'
    _description = 'A dialog that can be confirmed only once'

    fitness_confirmed = fields.Boolean(
        'Already confirmed', readonly=True, copy=False, default=False)

    def _fitness_confirm_once(self):
        self.ensure_one()
        self.env.cr.execute(SQL(
            "SELECT fitness_confirmed FROM %s WHERE id = %s FOR UPDATE",
            SQL.identifier(self._table), self.id))
        row = self.env.cr.fetchone()
        if not row or row[0]:
            raise UserError(self.env._(
                "This dialog has already been confirmed, so nothing more "
                "was done. To do it again, open a new one."))
        self.env.cr.execute(SQL(
            "UPDATE %s SET fitness_confirmed = TRUE WHERE id = %s",
            SQL.identifier(self._table), self.id))
        self.invalidate_recordset(['fitness_confirmed'])
