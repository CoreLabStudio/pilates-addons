# -*- coding: utf-8 -*-
"""What was joined into what, kept after the evidence is gone.

A merge is destructive. base.partner.merge.automatic.wizard._merge moves
every foreign key onto the survivor and then deletes the other contact,
so once it has run there is nothing left to compare against: the id is
gone, the name is gone, and the only trace is a line in a log file that
rotates.

That is tolerable for a merge a person chose to do, having looked at
both records. It is not tolerable for one the system did on its own at
three in the morning while a student clicked a link in her email.

So the facts are written down BEFORE the merge: who was merged into
whom, what each was called, what the address was, and how much history
moved. If a join ever turns out to have been wrong - two people on one
address that the name check did not catch - this is what says which
bookings and which orders came from the contact that no longer exists.

It cannot undo the merge. Nothing can. It is the difference between
knowing a mistake happened and being able to put it right by hand.
"""
from odoo import models, fields


class FitnessDuplicateJoinLog(models.Model):
    _name = 'fitness.duplicate.join.log'
    _description = 'Automatic duplicate join, recorded'
    _order = 'create_date desc'
    _rec_name = 'email'

    email = fields.Char("Verified address", required=True, index=True)

    survivor_id = fields.Many2one(
        'res.partner', string="Kept", ondelete='set null',
        help="The contact that remains, and that her login now points at.")
    survivor_name = fields.Char(
        "Kept (name at the time)",
        help="Written down separately: a contact can be renamed later, "
             "and this has to still describe what happened.")

    merged_name = fields.Char("Merged away (name)", required=True)
    merged_ref = fields.Integer(
        "Merged away (id)",
        help="The contact no longer exists, so this is an id and not a "
             "link. It is what matches this record to rows elsewhere "
             "that still mention it.")

    bookings_moved = fields.Integer("Bookings moved", default=0)
    orders_moved = fields.Integer("Confirmed orders moved", default=0)

    user_login = fields.Char(
        "Account",
        help="The login that verified the address. Never a password or a "
             "token - only which account acted.")
