# -*- coding: utf-8 -*-
"""Ask why, before cancelling a trial request.

A dialog rather than a status anybody can pick off the statusbar. Declining
sends the student an email and an app notification, and both read better -
and are far more use to the person reading them - when they say something
about why. Requiring it here is also a small brake on the click: cancelling
somebody's free class is worth a sentence.
"""
import logging

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FitnessTrialDeclineWizard(models.TransientModel):
    _name = 'fitness.trial.decline.wizard'
    _description = 'Cancel a Trial Request'

    request_id = fields.Many2one(
        'fitness.trial.request', string='Request', required=True,
        ondelete='cascade')
    student_name = fields.Char(related='request_id.name', readonly=True)
    reason = fields.Text(
        string='Reason', required=True,
        help="Goes to the student, in the email and in the app. Write it as "
             "you would say it to them.")

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        # required=True already stops an empty box, but not one holding a
        # space, and a notification whose body is a space helps nobody.
        if not reason:
            raise UserError(_("Please say why, so the student is told something."))
        if self.request_id.status == 'scheduled':
            raise UserError(_(
                "This request is already scheduled and the class is booked. "
                "Cancel the booking from the student's schedule first, so the "
                "seat is released and their credit comes back."))
        self.request_id._decline(reason)
        return {'type': 'ir.actions.act_window_close'}
