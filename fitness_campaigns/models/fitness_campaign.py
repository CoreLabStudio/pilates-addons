# -*- coding: utf-8 -*-
"""Send a survey to a chosen group of students, and read what came back.

Yoleyva builds the survey in Odoo's own Surveys app, exactly as Odoo
intends. This module does not reimplement questions, answering or results -
it answers the two questions Odoo's own invite wizard does not: which
students, and deliver it to them the way this studio reaches students,
which is by email AND in the app.

Feedback today, a discount announcement in November, the same flow.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STUDENT_GROUP = 'fitness_core.group_fitness_student'


class FitnessCampaign(models.Model):
    _name = 'fitness.campaign'
    _description = 'Studio Campaign'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(required=True, tracking=True)
    survey_id = fields.Many2one(
        'survey.survey', string='Survey', required=True, tracking=True,
        help="Any survey built in the Surveys app.")

    audience = fields.Selection([
        ('everyone', 'Every student'),
        ('active_membership', 'Students on a running membership'),
        ('has_credits', 'Students holding class credits'),
        ('attended_recently', 'Students who came recently'),
    ], default='everyone', required=True, tracking=True)
    days = fields.Integer(
        string='In the last (days)', default=30,
        help="Only used by 'Students who came recently'.")

    # Not stored. It is a statement about who the students are today, and a
    # stored copy would be a second answer that can disagree with the first
    # the moment somebody's membership lapses.
    recipient_ids = fields.Many2many(
        'res.partner', compute='_compute_recipients', string='Recipients')
    recipient_count = fields.Integer(compute='_compute_recipients')

    sent_on = fields.Datetime(readonly=True, copy=False, tracking=True)
    sent_by = fields.Many2one('res.users', readonly=True, copy=False)
    sent_count = fields.Integer(readonly=True, copy=False, default=0)
    state = fields.Selection([
        ('draft', 'Draft'), ('sent', 'Sent')],
        compute='_compute_state', store=True)

    user_input_ids = fields.One2many(
        'survey.user_input', 'fitness_campaign_id', string='Answers',
        readonly=True)
    response_count = fields.Integer(compute='_compute_responses')
    response_rate = fields.Float(compute='_compute_responses')

    # ── who gets it ─────────────────────────────────────────────────────────

    @api.model
    def _student_partners(self):
        """Every partner who is actually a student.

        Keyed on the group rather than on "has bookings", because a student
        the studio has just signed up has no history yet and should still be
        asked. all_group_ids so a group that implies the student role counts
        too - the same question res_partner.fitness_is_student asks, and the
        two must not disagree about the same person.
        """
        group = self.env.ref(STUDENT_GROUP, raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        users = self.env['res.users'].sudo().search(
            [('all_group_ids', 'in', group.id)])
        return users.mapped('partner_id')

    @api.depends('audience', 'days')
    def _compute_recipients(self):
        for rec in self:
            students = rec._student_partners()
            if rec.audience == 'active_membership':
                orders = self.env['sale.order'].sudo().search([
                    ('partner_id', 'in', students.ids),
                    ('is_subscription', '=', True),
                    ('subscription_state', '=', '3_progress'),
                ])
                students = orders.mapped('partner_id')
            elif rec.audience == 'has_credits':
                students = students.filtered(
                    lambda p: (p._fitness_credit_total() or 0) > 0)
            elif rec.audience == 'attended_recently':
                since = fields.Datetime.now() - timedelta(
                    days=max(rec.days or 0, 1))
                bookings = self.env['fitness.booking'].sudo().search([
                    ('student_id', 'in', students.ids),
                    ('state', '=', 'attended'),
                    ('calendar_event_id.start', '>=', since),
                ])
                students = bookings.mapped('student_id')
            rec.recipient_ids = students
            rec.recipient_count = len(students)

    @api.depends('sent_on')
    def _compute_state(self):
        for rec in self:
            rec.state = 'sent' if rec.sent_on else 'draft'

    @api.depends('user_input_ids.state')
    def _compute_responses(self):
        # sudo: survey.user_input is Odoo's model with Odoo's ACLs, and a
        # studio manager is not a survey user. Without this the campaign
        # form raises AccessError on a number she is entitled to see - how
        # many of HER students answered. The ACL beside this grants her read
        # as well, so the Answers list works; this keeps the count from
        # depending on that being right.
        for rec in self:
            done = rec.sudo().user_input_ids.filtered(
                lambda u: u.state == 'done')
            rec.response_count = len(done)
            rec.response_rate = (
                100.0 * len(done) / rec.sent_count) if rec.sent_count else 0.0

    # ── sending ─────────────────────────────────────────────────────────────

    def _deliverable_lang(self, partner, user):
        """A language code Odoo will actually accept.

        env.lang does not fall back - it raises:

            # odoo/orm/environments.py
            raise UserError(f'Invalid language code: {lang}')

        A partner can easily carry a code that is not installed on this
        database: a language activated once and deactivated later, or a
        contact imported with one. Passing it through would kill action_send
        part way down the recipient list, leaving some students invited and
        the rest not, with sent_on unset so the campaign cannot even be
        retried cleanly - and the studio with no way to tell who got it.

        So the code is checked against what is actually installed, and
        anything else falls back rather than raising.
        """
        installed = {code for code, _name
                     in self.env['res.lang'].sudo().get_installed()}
        for candidate in (partner.lang, user.lang if user else None,
                          self.env.user.lang, 'en_US'):
            if candidate and candidate in installed:
                return candidate
        return self.env.user.lang or 'en_US'

    def _pin_survey_settings(self):
        """Make one answer per student actually mean one.

        Odoo only enforces an attempt limit when the survey is not public:

            # survey/models/survey_survey.py
            if (self.access_mode != 'public' or self.users_login_required) \\
                    and self.is_attempts_limited:
                return self._get_number_of_attempts_lefts(...) > 0
            return True

        So ticking "Limited number of attempts" on a public survey does
        nothing at all. Whatever Yoleyva happened to choose when building
        the questions, a campaign is invited-people-only with one attempt -
        set here rather than trusted, because the failure is silent and the
        symptom is a student answering twice.
        """
        self.ensure_one()
        self.survey_id.sudo().write({
            'access_mode': 'token',
            'is_attempts_limited': True,
            'attempts_limit': 1,
        })

    def action_send(self):
        self.ensure_one()
        if not self.env.user.has_group('fitness_core.group_fitness_manager') \
                and not self.env.user._is_admin():
            raise UserError(self.env._(
                "Only a studio manager can send a campaign."))
        if self.sent_on:
            raise UserError(self.env._(
                "%(name)s was already sent on %(when)s. Duplicate it to send "
                "again.", name=self.name, when=self.sent_on))
        if not self.recipient_ids:
            raise UserError(self.env._(
                "Nobody matches this audience, so there is nothing to send."))

        self._pin_survey_settings()
        template = self.env.ref(
            'fitness_campaigns.mail_template_campaign_invite',
            raise_if_not_found=False)
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        Notif = self.env['fitness.notification'].sudo()
        survey = self.survey_id.sudo()

        sent = 0
        for partner in self.recipient_ids:
            # One token per student, reused by BOTH channels. _create_answer
            # always creates - it never returns an existing one - so minting
            # per channel would hand her two, and two tokens is two
            # submissions however the attempt limit is set.
            answer = survey._create_answer(
                partner=partner, check_attempts=False)
            answer.fitness_campaign_id = self.id
            url = '%s%s' % (base_url, answer.get_start_url())

            user = partner.user_ids[:1]
            lang = self._deliverable_lang(partner, user)

            # In-app first. It is the channel every student has, including
            # the ones with no email address at all, and it must not be lost
            # if the mail server refuses the message.
            if user:
                env_lang = self.with_context(lang=lang).env
                Notif._create_for_user(
                    user.id, 'campaign',
                    env_lang._('%(studio)s would like your answer',
                               studio=self.env.company.name),
                    env_lang._('%(name)s - it takes a moment.',
                               name=self.survey_id.title or self.name),
                    action_url=url)

            # Then email, and only to somebody who has an address. A student
            # with none is supported on purpose - see
            # RUNBOOK-students-without-email.md - and queueing for her parks
            # a permanent failure in the outgoing queue.
            if template and partner.email:
                try:
                    template.with_context(lang=lang).sudo().send_mail(
                        answer.id, force_send=False,
                        email_values={'email_to': partner.email})
                except Exception:
                    _logger.exception(
                        "[CAMPAIGN] could not queue mail for %s",
                        partner.display_name)
            elif not partner.email:
                _logger.info(
                    "[CAMPAIGN] %s has no email address; the in-app "
                    "notification is her copy", partner.display_name)
            sent += 1

        self.write({
            'sent_on': fields.Datetime.now(),
            'sent_by': self.env.user.id,
            'sent_count': sent,
        })
        self.message_post(body=self.env._(
            "Sent to %(n)s student(s) by %(who)s.",
            n=sent, who=self.env.user.name))
        _logger.info("[CAMPAIGN] %s sent to %s student(s)", self.name, sent)
        return True

    # ── reading the answers ─────────────────────────────────────────────────

    def action_view_results(self):
        """Odoo's own results dashboard, filtered to this campaign's answers.

        Deliberately not a second results screen. Odoo's already charts every
        question type and handles the ones this studio has not used yet.
        """
        self.ensure_one()
        return self.survey_id.action_survey_user_input()

    def action_view_recipients(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Recipients'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.recipient_ids.ids)],
        }
