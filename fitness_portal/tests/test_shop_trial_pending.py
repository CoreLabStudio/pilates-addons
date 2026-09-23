# -*- coding: utf-8 -*-
"""The shop closes both trial cards while any request is open.

The form behind these cards has always refused per student: /trial and
/trial/submit ask _open_request_for(partner) with no discipline. The cards
asked per discipline, so a student with a Reformer request still sitting with
the studio saw the Barre card offering "Book", opened the form, filled it in,
and was refused at submit. The card is the place to say it - a button that
leads somewhere the student cannot finish is worse than one that says why.
"""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestShopTrialPendingIsPerStudent(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "shop-trial-pending-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Shop Pending Student",
            "login": "shop.pending@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        # Resolved by xmlid rather than by name: these two are the only
        # products the portal treats as trials, and a guessed id would skip
        # silently and leave this test proving nothing.
        cls.barre = cls.env.ref("fitness_packages.product_barre_trial")
        cls.reformer = cls.env.ref("fitness_packages.product_reformer_trial")

    def _page(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")
        return res.text

    def _open_reformer_request(self):
        return self.env["fitness.trial.request"].create({
            "name": "Shop Pending Student",
            "email": "shop.pending@example.invalid",
            "partner_id": self.partner.id,
            "class_interest": "reformer",
            "status": "pending",
        })

    def test_the_barre_card_closes_while_a_reformer_request_is_open(self):
        """The failure a student actually walked into."""
        before = self._page("/my/packages/%d" % self.barre.id)
        self.assertNotIn(
            "Request sent", before,
            "fixture is wrong: Barre already says a request is pending")

        self._open_reformer_request()

        after = self._page("/my/packages/%d" % self.barre.id)
        self.assertIn(
            "Request sent", after,
            "the Barre card still offers the form while a Reformer request "
            "is open - the student fills it in and is refused at submit")

    def test_the_requested_discipline_closes_too(self):
        """The half that already worked, kept honest."""
        self._open_reformer_request()
        html = self._page("/my/packages/%d" % self.reformer.id)
        self.assertIn("Request sent", html)

    def test_the_grid_closes_both_cards(self):
        """The listing carries its own flags, so it is asked separately."""
        before = self._page("/my/packages")
        self.assertNotIn("Request sent", before, "fixture is wrong")

        self._open_reformer_request()

        after = self._page("/my/packages")
        self.assertIn(
            "Request sent", after,
            "the shop grid still offers a trial card while a request is open")

    def test_a_finished_request_reopens_both_cards(self):
        """Declined is finished, and she may ask again - in either room."""
        req = self._open_reformer_request()
        self.assertIn("Request sent", self._page(
            "/my/packages/%d" % self.barre.id))

        # Through the wizard, not by writing status: the model refuses a bare
        # write because cancelling is something the student is told about.
        self.env["fitness.trial.decline.wizard"].create({
            "request_id": req.id, "reason": "No space that week.",
        }).action_confirm()

        self.assertNotIn(
            "Request sent", self._page("/my/packages/%d" % self.barre.id),
            "a declined request must not keep the Barre card shut")

    def test_home_stops_offering_a_trial_while_one_is_open(self):
        """Home carried a second, quieter trial CTA that was gated on nothing.

        A student who had already asked saw "Book a Free Trial" directly above
        the line saying her request was with the studio. Asserted on the class
        rather than the label, because the label is translated and the page
        renders in the studio's language, not the reader's.
        """
        # Home only carries this CTA when a news post with a cta_url exists.
        # The studio's database has one; a fresh build does not, so the odoo.sh
        # main build failed on the guard below rather than on the gate. The
        # test owns the post now, so the precondition holds on any database.
        self.env["fitness.news.post"].create({
            "title": "Your first class is on us",
            "cta_url": "/my/studio",
            "cta_label": "Book a Free Trial",
            "sequence": 1,
        })

        before = self._page("/my/home")
        self.assertIn(
            "mv-home-cta--ghost", before,
            "fixture is wrong: Home is not offering the trial at all, so "
            "this test could pass without the gate working")

        self._open_reformer_request()

        after = self._page("/my/home")
        self.assertNotIn(
            "mv-home-cta--ghost", after,
            "Home still invites her to book a trial while her request is "
            "open, directly above the line saying it is with the studio")


    # -- once the trial is gone, it is an ordinary paid class --------------

    def _spend_her_trial(self):
        """A confirmed zero-price order for a trial product is what
        _trial_entitlement_used reads, so that is what this makes."""
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.barre.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 0.0,
            })],
        })
        order.action_confirm()
        return order

    def test_the_card_stops_calling_it_a_trial_once_it_is_spent(self):
        """It is the studio's only single-class product, priced 12.00, and
        it was still telling her it was a trial class. One student reported
        that as "I bought a credit to try a Barre class".

        Asserted on the English label, because url_open lands on /en/ and the
        page renders in English - the Spanish wording would be testing which
        language the test happens to run in, not the rename.
        """
        before = self._page("/my/packages/%d" % self.barre.id)
        self.assertIn(
            "Trial", before,
            "fixture is wrong: the card is not calling itself a trial to "
            "begin with, so the rename cannot be what this proves")
        self.assertNotIn("single class", before)

        self._spend_her_trial()

        after = self._page("/my/packages/%d" % self.barre.id)
        self.assertIn(
            "single class", after,
            "a student whose trial is spent is still shown a trial class")

    def test_an_unused_trial_is_still_called_a_trial(self):
        """The rename must not reach somebody whose trial is genuinely free."""
        html = self._page("/my/packages/%d" % self.barre.id)
        self.assertIn("Trial", html)
        self.assertNotIn("single class", html)

    def test_the_renamed_card_is_still_buyable_again_and_again(self):
        """A paid single class is an ordinary product.

        Only the FREE claim is once-per-student: claimed_ids is built from
        free_ids, so a product that is no longer free for her can never enter
        it. Buying it at 12.00 must therefore never hide it - she can come
        back for another class next week.
        """
        self._spend_her_trial()
        self._buy_it_at_full_price()

        html = self._page("/my/packages/%d" % self.barre.id)
        self.assertNotIn(
            "Already used", html,
            "a paid class was marked as used up; she cannot buy another")
        self.assertIn("single class", html)

    def _buy_it_at_full_price(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.barre.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 12.0,
            })],
        })
        order.action_confirm()
        return order

    def test_a_spent_trial_can_still_be_bought_while_a_request_is_open(self):
        """The f39797b interaction.

        The shop disables a trial card while a request is open, which is right
        while the trial is hers to claim. These products are also the only
        single-class products, so gating on the open request alone left a
        student who had already used her trial unable to buy a class at all.
        /trial/submit refuses a second OPEN request but not a student whose
        entitlement is spent, so she really can hold one.
        """
        self._spend_her_trial()
        self._open_reformer_request()

        html = self._page("/my/packages/%d" % self.barre.id)
        self.assertNotIn(
            "Request sent", html,
            "a spent trial is an ordinary paid class; an open request must "
            "not stop her buying one")
        self.assertNotIn("Solicitud enviada", html)

    def test_an_unspent_trial_is_still_gated_by_an_open_request(self):
        """The behaviour f39797b added must survive the fix above."""
        self._open_reformer_request()
        html = self._page("/my/packages/%d" % self.barre.id)
        self.assertTrue(
            "Request sent" in html or "Solicitud enviada" in html,
            "an open request no longer closes the trial card")
