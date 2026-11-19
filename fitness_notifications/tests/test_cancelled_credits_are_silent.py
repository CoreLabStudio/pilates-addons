# -*- coding: utf-8 -*-
"""A cancelled order's credits never ring the student.

Cancelling an order leaves its pack line's counter as it was - "3 left,
valid until 2 Dec" - although nothing can spend those credits any more.
The expiry reminder read that counter regardless of the order's state, so
a student whose pack was cancelled (switched to another discipline, say)
was told her credits were about to expire. Because the reminder goes to a
student at most once a week, that notice also took the place of the real
one for a pack she still held.

The "no credits left" notice had the mirror fault: leftover credits on a
cancelled order kept her from being told her spendable ones had run out.

Both now count only orders whose credits can be spent - the same states
the payment engine accepts. A confirmed order behaves exactly as before.

Clock pinned per run, English throughout.
"""
from datetime import date, datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

EXPIRY = date(2026, 11, 20)


def _morning(day):
    # 08:00 UTC is 09:00 in Madrid in November: the same studio date
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=8)


@tagged('post_install', '-at_install')
class TestCancelledCreditsAreSilent(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness_notifications.send_credit_expiry', 'True')
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.types = {
            room: self.env['fitness.class.type'].create({
                'name': 'CC %s' % room, 'classroom_type': room,
                'duration': 50, 'level': 'all', 'session_type': 'group'})
            for room in ('reformer', 'barre')}
        self._seq = 0

    # ── fixtures ────────────────────────────────────────────────────────

    def _student(self):
        self._seq += 1
        return self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CC Student %d' % self._seq,
                'login': 'cc.%d@example.invalid' % self._seq,
                'email': 'cc.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            }).partner_id

    def _pack(self, partner, count, room, expiry, cancel=False):
        self._seq += 1
        tmpl = self.env['product.template'].create({
            'name': 'CC %s %d (%d)' % (room, count, self._seq),
            'list_price': 10.0 * count, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': count,
            'fitness_validity_days': 14, 'fitness_class_type': room,
            'fitness_session_type': 'group',
        })
        order = self.env['sale.order'].sudo().create({'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': room,
        })
        order.with_context(skip_fitness_notification=True).action_confirm()
        line = order.order_line[:1]
        line.fitness_validity_end_date = expiry
        if cancel:
            order.action_cancel()
            self.assertEqual(order.state, 'cancel', 'fixture: order not cancelled')
        self.assertEqual(line.fitness_remaining_classes, count,
                         'fixture: the line does not hold its credits')
        return line

    def _run_job(self, day):
        with common.freeze_time(_morning(day)):
            self.env['fitness.booking']._cron_check_credit_expiry()

    def _bells(self, partner, kind):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', 'in', partner.user_ids.ids),
            ('notification_type', '=', kind)])

    # ── the expiry reminder ─────────────────────────────────────────────

    def test_cancelled_pack_never_reminded_7_5_1_days_before(self):
        p = self._student()
        self._pack(p, 3, 'barre', EXPIRY, cancel=True)
        for days in (7, 5, 1):
            self._run_job(EXPIRY - timedelta(days=days))
            self.assertFalse(
                self._bells(p, 'credit_expiring'),
                'a cancelled order\'s credits were reminded %d day(s) before '
                'they expire' % days)

    def test_confirmed_pack_still_reminded_7_5_1_days_before(self):
        for days in (7, 5, 1):
            with self.subTest(days=days):
                p = self._student()
                self._pack(p, 3, 'barre', EXPIRY)
                self._run_job(EXPIRY - timedelta(days=days))
                bells = self._bells(p, 'credit_expiring')
                self.assertEqual(len(bells), 1,
                                 'no reminder %d day(s) before a live pack '
                                 'expires' % days)
                self.assertEqual(bells.title,
                                 '3 credit(s) expiring in %d day(s)' % days)

    def test_cancelled_and_live_pack_reminded_only_for_the_live_one(self):
        p = self._student()
        # The job walks the lines newest order first and reminds a student
        # once a week, so whichever pack it reaches first decides what she is
        # told. The cancelled order is the newer one here, as when a pack is
        # bought and then cancelled after another: the old job reached it
        # first and the live pack's reminder never came.
        self._pack(p, 2, 'reformer', EXPIRY + timedelta(days=2))
        self._pack(p, 3, 'barre', EXPIRY, cancel=True)
        self._run_job(EXPIRY - timedelta(days=5))
        bells = self._bells(p, 'credit_expiring')
        self.assertEqual(len(bells), 1, 'expected exactly one reminder')
        self.assertEqual(bells.title, '2 credit(s) expiring in 7 day(s)',
                         'the reminder was about the cancelled pack')

    # ── "no credits left" ───────────────────────────────────────────────

    def test_cancelled_credits_do_not_hide_no_credits_left(self):
        p = self._student()
        with common.freeze_time(_morning(EXPIRY - timedelta(days=10))):
            self._pack(p, 3, 'barre', EXPIRY, cancel=True)
            live = self._pack(p, 1, 'barre', EXPIRY)
            start = _morning(EXPIRY - timedelta(days=9)) + timedelta(hours=2)
            event = self.env['calendar.event'].sudo().create({
                'name': 'CC class', 'start': start,
                'stop': start + timedelta(minutes=50),
                'class_type_id': self.types['barre'].id,
                'is_fitness_class': True, 'capacity': 6,
                'session_type': 'group',
            })
            self.env['fitness.booking'].sudo().create({
                'student_id': p.id, 'calendar_event_id': event.id,
                'package_order_line_id': live.id,
            })
        self.assertEqual(live.fitness_remaining_classes, 0)
        self.assertEqual(len(self._bells(p, 'credit_zero')), 1,
                         'her last spendable credit went unannounced because '
                         'a cancelled order still showed credits')
