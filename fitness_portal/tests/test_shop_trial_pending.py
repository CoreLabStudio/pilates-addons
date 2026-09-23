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


    # -- once the trial is gone, it is not offered at all ------------------

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

    def test_the_card_disappears_from_the_shop_once_the_trial_is_spent(self):
        """The studio's decision: a spent trial is not offered again in any
        form. These are also the only single-class products, so she is left
        with packs and memberships - taken knowingly."""
        before = self._page("/my/packages")
        self.assertIn(
            self.barre.name, before,
            "fixture is wrong: the Barre card is not on the shop to begin "
            "with, so its disappearance would prove nothing")

        self._spend_her_trial()

        after = self._page("/my/packages")
        self.assertNotIn(
            self.barre.name, after,
            "the Barre trial card is still on the shop after the trial was "
            "spent")

    def test_the_other_discipline_goes_too(self):
        """One entitlement covers both - "one per student, Barre or
        Reformer" - so spending it on Barre hides Reformer as well."""
        self._spend_her_trial()
        html = self._page("/my/packages")
        self.assertNotIn(self.reformer.name, html)

    def test_the_product_page_refuses_a_kept_link(self):
        """Hidden means hidden, including to somebody who typed the id."""
        self._spend_her_trial()
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages/%d" % self.barre.id, timeout=30)
        self.assertNotIn(
            self.barre.name, res.text,
            "the page behind the hidden card still sells her the class")

    def test_an_unused_trial_is_still_offered(self):
        """The hiding must not reach somebody whose trial is genuinely hers."""
        html = self._page("/my/packages")
        self.assertIn(self.barre.name, html)
        self.assertIn(self.reformer.name, html)

    def test_packs_are_untouched(self):
        """She keeps everything else - this removes one card, not the shop."""
        pack = self.env["product.template"].create({
            "name": "Hidden-test pack of 5", "list_price": 90.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 60,
            "fitness_class_type": "barre", "fitness_session_type": "group"})
        self._spend_her_trial()

        # ?tab=packages, because /my/packages lands on the CLASSES tab -
        # fitness_class_count <= 1 - and a five-class pack is not on it. The
        # first version of this test asked the wrong page and read an empty
        # tab as the filter having swallowed the packs.
        html = self._page("/my/packages?tab=packages")
        self.assertIn(
            pack.name, html,
            "hiding the trial took the ordinary packs with it")

    def test_she_is_told_why_the_classes_tab_changed(self):
        """A tab with the ordinary cards removed and nothing said is the same
        confusion this change set out to end. The note names the reason and
        where to go instead."""
        before = self._page("/my/packages")
        self.assertNotIn(
            "free class", before,
            "fixture is wrong: the note is showing before the trial is spent")

        self._spend_her_trial()

        after = self._page("/my/packages")
        self.assertIn(
            "free class", after,
            "nothing explains why the single classes are gone")
        self.assertIn(
            "pack or a membership", after,
            "the note does not say where to go instead")

    def test_the_note_stays_off_the_other_tabs(self):
        """It explains the Classes tab, so it belongs only there."""
        self._spend_her_trial()
        packs = self._page("/my/packages?tab=packages")
        self.assertNotIn("free class", packs)

    def test_the_classes_tab_is_what_empties(self):
        """Worth stating outright, because it is the studio's decision made
        visible: the trial products are single classes, so hiding them empties
        the tab a student lands on. She is left with the private and duo
        contact-only cards there, and must move to Packs or Memberships to buy
        anything."""
        self._spend_her_trial()
        classes = self._page("/my/packages")

        self.assertNotIn(self.barre.name, classes)
        self.assertNotIn(self.reformer.name, classes)
