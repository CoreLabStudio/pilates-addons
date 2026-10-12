# -*- coding: utf-8 -*-
"""What she sees and what the engine spends are the same set of lines.

The defect was a disagreement, not a missing filter: the balance hid a
cancelled order's credits and the payment engine spent them. So these
tests assert the AGREEMENT, for every order state Odoo knows about - read
from the field's own selection, so a state added later is covered
without anybody remembering to add it here.

Consumers asked: the balance (_fitness_active_package_lines and the
fitness_credit_available figure built on it), the engine
(_select_payment_source), the in-memory form (fitness_spendable) and the
trial path (_existing_trial_credit).

Clock pinned, language explicit, every record built here.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
SPENDABLE = {'sale', 'done'}


@tagged('post_install', '-at_install')
class TestSpendableAgreement(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        self.class_type = self.env['fitness.class.type'].create({
            'name': 'AG Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group',
        })
        self.pack = self.env['product.template'].create({
            'name': 'AG Reformer pack 5', 'list_price': 50.0,
            'type': 'service', 'fitness_is_package': True,
            'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'reformer', 'fitness_session_type': 'group',
        })
        start = PINNED + timedelta(days=1, hours=2)
        self.event = self.env['calendar.event'].create({
            'name': 'AG class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.class_type.id, 'is_fitness_class': True,
        })
        self._seq = 0

    def _partner(self):
        self._seq += 1
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'AG Student %d' % self._seq,
                'login': 'ag.%d@example.invalid' % self._seq,
                'email': 'ag.%d@example.invalid' % self._seq,
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            })
        return user.partner_id

    def _line(self, partner, product=None):
        product = product or self.pack
        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            'fitness_class_type': product.fitness_class_type,
        })
        order.action_confirm()
        return order.order_line[:1]

    def _engine_pays(self, partner, line):
        try:
            src = self.env['fitness.booking'].sudo()._select_payment_source(
                partner.id, self.event)
        except UserError:
            return False
        return src == {'package_order_line_id': line.id}

    def _answers(self, partner, line):
        return {
            'balance': line in partner._fitness_active_package_lines(),
            'balance figure': partner.fitness_credit_available
                              == line.fitness_remaining_classes,
            'engine': self._engine_pays(partner, line),
            'in memory': bool(line.sudo().fitness_spendable()),
        }

    def _assert_agree(self, partner, line, expected, label):
        answers = self._answers(partner, line)
        self.assertEqual(
            set(answers.values()), {expected},
            '%s: consumers disagree or are wrong, expected %s, got %s'
            % (label, expected, answers))

    def test_every_order_state_agrees(self):
        states = [s for s, _label in
                  self.env['sale.order']._fields['state'].selection]
        self.assertIn('cancel', states)
        self.assertIn('sale', states)
        for state in states:
            with self.subTest(state=state):
                partner = self._partner()
                line = self._line(partner)
                line.order_id.sudo().write({'state': state})
                self.assertGreater(line.fitness_remaining_classes, 0)
                self._assert_agree(partner, line, state in SPENDABLE,
                                   'state %s' % state)

    def test_a_locked_order_agrees_and_still_spends(self):
        partner = self._partner()
        line = self._line(partner)
        line.order_id.action_lock()
        self.assertTrue(line.order_id.locked)
        self._assert_agree(partner, line, True, 'locked')

    def test_expired_and_last_day_agree(self):
        for end, expected in ((date(2026, 11, 3), False),
                              (date(2026, 11, 4), True),
                              (False, True)):
            with self.subTest(end=end):
                partner = self._partner()
                line = self._line(partner)
                line.sudo().fitness_validity_end_date = end
                self._assert_agree(partner, line, expected, 'end %s' % end)

    def test_nurias_case_balance_and_engine_name_the_pack(self):
        partner = self._partner()
        single_tmpl = self.pack.copy({
            'name': 'AG single', 'fitness_class_count': 1})
        single = self._line(partner, single_tmpl)
        single.sudo().fitness_validity_end_date = date(2026, 11, 10)
        single.order_id._action_cancel()
        pack = self._line(partner)
        self.assertEqual(partner._fitness_active_package_lines(), pack)
        self.assertEqual(partner.fitness_credit_available, 5)
        self.assertTrue(self._engine_pays(partner, pack))

    def test_the_trial_path_never_offers_a_cancelled_trial(self):
        trial = self.env.ref('fitness_packages.product_reformer_trial')
        Req = self.env['fitness.trial.request']
        partner = self._partner()
        line = self._line(partner, trial)
        self.assertEqual(Req._existing_trial_credit(partner, trial), line)
        line.order_id._action_cancel()
        self.assertFalse(Req._existing_trial_credit(partner, trial))
