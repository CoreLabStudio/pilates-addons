# -*- coding: utf-8 -*-
"""Record a walk-in takes classes that started within 14 days - to the minute.

Independent QA recorded walk-ins on classes that had started 14 days and
2 hours, and 14 days and 20 hours, ago: both accepted, each spending a
free class. The dialog's class list hid them; a direct call went through,
because the check counted whole days and 14 days 20 hours is 14 of them.

Both sides of the edge, to the minute, on the dialog (what it offers) and
by direct call (what the button does). Clock pinned.
"""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 18, 0, 0)
CASES = [
    # (label, how long ago it started, accepted)
    ('13 d 23 h', timedelta(days=13, hours=23), True),
    ('14 d less 1 min', timedelta(days=14) - timedelta(minutes=1), True),
    ('14 d and 1 min', timedelta(days=14, minutes=1), False),
    ('14 d 2 h', timedelta(days=14, hours=2), False),
    ('14 d 20 h', timedelta(days=14, hours=20), False),
]


@tagged('post_install', '-at_install')
class TestWalkinWindowToTheMinute(TransactionCase):

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.search([('key', '=', 'fitness.record_attendance_days')]).unlink()
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'WM Manager', 'login': 'wm.manager@example.invalid',
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id])]})
        self.ctype = self.env['fitness.class.type'].create({
            'name': 'WM Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})

    def _class(self, ago):
        start = PINNED - ago
        return self.env['calendar.event'].sudo().create({
            'name': 'WM class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group'})

    def _wizard(self, event, student):
        return self.env['fitness.record.attendance.wizard'].with_user(
            self.manager).create({
                'calendar_event_id': event.id, 'student_id': student.id,
                'pay_with': 'free', 'reason': 'Walked in'})

    def test_the_dialog_and_the_button_agree_to_the_minute(self):
        for label, ago, accepted in CASES:
            with self.subTest(started=label):
                event = self._class(ago)
                student = self.env['res.partner'].create(
                    {'name': 'WM %s' % label})
                wiz = self._wizard(event, student)
                self.assertEqual(event in wiz.available_event_ids, accepted,
                                 'the dialog %s it' % (
                                     'hid' if accepted else 'offered'))
                if accepted:
                    wiz.action_record()
                else:
                    with self.assertRaises(UserError) as caught:
                        wiz.action_record()
                    self.assertIn('more than 14 days ago', str(caught.exception))
                self.assertEqual(self.env['fitness.booking'].sudo().search_count(
                    [('student_id', '=', student.id)]), 1 if accepted else 0)
