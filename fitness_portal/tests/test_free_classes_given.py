# -*- coding: utf-8 -*-
"""Free classes given: one list of everything the studio gave away.

A manager-only report over the orders (fitness.free.credit.report, a
Postgres view), so the history includes packs and memberships given
before it existed, and managers - who cannot read sale.order.line - get
this list and nothing more. Students and instructors get nothing, over
RPC as well as on screen; the Excel route reads rows back as the asker.

Months and "expired" are Madrid's: a gift given at 00:30 on 1 November in
Madrid is November, though UTC still says 31 October.

The report is a database view, so two things differ from an ordinary
model in these tests: writes are flushed before it is read, and its
"today" is the database's own clock in Madrid, which a frozen Python
clock cannot move - so the status and this-month assertions are made
against that date, read explicitly, and do not depend on the day the
suite runs.

Clock pinned, language explicit.
"""
import io
import json
from datetime import date, datetime, timedelta

import pytz

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
PINNED = datetime(2026, 11, 4, 9, 0, 0)       # Wednesday 4 Nov, 10:00 Madrid
PASSWORD = 'free-given-Pw-26'


def utc(y, m, d, hh, mm):
    return MADRID.localize(datetime(y, m, d, hh, mm)).astimezone(
        pytz.utc).replace(tzinfo=None)


@tagged('post_install', '-at_install')
class TestFreeClassesGiven(HttpCase):

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        Users = self.env['res.users'].with_context(no_reset_password=True)

        def user(login, groups):
            return Users.create({
                'name': login.split('@')[0], 'login': login,
                'password': PASSWORD, 'email': login, 'lang': 'en_US',
                'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])]})
        self.manager = user('fg.manager@example.invalid', [
            'base.group_user', 'fitness_core.group_fitness_manager'])
        self.teacher = user('fg.teacher@example.invalid', [
            'base.group_portal', 'fitness_core.group_fitness_teacher'])
        self.student = user('fg.student@example.invalid', [
            'base.group_portal', 'fitness_core.group_fitness_student'])
        self.Report = self.env['fitness.free.credit.report']
        self.free_reformer = self.env.ref(
            'fitness_packages.product_courtesy_reformer')
        self.pack = self.env['product.template'].create({
            'name': 'FG Pack 5', 'list_price': 60.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})

    # -- ways a credit comes to exist --------------------------------
    def _desk(self, product, method, reason=None, amount=0.0):
        vals = {'partner_id': self.student.partner_id.id,
                'product_id': product.id, 'payment_method': method}
        if reason:
            vals['reason'] = reason
        if amount:
            vals['amount_paid'] = amount
        self.env['fitness.desk.sale.wizard'].with_user(self.manager).create(
            vals).action_create_sale()
        return self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.partner_id.id)],
            order='id desc', limit=1).order_line[:1]

    def _old_gift(self, product, by):
        """A free order as the desk wrote it before the reason field."""
        order = self.env['sale.order'].with_user(by).sudo().create(
            {'partner_id': self.student.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 0.0,
            'fitness_class_type': product.fitness_class_type})
        order.write({'fitness_payment_method': 'free'})
        order.with_context(skip_fitness_notification=True).action_confirm()
        return order.order_line[:1]

    def _rows(self, **domain):
        self.env.flush_all()
        return self.Report.with_user(self.manager).search(
            [(k, '=', v) for k, v in domain.items()])

    def _all(self):
        self.env.flush_all()
        return self.Report.with_user(self.manager).search([])

    def _db_today(self):
        self.env.cr.execute(
            "SELECT (now() AT TIME ZONE 'Europe/Madrid')::date")
        return self.env.cr.fetchone()[0]

    # -- what is a row -----------------------------------------------
    def test_past_and_new_gifts_are_rows_and_nothing_else_is(self):
        past = self._old_gift(self.pack, self.manager)
        new = self._desk(self.free_reformer, 'free', reason='Brought a friend')
        self._desk(self.env.ref('fitness_packages.product_reformer_trial'),
                   'cash', amount=12.0)
        own = self._old_gift(self.pack, self.student)   # her own 0.00 claim
        new.sudo().fitness_validity_end_date = self._db_today() + timedelta(
            days=10)
        rows = self._all()
        self.assertEqual(set(rows.mapped('order_line_id').ids),
                         {past.id, new.id})
        self.assertNotIn(own, rows.mapped('order_line_id'))
        row = rows.filtered(lambda r: r.order_line_id == new)
        self.assertEqual((row.given_type, row.discipline, row.given_by,
                          row.reason, row.status, row.expires_on),
                         ('class', 'reformer', self.manager,
                          'Brought a friend', 'available',
                          self._db_today() + timedelta(days=10)))
        self.assertEqual(rows.filtered(
            lambda r: r.order_line_id == past).given_type, 'package')

    def test_statuses_and_the_class_it_paid_for(self):
        used = self._desk(self.free_reformer, 'free', reason='used')
        gone = self._desk(self.free_reformer, 'free', reason='expired')
        avail = self._desk(self.free_reformer, 'free', reason='available')
        ct = self.env['fitness.class.type'].create({
            'name': 'FG Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        start = PINNED + timedelta(days=1)
        event = self.env['calendar.event'].sudo().create({
            'name': 'FG class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': ct.id, 'is_fitness_class': True,
            'capacity': 6})
        self.env['fitness.booking'].sudo().create({
            'student_id': self.student.partner_id.id,
            'calendar_event_id': event.id,
            'package_order_line_id': used.id})
        # Dates set after booking, against the database's Madrid "today",
        # which is the clock the report reads.
        today = self._db_today()
        gone.sudo().fitness_validity_end_date = today - timedelta(days=1)
        avail.sudo().fitness_validity_end_date = today       # its last day
        used.sudo().fitness_validity_end_date = today + timedelta(days=5)
        status = {r.reason: (r.status, r.used_event_id)
                  for r in self._all()}
        self.assertEqual(status['used'], ('used', event))
        self.assertEqual(status['expired'][0], 'expired')
        self.assertEqual(status['available'][0], 'available')

    def test_the_month_is_madrids(self):
        with common.freeze_time(utc(2026, 11, 1, 0, 30)):
            line = self._desk(self.free_reformer, 'free', reason='midnight')
        self.assertEqual(line.order_id.date_order.date(), date(2026, 10, 31),
                         'fixture: UTC still says October')
        row = self._rows(order_line_id=line.id)
        self.assertEqual(row.given_month, '2026-11')
        this_month = self._db_today().strftime('%Y-%m')
        self.assertEqual(row.is_this_month, this_month == '2026-11')

    def test_group_by_and_pivot_read_for_a_manager(self):
        self._desk(self.free_reformer, 'free', reason='a')
        self._old_gift(self.pack, self.manager)
        self.env.flush_all()
        groups = self.Report.with_user(self.manager).read_group(
            [], ['credits_given:sum'], ['given_month', 'discipline'],
            lazy=False)
        got = {(g['given_month'], g['discipline']): g['credits_given']
               for g in groups}
        self.assertEqual(got, {('2026-11', 'reformer'): 1,
                               ('2026-11', 'barre'): 5})
        for field in ('given_by', 'student_id', 'status'):
            self.assertTrue(self.Report.with_user(self.manager).read_group(
                [], ['credits_given:sum'], [field]))

    def test_the_manager_still_reads_no_order_lines(self):
        self._desk(self.free_reformer, 'free', reason='a')
        with self.assertRaises(AccessError):
            self.env['sale.order.line'].with_user(self.manager).search([])

    # -- who may see it ----------------------------------------------
    def test_students_and_instructors_get_nothing(self):
        self._desk(self.free_reformer, 'free', reason='a')
        self.env.flush_all()
        for who in (self.student, self.teacher):
            with self.subTest(who=who.login):
                with self.assertRaises(AccessError):
                    self.Report.with_user(who).search([])
                self.authenticate(who.login, PASSWORD)
                out = self.url_open(
                    '/web/dataset/call_kw/fitness.free.credit.report/'
                    'search_read',
                    data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                                     'id': 1, 'params': {
                                         'model': 'fitness.free.credit.report',
                                         'method': 'search_read',
                                         'args': [[], ['reason']],
                                         'kwargs': {}}}),
                    headers={'Content-Type': 'application/json'}).json()
                self.assertIn('error', out)
                res = self.url_open('/fitness/free_credits/export.xlsx')
                self.assertEqual(res.status_code, 404)

    def test_the_export_is_exactly_the_filtered_rows(self):
        import openpyxl
        keep = self._desk(self.free_reformer, 'free', reason='keep me')
        self._desk(self.free_reformer, 'free', reason='filtered out')
        rows = self._rows(reason='keep me')
        self.assertEqual(rows.order_line_id, keep)
        self.authenticate(self.manager.login, PASSWORD)
        res = self.url_open('/fitness/free_credits/export.xlsx?ids=%s'
                            % ','.join(map(str, rows.ids)))
        self.assertEqual(res.status_code, 200)
        sheet = openpyxl.load_workbook(io.BytesIO(res.content)).active
        data = list(sheet.iter_rows(values_only=True))
        self.assertEqual(len(data), 2, 'header plus exactly the one row')
        header, row = data
        cells = dict(zip(header, row))
        self.assertEqual(cells['Reason'], 'keep me')
        self.assertEqual(cells['Student'], self.student.partner_id.name)
        # Madrid wall time: given at 10:00 Madrid on the pinned day.
        self.assertEqual(cells['Given'].hour, 10)

    def test_the_screens_speak_spanish_and_catalan(self):
        """View terms are bound per view; a msgid translated elsewhere
        does not translate here unless this view is in its references."""
        for code, label, term, title in (
                ('es_ES', 'Regalado por', 'Bonos gratuitos',
                 'Clases gratuitas regaladas'),
                ('ca_ES', 'Regalat per', 'Bons gratuïts',
                 'Classes gratuïtes regalades')):
            with self.subTest(lang=code):
                self.env['res.lang']._activate_and_install_lang(code)
                Report = self.Report.with_user(self.manager).with_context(
                    lang=code)
                self.assertEqual(
                    Report.fields_get(['given_by'])['given_by']['string'],
                    label)
                self.assertIn(term, Report.get_view(view_type='search')['arch'])
                menu = self.env.ref(
                    'fitness_portal.menu_fitness_free_credit').with_context(
                        lang=code)
                self.assertEqual(menu.name, title)
