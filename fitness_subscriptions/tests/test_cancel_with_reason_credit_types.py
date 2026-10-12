# -*- coding: utf-8 -*-
"""Cancel with reason returns the credit the booking spent - or nothing.

For each kind of credit a booking can be paid with - a pack class, a
membership's weekly allowance, a make-up credit, the free trial and a
gift - a marked booking is cancelled with the "Return the credit" tick
on and off. Ticked: exactly one of that kind comes back, once. Unticked:
nothing moves. And the mark itself moved nothing before either.

Here rather than in fitness_bookings because this is the module that
sees every credit type at once.
"""
from datetime import timedelta

from odoo.tests import common, tagged

from .test_makeup_credit_returned import MakeUpCreditFixture

AFTER = timedelta(minutes=70)


@tagged('post_install', '-at_install')
class TestCancelWithReasonCreditTypes(MakeUpCreditFixture):

    def setUp(self):
        super().setUp()
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CR Manager', 'login': 'cr.manager@example.invalid',
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id,
                ])],
            })

    def _mark_then_cancel(self, booking, ticked):
        """No-show after the class, then Cancel with reason."""
        start = booking.calendar_event_id.start
        with common.freeze_time(start + AFTER):
            booking.with_user(self.manager).action_mark_no_show()
            yield 'marked'
            booking.with_user(self.manager)._cancel_marked_with_reason(
                'test', ticked)
        yield 'cancelled'

    def _run(self, booking, measure, ticked):
        """measure() before booking was taken; returns (marked, after)."""
        steps = self._mark_then_cancel(booking, ticked)
        next(steps)
        marked = measure()
        next(steps)
        return marked, measure()

    # -- a pack class ------------------------------------------------------
    def test_pack(self):
        for ticked in (True, False):
            with self.subTest(ticked=ticked):
                partner = self._student('pk%s' % ticked).partner_id
                line = self._packline(partner)
                full = line.fitness_remaining_classes
                booking = self._book(partner, self._class(30))
                left = lambda: line.fitness_remaining_classes  # noqa: E731
                marked, after = self._run(booking, left, ticked)
                self.assertEqual(marked, full - 1, 'the mark moved a credit')
                self.assertEqual(after, full if ticked else full - 1)
                self.assertEqual(booking.credit_returned, ticked)

    # -- a membership's weekly allowance ------------------------------------
    def test_allowance(self):
        for ticked in (True, False):
            with self.subTest(ticked=ticked):
                partner = self._student('al%s' % ticked).partner_id
                order = self._membership(partner)
                booking = self._book(partner, self._class(30))
                self.assertFalse(booking.fitness_used_floating_credit)
                self.assertEqual(booking.subscription_id, order)
                marked, after = self._run(
                    booking, lambda: self._floating(order), ticked)
                self.assertEqual(marked, 0)
                self.assertEqual(after, 1 if ticked else 0)

    # -- a make-up credit ---------------------------------------------------
    def test_makeup(self):
        for ticked in (True, False):
            with self.subTest(ticked=ticked):
                partner = self._student('mk%s' % ticked).partner_id
                order = self._membership(partner)
                self._spend_her_week(partner)
                order.sudo().fitness_floating_credits = 1
                booking = self._book(partner, self._class(32))
                self.assertTrue(booking.fitness_used_floating_credit,
                                'fixture: did not spend the make-up credit')
                marked, after = self._run(
                    booking, lambda: self._floating(order), ticked)
                self.assertEqual(marked, 0)
                self.assertEqual(after, 1 if ticked else 0)

    # -- the free trial -----------------------------------------------------
    def test_trial(self):
        trial = self.env.ref('fitness_packages.product_reformer_trial')
        for ticked in (True, False):
            with self.subTest(ticked=ticked):
                partner = self._student('tr%s' % ticked).partner_id
                order = self.env['sale.order'].sudo().create({
                    'partner_id': partner.id})
                self.env['sale.order.line'].sudo().create({
                    'order_id': order.id,
                    'product_id': trial.product_variant_ids[:1].id,
                    'product_uom_qty': 1, 'price_unit': 0.0,
                    'fitness_class_type': 'reformer'})
                order.action_confirm()
                line = order.order_line[:1]
                booking = self._book(partner, self._class(30),
                                     package_order_line_id=line.id)
                state = lambda: (order.state,  # noqa: E731
                                 line.fitness_remaining_classes)
                marked, after = self._run(booking, state, ticked)
                self.assertEqual(marked, ('sale', 0))
                # Ticked: the entitlement is handed back, as on any trial
                # cancellation - order cancelled, nothing left on the line.
                self.assertEqual(after, ('cancel', 0) if ticked
                                 else ('sale', 0))

    # -- a gift -------------------------------------------------------------
    def test_gift(self):
        gift = self.env.ref('fitness_packages.product_courtesy_reformer')
        for ticked in (True, False):
            with self.subTest(ticked=ticked):
                partner = self._student('gf%s' % ticked).partner_id
                order = self.env['sale.order'].sudo().create({
                    'partner_id': partner.id})
                self.env['sale.order.line'].sudo().create({
                    'order_id': order.id,
                    'product_id': gift.product_variant_ids[:1].id,
                    'product_uom_qty': 1, 'price_unit': 0.0,
                    'fitness_class_type': 'reformer'})
                order.action_confirm()
                line = order.order_line[:1]
                full = line.fitness_remaining_classes
                booking = self._book(partner, self._class(30),
                                     package_order_line_id=line.id)
                left = lambda: line.fitness_remaining_classes  # noqa: E731
                marked, after = self._run(booking, left, ticked)
                self.assertEqual(marked, full - 1)
                self.assertEqual(after, full if ticked else full - 1)
