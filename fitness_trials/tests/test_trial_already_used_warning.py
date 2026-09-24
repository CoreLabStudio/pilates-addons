# -*- coding: utf-8 -*-
"""Telling the studio a request cannot be approved, before they try.

The studio asked why the system accepted a second trial request from
somebody who had already taken her trial that morning. It accepted it on
purpose: once a trial is finished, asking again is a real ask - she may want
to buy a class. The entitlement is never at risk, because
action_approve_and_book refuses her.

What was missing is that nothing said so until the click. The existing
duplicate banner counts only OPEN requests, so a student whose trial is
spent and closed has no other open request and her row reads as ordinary.

These tests pin both halves: the warning appears for someone who has had
their trial, and stays silent for someone who has not - because a warning
that is always on is the same as no warning at all.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrialAlreadyUsedWarning(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.TR = cls.env["fitness.trial.request"].sudo()
        cls.trial_product = cls.TR._all_trial_products()[:1]

    def _partner(self, suffix):
        return self.env["res.partner"].create({
            "name": "Warned %s" % suffix,
            "email": "warned.%s@example.invalid" % suffix,
        })

    def _spend_her_trial(self, partner):
        """A trial is spent when a confirmed order for a trial product totals
        zero - that is the shape _trial_already_claimed looks for."""
        order = self.env["sale.order"].create({"partner_id": partner.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.trial_product.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": 0.0,
        })
        order.action_confirm()
        return order

    def _request(self, partner, status="pending", link=True):
        return self.TR.create({
            "name": partner.name,
            "email": partner.email,
            "class_interest": "reformer",
            "status": status,
            "lang": "es_ES",
            "partner_id": partner.id if link else False,
        })

    # ── the warning fires ───────────────────────────────────────────────────

    def test_a_student_who_has_had_her_trial_is_flagged(self):
        partner = self._partner("spent")
        self._spend_her_trial(partner)
        req = self._request(partner)
        self.env.invalidate_all()
        self.assertTrue(
            req.trial_already_used,
            "she has had her trial and the request does not say so")
        self.assertTrue(req.trial_used_warning, "no warning text")
        self.assertIn(partner.name, req.trial_used_warning,
                      "the warning does not name her")

    def test_it_works_on_an_unlinked_public_submission(self):
        """The case it exists for. A public request arrives with no
        partner_id and is matched by email at approval time - which is
        exactly when the studio finds out it cannot be approved."""
        partner = self._partner("unlinked")
        self._spend_her_trial(partner)
        req = self._request(partner, link=False)
        req.partner_id = False          # as a public submission arrives
        self.env.invalidate_all()
        self.assertTrue(
            req.trial_already_used,
            "an unattached request was not matched to her by email")

    # ── and stays quiet otherwise ───────────────────────────────────────────

    def test_a_first_time_requester_is_not_flagged(self):
        partner = self._partner("fresh")
        req = self._request(partner)
        self.env.invalidate_all()
        self.assertFalse(
            req.trial_already_used,
            "somebody who has never had a trial was warned about")
        self.assertFalse(req.trial_used_warning)

    def test_a_scheduled_request_is_not_flagged(self):
        """On a request the studio has already booked, the answer is
        trivially yes and the banner would be scolding them for a decision
        they made correctly."""
        partner = self._partner("done")
        self._spend_her_trial(partner)
        req = self._request(partner, status="scheduled")
        self.env.invalidate_all()
        self.assertFalse(
            req.trial_already_used,
            "a scheduled request should not carry the warning")

    def test_a_declined_request_is_not_flagged(self):
        partner = self._partner("declined")
        self._spend_her_trial(partner)
        req = self._request(partner, status="declined")
        self.env.invalidate_all()
        self.assertFalse(req.trial_already_used)

    # ── it agrees with the thing that actually refuses ──────────────────────

    def test_the_warning_matches_what_approval_will_do(self):
        """The warning is only worth anything if it predicts the refusal.
        If these two ever disagree, the studio is told one thing and the
        button does another."""
        spent = self._partner("agree_spent")
        self._spend_her_trial(spent)
        fresh = self._partner("agree_fresh")

        for partner, expected in ((spent, True), (fresh, False)):
            req = self._request(partner)
            self.env.invalidate_all()
            self.assertEqual(
                req.trial_already_used,
                self.TR._trial_already_claimed(partner),
                "the banner and the approval guard disagree about %s"
                % partner.name)
            self.assertEqual(req.trial_already_used, expected)
