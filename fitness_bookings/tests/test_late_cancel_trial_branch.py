# -*- coding: utf-8 -*-
"""The free-trial case, as one named branch that can be flipped in a line.

A student cancelling her free-trial class INSIDE the window follows the
same rule as every other credit: nothing is returned, and the trial
stays counted as used. That is what the Terms say and what this build
does today - it is NOT a change, and nothing here switches it.

The owner is being asked whether she wants the trial treated as an
exception, because a trial is a first impression rather than a credit
somebody paid for, and losing it to a late cancellation may cost the
studio a customer rather than teach a lesson.

So the behaviour sits behind ONE name, TRIAL_IS_FORGIVEN, and both
answers are tested. Flipping it is a one-line change in
fitness_bookings/models/fitness_booking.py plus flipping the constant
here; nothing else moves, and the test that currently passes becomes the
test that fails, which is the point of writing both.
"""
from datetime import datetime, timedelta

import pytz

from odoo import fields
from odoo.tests import common, tagged

from odoo.addons.fitness_bookings.tests.test_student_may_cancel_late import (
    LateCancelFixture,
)

# What the studio does TODAY. The owner has not asked for the other one.
TRIAL_IS_FORGIVEN = False


@tagged("post_install", "-at_install")
class TestLateCancelOfATrial(LateCancelFixture):

    def _trial_product(self):
        product = self.env.ref(
            "fitness_packages.product_barre_trial", raise_if_not_found=False)
        if not product:
            self.skipTest("no barre trial product on this database")
        return product

    def _trial_class(self, hours):
        """A Barre class, because the Barre trial only covers Barre."""
        ct = self.env["fitness.class.type"].create({
            "name": "LC Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group"})
        start = fields.Datetime.now() + timedelta(hours=hours)
        return self.env["calendar.event"].sudo().create({
            "name": "LC Barre trial class", "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": ct.id, "is_fitness_class": True,
            "capacity": 7, "session_type": "group"})

    def _give_trial(self, user):
        """A confirmed zero-priced trial order: what 'used' means."""
        product = self._trial_product()
        order = self.env["sale.order"].sudo().create({
            "partner_id": user.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": product.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 0.0,
                "fitness_class_type": "barre"})]})
        order.action_confirm()
        return order.order_line[:1]

    def _trial_used(self, user):
        """The same question the shop and Home ask."""
        product = self._trial_product()
        lines = self.env["sale.order.line"].sudo().search([
            ("order_partner_id", "=", user.partner_id.id),
            ("product_id", "in", product.product_variant_ids.ids),
            ("order_id.state", "in", ("sale", "done"))])
        return any((l.price_total or 0.0) == 0.0 for l in lines)

    # == what happens today ==========================================
    def test_a_late_cancelled_trial_follows_the_same_rule(self):
        user = self._student("trial")
        line = self._give_trial(user)
        booking = self._book(user, self._trial_class(self.window - 2))
        self.assertEqual(self._left(line), 0, "the trial was not spent")

        booking.with_user(user).action_cancel()

        self.assertFalse(
            booking.credit_returned,
            "a late-cancelled trial reports its credit as returned")
        if TRIAL_IS_FORGIVEN:
            self.assertEqual(
                self._left(line), 1,
                "TRIAL_IS_FORGIVEN is on, so the trial should have come "
                "back and did not")
            self.assertFalse(
                self._trial_used(user),
                "the trial is still counted as used, so she will never be "
                "offered it again")
        else:
            self.assertEqual(
                self._left(line), 0,
                "the trial credit came back on a late cancellation, which "
                "is not what the Terms say")
            self.assertTrue(
                self._trial_used(user),
                "her trial stopped counting as used, so the shop would "
                "offer her a second free class")

    def test_outside_the_window_a_trial_comes_back_either_way(self):
        """Not part of the question: in good time, it returns."""
        user = self._student("trialgood")
        line = self._give_trial(user)
        booking = self._book(user, self._trial_class(self.window + 2))
        booking.with_user(user).action_cancel()
        self.assertTrue(booking.credit_returned)
        # A trial comes back as an ENTITLEMENT, not as a credit sitting on
        # the line: cancelling releases the claim so she may ask for it
        # again. Asserting a remaining count here would be asserting the
        # wrong mechanism, and would pass only by accident.
        self.assertFalse(
            self._trial_used(user),
            "cancelling a trial in good time left it counted as used, so "
            "she can never have the free class she never took")

    def test_the_switch_is_a_single_name(self):
        """If this file grows a second condition, the switch has leaked."""
        import odoo.addons.fitness_bookings.tests.test_late_cancel_trial_branch \
            as mod
        source = open(mod.__file__, encoding="utf-8").read()
        branches = [l for l in source.splitlines()
                    if l.strip().startswith("if TRIAL_IS_FORGIVEN")]
        self.assertEqual(
            len(branches), 1,
            "the trial behaviour is decided in %d places, so it can no "
            "longer be flipped in one line: %s" % (len(branches), branches))
        assigns = [l for l in source.splitlines()
                   if l.startswith("TRIAL_IS_FORGIVEN")]
        self.assertEqual(
            len(assigns), 1,
            "the switch is set in %d places" % len(assigns))
