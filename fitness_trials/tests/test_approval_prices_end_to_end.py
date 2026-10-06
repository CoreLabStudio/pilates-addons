# -*- coding: utf-8 -*-
"""Approving a request produces the order the student was promised.

The helper tests beside this one check _price_date() in isolation, and
that turned out to prove very little: with the source reverted they all
failed on AttributeError, never on an assertion, so they would have
passed against any implementation that returned a date - including a
wrong one.

These go through action_approve_and_book() and look at the order that
comes out of it. Against the old code they fail on the number.

Everything is built here with explicit values: the promotion, the price,
the class, the request and its creation date. Nothing reads a seeded
product's promotion, because a seeded promotion expires and takes the
test with it.
"""
import io
from datetime import datetime, timedelta

import pytz

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
OFFER_END = '2026-10-16'
LIST_PRICE = 12.0


def _utc(local_naive):
    """A Madrid wall clock reading as the naive UTC the database holds."""
    return MADRID.localize(local_naive).astimezone(
        pytz.UTC).replace(tzinfo=None)


class _ApprovalCase(TransactionCase):
    """A studio, a trial product on promotion, a class, and a request."""

    #: when the studio is approving, Madrid wall clock
    PINNED = datetime(2026, 10, 17, 10, 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # es_ES BEFORE any fixture record exists.
        #
        # _resolve_partner() creates the contact with
        # `'lang': self.lang or 'es_ES'`, and fitness.trial.request.lang
        # itself defaults to es_ES. On a database without Spanish that
        # write raises "Invalid language code: es_ES" - which arrives
        # buried under a KeyError cache-miss on product.product.name and
        # reads like something else entirely. markupg01 has all three
        # languages; a --without-demo=all fresh_main has only en_US.
        #
        # Here, not in setUp, and not mid-test: activating a language
        # resets caches, and doing it after the fixtures are built leaves
        # the env holding keys for records created under the old one.
        cls.env['res.lang']._activate_lang('es_ES')
        cls.env.registry.clear_cache()

        # If the cache and the rows disagree, say so here rather than
        # letting it surface three frames deep in the ORM.
        cached = {code for code, _n in cls.env['res.lang'].get_installed()}
        cls.env.cr.execute("SELECT code FROM res_lang WHERE active = true")
        rows = {c for (c,) in cls.env.cr.fetchall()}
        assert cached == rows, (
            "get_installed() says %s but res_lang says %s - the language "
            "cache is stale before the fixtures are built"
            % (sorted(cached), sorted(rows)))
        assert 'es_ES' in rows, "es_ES did not activate"
        cls.addClassCleanup(cls.env.registry.clear_cache)

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(_utc(self.PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)

        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', OFFER_END)
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

        self.TR = self.env['fitness.trial.request'].sudo().with_context(
            lang='en_US')

        # The trial product, with its own promotion and its own price.
        self.product = self.TR._trial_product_for('barre') \
            if hasattr(self.TR, '_trial_product_for') else None
        if self.product is None:
            prods = self.TR._all_trial_products().filtered(
                lambda p: p.fitness_class_type == 'barre')
            if not prods:
                self.fail("no Barre trial product on this database")
            self.product = prods[0]
        self.product.sudo().write({
            'list_price': LIST_PRICE,
            'fitness_promo_mode': 'free',
            'fitness_promo_start': '2026-09-01',
            'fitness_promo_end': OFFER_END,
        })

        room = self.env['fitness.classroom'].sudo().create({
            'name': 'Approval Room', 'classroom_type': 'barre',
            'capacity': 8})
        self.ctype = self.env['fitness.class.type'].sudo().create({
            'name': 'Approval Barre', 'classroom_type': 'barre',
            'session_type': 'group', 'level': 'all',
            'classroom_id': room.id})
        start = _utc(self.PINNED + timedelta(days=3))
        self.slot = self.env['calendar.event'].sudo().create({
            'name': 'Approval class',
            'start': start,
            'stop': start + timedelta(minutes=55),
            'class_type_id': self.ctype.id,
            'is_fitness_class': True,
            'capacity': 8})

    def _request_made_at(self, local_naive, email=None):
        req = self.TR.create({
            'name': 'Approval Student',
            'email': email or 'approval.student@example.invalid',
            'phone': '600111222',
            'class_interest': 'barre',
            'occurrence_id': self.slot.id,
        })
        # create_date is readonly; the ORM will not take it.
        self.env.cr.execute(
            "UPDATE fitness_trial_request SET create_date = %s WHERE id = %s",
            (_utc(local_naive), req.id))
        req.invalidate_recordset(['create_date'])
        return req

    def _approve(self, req):
        # en_US explicitly. The contact approval creates inherits the
        # company default, and on a fresh database that language is not
        # installed - the order line's translated product name then
        # misses the cache and the ORM raises
        # KeyError: 'product.product.name' deep inside create(). It
        # passed on the restore, where all three languages are present,
        # and failed on fresh_main. A test that does not say which
        # language it is in is a test that depends on the database.
        req.with_context(lang='en_US').action_approve_and_book()
        partner = req._resolve_partner(create_if_missing=False)
        self.assertTrue(partner, "approval created no contact")
        orders = self.env['sale.order'].sudo().search(
            [('partner_id', '=', partner.id)], order='id desc')
        self.assertTrue(orders, "approval created no order at all")
        return partner, orders[0]


@tagged("post_install", "-at_install")
class TestAskedOnTheLastMinuteApprovedAfter(_ApprovalCase):
    """23:59 Madrid on the 16th, approved on the 17th.

    The case the rule exists for. She asked inside the offer; the delay
    in answering her is the studio's.
    """

    longMessage = False
    PINNED = datetime(2026, 10, 17, 10, 0)

    def test_the_order_is_free(self):
        req = self._request_made_at(datetime(2026, 10, 16, 23, 59))
        _partner, order = self._approve(req)
        self.assertAlmostEqual(
            order.amount_total, 0.0, places=2,
            msg="she asked at 23:59 on the last day and was charged %.2f"
                % order.amount_total)

    def test_the_order_is_confirmed(self):
        req = self._request_made_at(datetime(2026, 10, 16, 23, 59))
        _partner, order = self._approve(req)
        self.assertIn(order.state, ('sale', 'done'),
                      "the trial order was left unconfirmed, so nothing "
                      "was credited")

    def test_her_trial_is_now_spent(self):
        req = self._request_made_at(datetime(2026, 10, 16, 23, 59))
        partner, _order = self._approve(req)
        self.assertTrue(
            self.TR._trial_already_claimed(partner),
            "the free trial was given away without being marked as used, "
            "so she could claim another")


@tagged("post_install", "-at_install")
class TestAskedJustAfterItEnded(_ApprovalCase):
    """00:01 Madrid on the 17th.

    WHAT THE CODE DOES: it does not refuse. action_approve_and_book has
    no check on whether the offer is open - it books the slot and prices
    the line from _price_date(), which for this request is the 17th. So
    she is approved and charged the list price. That is asserted here
    rather than left to be discovered.
    """

    longMessage = False
    PINNED = datetime(2026, 10, 17, 10, 0)

    def test_approval_is_not_refused(self):
        req = self._request_made_at(datetime(2026, 10, 17, 0, 1))
        _partner, order = self._approve(req)
        self.assertTrue(order, "approval was refused outright")

    def test_she_is_charged_the_list_price(self):
        req = self._request_made_at(datetime(2026, 10, 17, 0, 1))
        _partner, order = self._approve(req)
        self.assertAlmostEqual(
            order.amount_total, LIST_PRICE, places=2,
            msg="a request made after the offer closed came to %.2f, not "
                "the list price" % order.amount_total)


@tagged("post_install", "-at_install")
class TestAskedAndApprovedWhileOpen(_ApprovalCase):
    """The ordinary case: both sides of it inside the offer."""

    longMessage = False
    PINNED = datetime(2026, 10, 15, 12, 0)

    def test_the_order_is_free(self):
        req = self._request_made_at(datetime(2026, 10, 15, 9, 0))
        _partner, order = self._approve(req)
        self.assertAlmostEqual(order.amount_total, 0.0, places=2)

    def test_the_order_is_confirmed(self):
        req = self._request_made_at(datetime(2026, 10, 15, 9, 0))
        _partner, order = self._approve(req)
        self.assertIn(order.state, ('sale', 'done'))


@tagged("post_install", "-at_install")
class TestWithTheRuleTurnedOff(_ApprovalCase):
    """The old behaviour, so turning the flag off is covered too."""

    longMessage = False
    PINNED = datetime(2026, 10, 17, 10, 0)

    def test_she_is_priced_by_the_approval_date(self):
        req = self._request_made_at(datetime(2026, 10, 16, 23, 59))
        self.patch(type(req), 'PRICE_FOLLOWS_REQUEST_DATE', False)
        _partner, order = self._approve(req)
        self.assertAlmostEqual(
            order.amount_total, LIST_PRICE, places=2,
            msg="with the rule off she should be priced on the day of "
                "approval, which is after the offer closed")
