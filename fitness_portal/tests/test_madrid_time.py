# -*- coding: utf-8 -*-
"""Every time a person sees is Madrid's, whatever the server, the browser or
the account says - and no stored datetime moves.

Spain changes clock on Sunday 25 October 2026: at 03:00 CEST it is 02:00
CET again, so 02:00-03:00 happens twice, and from then Madrid is UTC+1
instead of UTC+2. Every case below sits on one side of that or of a
midnight, where a UTC reading lands on the wrong day, month or hour:

  - the "class already started" refusal printed the UTC time and " UTC";
  - the history and credit pages filed a class by its UTC month;
  - the schedule's date filter grouped classes by UTC date;
  - the trial-scheduled bell showed the APPROVING STAFF's timezone;
  - the backend message thread used the viewer's timezone;
  - the dashboard used the company contact's timezone;
  - the class report dated a class by its UTC date;
  - the backend calendar filters cut at UTC midnight;
  - the instructor history filed a class by its UTC month.

Stored values are asserted unchanged wherever a case reads one.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, common, tagged

from odoo.addons.fitness_portal.controllers.portal import _madrid_month
from odoo.addons.fitness_teacher_swap.controllers.portal import (
    _madrid_month as _swap_month, _madrid_month_start_utc)

PW = 'madrid-time-Pw-26'
# UTC instants either side of the change and of midnights, with their Madrid time.
CEST_0230 = datetime(2026, 10, 25, 0, 30)    # 02:30 CEST, first 02:30
CET_0230 = datetime(2026, 10, 25, 1, 30)     # 02:30 CET, second 02:30
MON_0900 = datetime(2026, 10, 26, 8, 0)      # Monday 09:00 CET
SAT_0030 = datetime(2026, 10, 24, 22, 30)    # Sunday 25th 00:30 CEST (UTC: 24th)
NOV_0030 = datetime(2026, 10, 31, 23, 30)    # 1 Nov 00:30 CET (UTC: October)


class MadridFixture(TransactionCase):

    def _setup_studio(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        self.ctype = self.env['fitness.class.type'].create({
            'name': 'MT Reformer', 'classroom_type': 'reformer', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        self.pack = self.env['product.template'].create({
            'name': 'MT pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 10,
            'fitness_validity_days': 120, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})

    def _student(self, tag, lang='en_US', tz=False):
        u = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MT %s' % tag, 'login': 'mt.%s@example.invalid' % tag,
            'email': 'mt.%s@example.invalid' % tag, 'password': PW, 'lang': lang,
            'tz': tz, 'group_ids': [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('fitness_core.group_fitness_student').id])]})
        o = self.env['sale.order'].sudo().create({'partner_id': u.partner_id.id,
            'order_line': [(0, 0, {'product_id': self.pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 50.0})]})
        o.with_context(skip_fitness_notification=True).action_confirm()
        return u

    def _class(self, start, name='MT class'):
        return self.env['calendar.event'].sudo().create({
            'name': name, 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'is_fitness_class': True,
            'capacity': 8, 'session_type': 'group'})


@tagged('post_install', '-at_install')
class TestMadridTimeModels(MadridFixture):

    def setUp(self):
        super().setUp()
        self._setup_studio()

    def test_the_started_refusal_says_madrid_time_on_both_sides(self):
        student = self._student('started', tz='Asia/Calcutta')
        for start, local in ((CEST_0230, '2026-10-25 02:30'),
                             (CET_0230, '2026-10-25 02:30'),
                             (MON_0900, '2026-10-26 09:00')):
            with self.subTest(utc=start):
                event = self._class(start)
                with common.freeze_time(start + timedelta(minutes=5)):
                    with self.assertRaises(ValidationError) as caught:
                        self.env['fitness.booking'].sudo().create({
                            'student_id': student.partner_id.id,
                            'calendar_event_id': event.id})
                msg = str(caught.exception)
                self.assertIn(local, msg)
                self.assertNotIn('UTC', msg)
                self.assertEqual(event.start, start, 'a stored start moved')

    def test_the_madrid_month_of_a_stored_time(self):
        self.assertEqual(_madrid_month(NOV_0030), '2026-11')
        self.assertEqual(_madrid_month(NOV_0030 - timedelta(hours=1)), '2026-10')
        self.assertEqual(_madrid_month(date(2026, 10, 31)), '2026-10')
        self.assertEqual(_swap_month(NOV_0030), '2026-11')
        # Midnight on 1 November in Madrid is 23:00 UTC on the 31st (CET).
        self.assertEqual(_madrid_month_start_utc(2026, 11), datetime(2026, 10, 31, 23, 0))
        self.assertEqual(_madrid_month_start_utc(2026, 10), datetime(2026, 9, 30, 22, 0))

    def test_the_dashboard_is_on_madrid_whatever_the_company_says(self):
        self.env.company.partner_id.tz = 'Asia/Calcutta'
        tz = self.env['fitness.admin.dashboard']._studio_tz()
        self.assertEqual(tz.zone, 'Europe/Madrid')

    def test_the_class_report_dates_a_class_by_its_madrid_day(self):
        early = self._class(SAT_0030, 'MT early')
        monday = self._class(MON_0900, 'MT monday')
        self.env.flush_all()
        rows = {r['event_id'][0]: r['class_date'] for r in
                self.env['fitness.report.class'].search_read(
                    [('event_id', 'in', [early.id, monday.id])],
                    ['event_id', 'class_date'])}
        self.assertEqual(rows[early.id], date(2026, 10, 25))
        self.assertEqual(rows[monday.id], date(2026, 10, 26))

    def test_the_backend_filters_cut_at_madrid_midnight(self):
        arch = self.env.ref('fitness_core.view_calendar_event_search_fitness').arch \
            if self.env.ref('fitness_core.view_calendar_event_search_fitness',
                            raise_if_not_found=False) else ''
        if not arch:
            views = self.env['ir.ui.view'].search([
                ('model', '=', 'calendar.event'), ('type', '=', 'search'),
                ('arch_db', 'ilike', 'name="next_7"')])
            arch = ''.join(views.mapped('arch'))
        self.assertIn('name="today"', arch)
        for name in ('today', 'tomorrow', 'next_7', 'next_30', 'upcoming', 'past'):
            chunk = arch[arch.index('name="%s"' % name):][:600]
            self.assertIn('to_utc()', chunk.split('<filter')[0], name)

    def test_the_backend_message_thread_is_in_madrid(self):
        student = self._student('thread', tz='America/New_York')
        conv = self.env['fitness.studio.conversation'].sudo().create({
            'user_id': student.id, 'partner_id': student.partner_id.id})
        msg = self.env['fitness.studio.message'].sudo().create({
            'conversation_id': conv.id, 'body': 'hola'})
        self.env.cr.execute("UPDATE fitness_studio_message SET create_date=%s WHERE id=%s",
                            (CET_0230, msg.id))
        msg.invalidate_recordset()
        conv.invalidate_recordset()
        html = conv.with_user(self.env.ref('base.user_admin')).thread_html
        self.assertIn('02:30', html)


@tagged('post_install', '-at_install')
class TestMadridTimePortal(MadridFixture, HttpCase):

    def setUp(self):
        super().setUp()
        self._setup_studio()

    def _login(self, user):
        self.authenticate(user.login, PW)

    def test_the_schedule_files_classes_under_their_madrid_day(self):
        student = self._student('sched', tz='Asia/Calcutta')
        self._class(SAT_0030, 'MT sunday early')
        self._class(MON_0900, 'MT monday')
        with common.freeze_time(datetime(2026, 10, 24, 12, 0)):
            self._login(student)
            html = self.url_open('/my/studio').text
        self.assertIn('data-date="2026-10-25"', html)
        self.assertIn('data-date="2026-10-26"', html)
        self.assertNotIn('data-date="2026-10-24"', html,
                         'a 00:30 Madrid class filed under the UTC day before')

    def test_the_history_files_a_class_under_its_madrid_month(self):
        student = self._student('hist', tz=False)
        event = self._class(NOV_0030, 'MT first of november')
        booking = self.env['fitness.booking'].sudo().with_context(
            fitness_record_past_attendance=True, skip_fitness_notification=True)
        with common.freeze_time(NOV_0030 - timedelta(days=2)):
            b = booking.create({'student_id': student.partner_id.id,
                                'calendar_event_id': event.id})
        b.sudo().write({'state': 'attended'})
        with common.freeze_time(datetime(2026, 11, 3, 10, 0)):
            self._login(student)
            nov = self.url_open('/my/history?period=2026-11').text
            octo = self.url_open('/my/history?period=2026-10').text
        self.assertIn('MT first of november', nov)
        self.assertNotIn('MT first of november', octo)

    def test_the_trial_bell_is_in_madrid_not_the_approvers_zone(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.trial_offer_end', '2026-10-31')
        approver = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'MT Approver', 'login': 'mt.approver@example.invalid',
            'tz': 'Asia/Calcutta', 'lang': 'en_US',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('fitness_core.group_fitness_manager').id])]})
        student = self._student('trialbell')
        slot = self._class(MON_0900, 'MT trial slot')
        req = self.env['fitness.trial.request'].sudo().create({
            'name': student.name, 'email': student.email, 'phone': '600000002',
            'class_interest': 'reformer', 'partner_id': student.partner_id.id,
            'occurrence_id': slot.id})
        # The bell for a trial scheduled with no booking yet (approval books
        # her and the booking notifies instead). The web client sends the
        # approver's own timezone in the context.
        with common.freeze_time(datetime(2026, 10, 22, 10, 0)):
            req.with_user(approver).with_context(
                lang='en_US', tz='Asia/Calcutta')._notify_scheduled_in_app()
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', student.id),
            ('title', '=', 'Your trial class is confirmed')])
        self.assertEqual(len(bell), 1, 'no trial-scheduled bell')
        self.assertIn('MT trial slot on', bell.body)
        self.assertIn('09:00', bell.body, 'not in Madrid time: %s' % bell.body)
        self.assertNotIn('13:30', bell.body, "the approver's zone: %s" % bell.body)
