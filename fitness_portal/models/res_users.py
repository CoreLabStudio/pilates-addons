import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Every account is on the studio's clock.
    #
    # Odoo takes the timezone from the browser at signup, so an account picked
    # up whatever the person happened to be sitting in - and accounts created
    # by the studio inherited whoever created them. That is how one instructor
    # ended up on Asia/Calcutta.
    #
    # Class times in the portal and in the notification emails are printed on
    # the studio clock regardless, so this does not affect what a student sees.
    # What it does affect is the admin backend, which renders every datetime in
    # the viewing user's timezone - the Bookings list, Booked At, the calendar.
    # A studio in Madrid should read Madrid there too.
    #
    # Set on create only. An admin who deliberately changes it afterwards keeps
    # their change; this is a starting point, not a lock.
    STUDIO_TZ = 'Europe/Madrid'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('tz', self.STUDIO_TZ)
        return super().create(vals_list)

    # Admin-only. Deliberately not exposed anywhere in the portal: a student
    # seeing "VIP" on their own profile is a different product decision from
    # the studio tagging someone internally, and only the latter was asked for.
    fitness_is_vip = fields.Boolean(
        string='VIP',
        default=False,
        help="Internal flag for the studio. Filters the Students list; it "
             "grants no privileges and is never shown to the student.",
    )

    fitness_is_teacher = fields.Boolean(
        compute='_compute_fitness_is_teacher',
        string='Is Instructor',
    )

    @api.depends('all_group_ids')
    def _compute_fitness_is_teacher(self):
        teacher_group = self.env.ref(
            'fitness_core.group_fitness_teacher', raise_if_not_found=False
        )
        for user in self:
            user.fitness_is_teacher = bool(teacher_group and teacher_group in user.all_group_ids)

    # ── Verification ──────────────────────────────────────────────────────────

    fitness_is_verified_student = fields.Boolean(
        compute='_compute_fitness_is_verified_student',
        search='_search_fitness_is_verified_student',
        string='Has shop access',
        help="Whether this account holds the student group. Without it the "
             "shop and the checkout send the person back to /my, whatever "
             "else is set on them.",
    )

    @api.depends('all_group_ids')
    def _compute_fitness_is_verified_student(self):
        group = self.env.ref(
            'fitness_core.group_fitness_student', raise_if_not_found=False)
        for user in self:
            user.fitness_is_verified_student = bool(
                group and group in user.all_group_ids)

    def _search_fitness_is_verified_student(self, operator, value):
        """Make the field filterable, so the studio can list who is stuck.

        A non-stored compute cannot be searched without this, and the filter
        that matters - "Cannot open the shop" - is a search. Answered through
        the group's own all_user_ids, which already accounts for implied
        groups, rather than by re-deriving membership here.
        """
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError(
                "fitness_is_verified_student supports = and != against a "
                "boolean only")
        group = self.env.ref(
            'fitness_core.group_fitness_student', raise_if_not_found=False)
        if not group:
            # No group means nobody holds it, so "verified" matches nobody.
            return [('id', '=', False)] if (value == (operator == '=')) else []
        wanted = value if operator == '=' else not value
        return [('id', 'in' if wanted else 'not in',
                 group.sudo().all_user_ids.ids)]

    def action_fitness_verify_student(self):
        """Grant shop access by hand, exactly as clicking the email link does.

        /corelab/verify-email was the only place in the codebase that granted
        this group, and its link is a signed payload embedding the account's
        latest login time - so logging in, even only to check whether
        verification had worked, invalidated the student's own outstanding
        link. Somebody anxious enough to keep checking could never get in, and
        the studio had no way to help: two people needed a one-off script run
        against production on 2026-09-21.

        This is that script, made permanent and put where the studio already
        looks. It does the same two things the route does and nothing more:
        adds the group, then cancels the signup so a stale link left in an
        inbox cannot be replayed afterwards.

        Deliberately narrow:
          * managers only, re-checked here rather than trusted to the button's
            groups= attribute, which only hides it
          * portal accounts only, so a misclick on the wrong record can never
            hand an internal user a group
        """
        group = self.env.ref('fitness_core.group_fitness_student')
        if not (self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only studio managers can give a student access."))

        done, skipped = self.env['res.users'], self.env['res.users']
        for user in self:
            if not user.share:
                raise UserError(_(
                    "%(name)s is not a portal account. This is for students "
                    "who signed up and could not get through verification.",
                    name=user.name))
            if group in user.all_group_ids:
                skipped |= user
                continue
            user.sudo().write({'group_ids': [(4, group.id)]})
            user.partner_id.sudo().signup_cancel()
            done |= user
            _logger.info(
                "[VERIFY] %s given student access by %s from the back office",
                user.login, self.env.user.login)

        if not done:
            title, kind = _("No change"), 'warning'
            message = _("%(who)s already had access; nothing changed.",
                        who=', '.join(skipped.mapped('name')) or _("Nobody"))
        else:
            title, kind = _("Access granted"), 'success'
            message = _(
                "%(who)s can now open the shop and book. They log in with the "
                "password they already chose - no new email is sent.",
                who=', '.join(done.mapped('name')))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': kind,
                'sticky': False,
                # The form behind the dialog still shows the old state, and
                # the button would still be sitting there offering itself.
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    # ── Student actions ───────────────────────────────────────────────────────

    def action_view_student_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Bookings — {self.name}',
            'res_model': 'fitness.booking',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.partner_id.id)],
            'context': {'default_student_id': self.partner_id.id},
        }

    def action_view_student_packages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Packages — {self.name}',
            'res_model': 'sale.order.line',
            # list,form, so clicking a balance opens onto when it was bought,
            # how it was paid for and what has been spent from it. With list
            # alone a click did nothing and the studio had to go and find the
            # order instead.
            'view_mode': 'list,form',
            'views': [
                (self.env.ref(
                    'fitness_packages.view_fitness_package_line_list').id,
                 'list'),
                (self.env.ref(
                    'fitness_packages.view_fitness_package_line_form').id,
                 'form'),
            ],
            'domain': [
                ('order_id.partner_id', '=', self.partner_id.id),
                ('order_id.state', 'in', ('sale', 'done')),
                ('fitness_original_class_count', '>', 0),
            ],
        }

    def action_view_student_subscriptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Memberships — {self.name}',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', '=', self.partner_id.id),
                ('fitness_subscription_product_id', '!=', False),
            ],
        }

    def action_view_student_credits(self):
        """Open the package lines the student's balance is summed from.

        Note this lists package credits only. Subscription floating credits are
        counted in the balance but live on the sale.order, so they are reached
        through the Memberships button instead; one act_window cannot span both
        models.
        """
        self.ensure_one()
        lines = self.partner_id._fitness_active_package_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Credits — {self.name}',
            'res_model': 'sale.order.line',
            'view_mode': 'list',
            'views': [(self.env.ref('fitness_portal.view_fitness_credit_line_list').id, 'list')],
            'domain': [('id', 'in', lines.ids)],
        }

    def action_view_student_details(self):
        """What the student has told us about themselves, as they last saved it.

        These live on res.partner and the student edits them from the portal,
        so this opens that same record rather than a copy of it: whatever they
        change in the portal is what the studio sees here. Read-only for the
        same reason the rest of this form is - it is their answer, not ours.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Details — {self.name}',
            'res_model': 'res.users',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'fitness_portal.view_student_profile_details').id, 'form')],
            'target': 'new',
        }

    def action_view_student_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages — {self.name}',
            'res_model': 'fitness.studio.conversation',
            'view_mode': 'list,form',
            'domain': [('user_id', '=', self.id)],
        }

    # ── Teacher actions ───────────────────────────────────────────────────────

    def action_view_teacher_classes(self):
        """Classes this teacher is assigned to teach (calendar.event where user_id = self)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Classes — {self.name}',
            'res_model': 'calendar.event',
            'view_mode': 'list,calendar,form',
            'domain': [
                ('user_id', '=', self.id),
                ('is_fitness_class', '=', True),
            ],
            'context': {
                'default_user_id': self.id,
                'default_is_fitness_class': True,
            },
        }
