# -*- coding: utf-8 -*-
"""Offer to say why, before cancelling a trial request.

A dialog rather than a status anybody can pick off a dropdown. Cancelling
sends the student an email and an app notification, and both read better - and
are far more use to the person reading them - when they say something about
why.

Offered, not demanded. Sometimes there is nothing useful to say, and a box
that insists on a sentence just collects full stops. Both messages already
read properly without one.
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
        string='Reason',
        help="Optional. Goes to the student, in the email and in the app. "
             "Write it as you would say it to them.")

    def action_confirm(self):
        self.ensure_one()
        # A box holding only spaces is the same as an empty one, and a
        # notification whose body is a space helps nobody.
        reason = (self.reason or '').strip()
        # A scheduled request is no longer refused here. It used to send the
        # studio away to cancel the booking first, which is exactly the second
        # step this dialog exists to save; _decline cancels the place itself,
        # releasing the seat and returning the credit.
        self.request_id._decline(reason)
        return {'type': 'ir.actions.act_window_close'}
