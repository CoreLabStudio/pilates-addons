# -*- coding: utf-8 -*-
"""Fill in the Student on trial requests that were taken before we filled it in.

WHAT WENT WRONG
---------------
_link_partner points a request at the contact whose email it carries, and it
runs on create and whenever the email changes. It was added with the admin
tooling; every request the studio took before that has never been through it.
So the Student column is blank on those rows even where the contact plainly
exists - the local copy has one, agos198@gmail.com from 6 August, sitting
blank next to a live contact with that exact address.

New requests link themselves correctly. Nothing backfills the old ones, which
is what this does.

WHAT IT DOES
------------
Calls the model's own _link_partner on every request that has no Student, so
the rule here and the rule at create time cannot drift apart. That rule is an
exact email match against a contact - =ilike, so case does not matter - and
the first match wins.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
  * It never overwrites a Student that is already set, including one an admin
    chose by hand. Only blank ones are considered, which also makes it safe to
    run again.
  * It creates no contacts. A request from somebody genuinely new stays blank,
    which is correct - approval is where a contact gets created, and it asks
    before it does.
  * It guesses nothing. No fuzzy matching on name, no matching on phone: a
    trial request pointed at the wrong student would book the wrong person
    into the class.
  * It changes no status, sends no mail, books nothing.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Trial = env['fitness.trial.request'].sudo()

    unlinked = Trial.search([('partner_id', '=', False)])
    if not unlinked:
        _logger.info("fitness_trials: no trial request is missing its Student.")
        return

    before = len(unlinked)
    unlinked._link_partner()

    linked = unlinked.filtered('partner_id')
    for rec in linked:
        _logger.info("fitness_trials: request %s (%s) linked to %s.",
                     rec.id, rec.email, rec.partner_id.display_name)

    _logger.info(
        "fitness_trials: %d of %d unlinked request(s) matched a contact; "
        "%d left blank because no contact carries that address.",
        len(linked), before, before - len(linked))
