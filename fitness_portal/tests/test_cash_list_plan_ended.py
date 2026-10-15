# -*- coding: utf-8 -*-
"""The cash list says when a student's plan has already closed.

The daily job closes a membership the day after its last paid day. A
student who asked to pay cash and is waiting at the desk cannot book until
the request is approved, so the list shows the end next to the request.
"""
from datetime import date, timedelta

from odoo.tests import TransactionCase, common, tagged

from .test_close_ended_memberships import NEXT, CloseFixture, at


@tagged('post_install', '-at_install')
class TestCashListPlanEnded(CloseFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._close_fixture()

    def test_closed_plan_shows_its_end_on_the_request(self):
        student, old = self._paid_member('flagclosed')
        self._run(NEXT)
        req = self._cash_request(student, NEXT + timedelta(days=1))
        with common.freeze_time(at(NEXT + timedelta(days=1))):
            req.invalidate_recordset(['fitness_cash_plan_ended_on'])
            self.assertEqual(req.fitness_cash_plan_ended_on, old.end_date)

    def test_running_plan_and_new_student_show_nothing(self):
        student, _old = self._paid_member('flagrunning')
        req = self._cash_request(student, date(2026, 10, 11))
        newcomer = self._student('flagnew')
        first = self._cash_request(newcomer, date(2026, 10, 11))
        with common.freeze_time(at(date(2026, 10, 11))):
            (req | first).invalidate_recordset(['fitness_cash_plan_ended_on'])
            self.assertFalse(req.fitness_cash_plan_ended_on, 'a running plan flagged as ended')
            self.assertFalse(first.fitness_cash_plan_ended_on)

    def test_the_column_is_on_the_cash_list(self):
        arch = self.env.ref('fitness_portal.view_sale_order_tree_fitness_cash').arch_db
        self.assertIn('fitness_cash_plan_ended_on', arch)
