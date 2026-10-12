# -*- coding: utf-8 -*-
"""One dialog, one confirmation - and no limit on dialogs.

Independent QA opened one desk dialog to give one free class, confirmed it
twice at the same moment and then once more: three orders, three free
classes. A cash sale through the same button was open to the same thing.

The owner gives free classes to family and friends as often as she likes,
so none of this counts per student, product or day: two dialogs for the
same student are two gifts and both go through. What is refused is the
SAME dialog doing its work a second time, sequentially or concurrently.
The same rule covers every other dialog that creates an order, a credit
or a booking.

Concurrency is tested with two real database connections racing for one
committed dialog row; the connection that loses is retried the way Odoo
retries a serialization failure, and must then be refused. End to end
over HTTP, the automated check fires two button presses at once.
"""
import threading
import time

import psycopg2.errors

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.fitness_subscriptions.tests.test_makeup_credit_returned \
    import MakeUpCreditFixture

ALREADY = {
    'en_US': 'already been confirmed',
    'es_ES': 'ya se ha confirmado',
    'ca_ES': "ja s'ha confirmat",
}


def _manager(env, login, lang='en_US'):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': 'Once Manager', 'login': login, 'email': login,
        'lang': lang, 'tz': 'Europe/Madrid',
        'group_ids': [(6, 0, [
            env.ref('base.group_user').id,
            env.ref('fitness_core.group_fitness_manager').id])],
    })


@tagged('post_install', '-at_install')
class TestDeskDialogOnce(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'once.desk@example.invalid')
        self.student = self.env['res.partner'].create({
            'name': "Once Núria O'Brien", 'email': 'once.st@example.invalid'})
        self.pack = self.env['product.template'].create({
            'name': 'Once pack of 5', 'list_price': 75.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})

    def _wizard(self, method, user=None, **extra):
        vals = {'partner_id': self.student.id, 'product_id': self.pack.id,
                'payment_method': method}
        vals.update({'amount_paid': 75.0} if method == 'cash'
                    else {'reason': 'Her sister'})
        vals.update(extra)
        return self.env['fitness.desk.sale.wizard'].with_user(
            user or self.manager).create(vals)

    def _orders(self):
        return self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.student.id)])

    def _credits(self):
        return sum(self.env['sale.order.line'].sudo().search(
            [('order_partner_id', '=', self.student.id)]
        ).mapped('fitness_remaining_classes'))

    def test_a_free_dialog_gives_once(self):
        wiz = self._wizard('free')
        wiz.action_create_sale()
        self.assertEqual((self._orders(), self._credits()), (1, 5))
        with self.assertRaises(UserError) as caught:
            wiz.action_create_sale()
        self.assertIn(ALREADY['en_US'], str(caught.exception))
        self.assertEqual((self._orders(), self._credits()), (1, 5),
                         'the second press gave the class again')

    def test_a_cash_dialog_sells_once(self):
        wiz = self._wizard('cash')
        wiz.action_create_sale()
        invoices = self.env['account.move'].sudo().search_count(
            [('partner_id', '=', self.student.id)])
        with self.assertRaises(UserError):
            wiz.action_create_sale()
        self.assertEqual((self._orders(), self._credits()), (1, 5))
        self.assertEqual(self.env['account.move'].sudo().search_count(
            [('partner_id', '=', self.student.id)]), invoices,
            'the second press invoiced her again')

    def test_two_dialogs_are_two_gifts(self):
        """No cap: per student, per product, per day."""
        for _ in range(2):
            self._wizard('free').action_create_sale()
        for _ in range(2):
            self._wizard('cash').action_create_sale()
        self.assertEqual((self._orders(), self._credits()), (4, 20))

    def test_a_refused_dialog_can_still_be_confirmed(self):
        """A refusal marks nothing: fix the dialog and press again."""
        wiz = self._wizard('free', reason='  ')
        with self.assertRaises(UserError):
            wiz.action_create_sale()
        wiz.reason = 'Her sister'
        wiz.action_create_sale()
        self.assertEqual(self._orders(), 1)

    def test_the_desk_is_told_exactly_what_was_done(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        said = {
            'en_US': ('Gave 1 Once pack of 5 to %s, order ',
                      'Sold 1 Once pack of 5 to %s for 75.00 '),
            'es_ES': ('Se ha regalado 1 Once pack of 5 a %s, pedido ',
                      'Se ha vendido 1 Once pack of 5 a %s por 75.00 '),
            'ca_ES': ("S'ha regalat 1 Once pack of 5 a %s, comanda ",
                      "S'ha venut 1 Once pack of 5 a %s per 75.00 "),
        }
        for lang, (gave, sold) in said.items():
            with self.subTest(lang=lang):
                for method, text in (('free', gave), ('cash', sold)):
                    wiz = self._wizard(method).with_context(lang=lang)
                    action = wiz.action_create_sale()
                    order = self.env['sale.order'].sudo().search(
                        [('partner_id', '=', self.student.id)],
                        order='id desc', limit=1)
                    message = action['params']['message']
                    self.assertIn(text % self.student.name, message)
                    self.assertIn(order.name, message)

    def test_a_sales_user_is_told_and_then_shown_the_order(self):
        owner = _manager(self.env, 'once.owner@example.invalid')
        owner.group_ids = [(4, self.env.ref(
            'sales_team.group_sale_manager').id)]
        action = self._wizard('free', user=owner).action_create_sale()
        self.assertIn('Gave 1', action['params']['message'])
        self.assertEqual(action['params']['next']['res_model'], 'sale.order')


@tagged('post_install', '-at_install')
class TestOtherDialogsOnce(MakeUpCreditFixture):
    """The sweep: every dialog that creates an order, a credit or a
    booking does its work once."""

    def setUp(self):
        super().setUp()
        self.manager = _manager(self.env, 'once.other@example.invalid')
        self.partner = self._student('once').partner_id
        self.line = self._packline(self.partner)

    def _left(self):
        self.line.invalidate_recordset()
        return self.line.fitness_remaining_classes

    def test_add_a_student_books_once(self):
        event = self._class(30)
        wiz = self.env['fitness.add.student.wizard'].with_user(
            self.manager).create({'event_id': event.id,
                                  'student_id': self.partner.id})
        wiz.action_add()
        with self.assertRaises(UserError) as caught:
            wiz.action_add()
        self.assertIn(ALREADY['en_US'], str(caught.exception))
        self.assertEqual(self.env['fitness.booking'].search_count(
            [('student_id', '=', self.partner.id)]), 1)
        self.assertEqual(self._left(), 4, 'a second credit was spent')

    def test_cancel_with_the_credit_back_returns_it_once(self):
        booking = self._book(self.partner, self._class(30))
        self.assertEqual(self._left(), 4)
        wiz = self.env['fitness.booking.cancel.wizard'].with_user(
            self.manager).create({'booking_id': booking.id,
                                  'restore_credit': True, 'reason': 'Ill'})
        wiz.action_confirm()
        self.assertEqual(self._left(), 5)
        with self.assertRaises(UserError) as caught:
            wiz.action_confirm()
        self.assertIn(ALREADY['en_US'], str(caught.exception))
        self.assertEqual(self._left(), 5, 'the credit came back twice')

    def test_move_or_cancel_only_happens_once(self):
        booking = self._book(self.partner, self._class(30))
        wiz = self.env['fitness.booking.reassign.wizard'].with_user(
            self.manager).create({'booking_id': booking.id})
        wiz.action_cancel_only()
        left = self._left()
        with self.assertRaises(UserError) as caught:
            wiz.action_cancel_only()
        self.assertIn(ALREADY['en_US'], str(caught.exception))
        self.assertEqual(self._left(), left)

    def test_a_gift_is_given_once_and_two_gifts_are_two(self):
        def gift():
            return self.env['fitness.gift.wizard'].with_user(
                self.manager).create({
                    'student_id': self.partner.id, 'gift_type': 'package',
                    'product_id': self.pack.id, 'reason': 'Her cousin'})

        def held():
            return self.env['sale.order.line'].sudo().search_count([
                ('order_partner_id', '=', self.partner.id),
                ('product_id.product_tmpl_id', '=', self.pack.id)])

        before = held()
        wiz = gift()
        wiz.action_give()
        with self.assertRaises(UserError) as caught:
            wiz.action_give()
        self.assertIn(ALREADY['en_US'], str(caught.exception))
        self.assertEqual(held(), before + 1)
        gift().action_give()
        self.assertEqual(held(), before + 2, 'a second gift was refused')

    def test_every_creating_dialog_carries_the_rule(self):
        for model in ('fitness.desk.sale.wizard', 'fitness.gift.wizard',
                      'fitness.add.student.wizard',
                      'fitness.booking.credit.back.wizard',
                      'fitness.booking.cancel.wizard',
                      'fitness.booking.reassign.wizard',
                      'fitness.class.bulk.cancel.wizard'):
            with self.subTest(model=model):
                self.assertIn('fitness_confirmed', self.env[model]._fields)


@tagged('post_install', '-at_install')
class TestConcurrentConfirm(TransactionCase):
    """Two connections, one committed dialog, both pressing at once.

    Raw connections, not registry.cursor(): inside a test that hands out
    test cursors sharing one connection behind a Python lock, so the
    second press would wait on that lock rather than on Postgres.
    """

    def _raw(self):
        return sql_db.db_connect(self.env.cr.dbname).cursor()

    def _commit_dialog(self, method):
        with self._raw() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            partner = env['res.partner'].create({'name': 'Once Race'})
            product = env['product.template'].create({
                'name': 'Once race pack', 'list_price': 75.0,
                'type': 'service', 'fitness_is_package': True,
                'fitness_class_count': 5, 'fitness_validity_days': 60,
                'fitness_class_type': 'barre',
                'fitness_session_type': 'group'})
            wiz = env['fitness.desk.sale.wizard'].create({
                'partner_id': partner.id, 'product_id': product.id,
                'payment_method': method, 'amount_paid': 75.0,
                'reason': 'race'})
            ids = (wiz.id, product.id, partner.id)
        self.addCleanup(self._drop, *ids)
        return ids[0]

    def _drop(self, wiz_id, product_id, partner_id):
        with self._raw() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['fitness.desk.sale.wizard'].browse(wiz_id).unlink()
            env['product.template'].browse(product_id).unlink()
            env['res.partner'].browse(partner_id).unlink()

    def _race(self, method):
        # The losing press is refused by Postgres on purpose, and
        # odoo.sql_db logs that refusal at ERROR. odoo.sh fails a build on
        # any ERROR line, so it is muted here, and only here.
        with mute_logger('odoo.sql_db'):
            return self._race_unmuted(method)

    def _race_unmuted(self, method):
        wiz_id = self._commit_dialog(method)
        model = 'fitness.desk.sale.wizard'
        first = self._raw()
        second = self._raw()
        outcome = {}
        try:
            api.Environment(first, SUPERUSER_ID, {})[model].browse(
                wiz_id)._fitness_confirm_once()

            # Built here, not in the thread: an Environment looks up the
            # registry under a lock the test runner is holding.
            again = api.Environment(second, SUPERUSER_ID, {})[model].browse(
                wiz_id)

            def press_again():
                try:
                    again._fitness_confirm_once()
                    outcome['first try'] = 'claimed'
                except psycopg2.errors.SerializationFailure:
                    outcome['first try'] = 'retry'
                except UserError:
                    outcome['first try'] = 'refused'

            racer = threading.Thread(target=press_again)
            racer.start()
            time.sleep(1.0)
            outcome['waited'] = racer.is_alive()
            first.commit()
            racer.join(30)
            if outcome.get('first try') == 'retry':
                # What Odoo does with a serialization failure: roll back
                # and run the request again from the start.
                second.rollback()
                env = api.Environment(second, SUPERUSER_ID, {})
                try:
                    env[model].browse(wiz_id)._fitness_confirm_once()
                    outcome['retry'] = 'claimed'
                except UserError:
                    outcome['retry'] = 'refused'
                second.rollback()
        finally:
            first.close()
            second.close()
        return outcome

    def test_two_presses_of_one_free_dialog(self):
        outcome = self._race('free')
        self.assertTrue(outcome['waited'],
                        'the second press did not wait for the first')
        self.assertNotIn('claimed', outcome.values(), outcome)
        self.assertIn('refused', outcome.values(), outcome)

    def test_two_presses_of_one_cash_dialog(self):
        outcome = self._race('cash')
        self.assertTrue(outcome['waited'], outcome)
        self.assertNotIn('claimed', outcome.values(), outcome)
        self.assertIn('refused', outcome.values(), outcome)
