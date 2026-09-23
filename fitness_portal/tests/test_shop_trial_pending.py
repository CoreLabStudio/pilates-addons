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
