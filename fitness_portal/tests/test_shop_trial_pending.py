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
        """Claim the trial AND use the class it paid for.

        Confirming a zero-price trial order is only half of it. The trial
        products are credit-bearing packages (fitness_is_package, class_count
        1), so confirming one mints a real credit that lives until a booking
        spends it. A fixture that stops at action_confirm leaves the student
        holding a bookable credit, which is a different state from the one
        these tests mean by "spent".

        The credit is zeroed rather than booked against a real class: that is
        precisely what fitness_packages does on booking ("Deducted 1 credit
        from line N"), without needing a timetable to exist.
        """
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.barre.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 0.0,
            })],
        })
        order.action_confirm()
        order.order_line.write({"fitness_remaining_classes": 0})
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
            "already used your trial classes", before,
            "fixture is wrong: the note is showing before the trial is spent")

        self._spend_her_trial()

        after = self._page("/my/packages")
        self.assertIn(
            "already used your trial classes", after,
            "nothing explains why the single classes are gone")
        self.assertIn(
            "a membership or a class", after,
            "the note does not say where to go instead")

    def test_the_note_stays_off_the_other_tabs(self):
        """It explains the Classes tab, so it belongs only there."""
        self._spend_her_trial()
        packs = self._page("/my/packages?tab=packages")
        self.assertNotIn("already used your trial classes", packs)

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


@tagged("post_install", "-at_install")
class TestTheSpentTrialNoteMatchesWhatSheHolds(HttpCase):
    """The note over the emptied Classes tab must describe her situation.

    The first version asked one question - has this student ever taken a
    trial - and told everyone who had to "choose a pack, a membership or a
    class". On the production restore 14 of the 19 students with a spent
    trial were already holding live credit, so the larger group was being
    told to buy what they had already bought.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "spent-note-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Note Student",
            "login": "note.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        cls.barre = cls.env.ref("fitness_packages.product_barre_trial")

        cls.pack = cls.env["product.template"].create({
            "name": "Note Barre Pack 5",
            "list_price": 60.0,
            "sale_ok": True,
            "fitness_is_package": True,
            "fitness_class_count": 5,
            "fitness_validity_days": 90,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

    def _page(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages", timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")
        return res.text

    def _claim_her_trial(self):
        """Claim it and stop - she now holds one unbooked trial credit."""
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

    def _spend_her_trial(self):
        """Claim it and use the class, which is what leaves her holding
        nothing. See the note on the other class's copy of this."""
        order = self._claim_her_trial()
        order.order_line.write({"fitness_remaining_classes": 0})
        return order

    def _buy_the_pack(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 60.0,
            })],
        })
        order.action_confirm()
        return order

    BUY = "Choose a pack, a membership or a class"
    BOOK = "Book a class from your schedule"

    def test_a_student_holding_nothing_is_told_to_buy(self):
        """The original case, which must keep working."""
        self._spend_her_trial()
        page = self._page()
        self.assertIn(self.BUY, page,
                      "a student with no credit is no longer told where to go")
        self.assertNotIn(self.BOOK, page,
                         "she is told to book with credit she does not have")

    def test_a_student_holding_credit_is_sent_to_her_schedule(self):
        """The defect this class exists for: she already bought a pack, and
        the shop told her to buy a pack."""
        self._spend_her_trial()
        self._buy_the_pack()
        page = self._page()
        self.assertIn(self.BOOK, page,
                      "a student holding credit is not pointed at her schedule")
        self.assertNotIn(
            self.BUY, page,
            "she already holds a pack and is still being told to choose one")

    def test_the_note_names_the_credit_she_actually_has(self):
        """Not a bare count: the pool's own sentence, which is per-discipline
        and singular/plural correct in every language."""
        self._spend_her_trial()
        self._buy_the_pack()
        page = self._page()
        self.assertIn("5 barre credits available", page,
                      "the note does not say what she is holding")

    def test_one_credit_reads_as_singular(self):
        """res_partner went to real trouble so that 1 credit does not read
        "1 barre credits". Building the sentence here would undo it."""
        self._spend_her_trial()
        order = self._buy_the_pack()
        line = order.order_line[:1]
        line.write({"fitness_remaining_classes": 1})
        page = self._page()
        self.assertIn("1 barre credit available", page)
        self.assertNotIn("1 barre credits available", page)

    def test_the_note_is_absent_before_the_trial_is_spent(self):
        """None of the three apply to a student who still has her trial."""
        page = self._page()
        self.assertNotIn(self.BUY, page)
        self.assertNotIn(self.BOOK, page)

    def test_the_note_stays_off_the_other_tabs(self):
        """It explains the Classes tab, so it belongs only there."""
        self._spend_her_trial()
        self._buy_the_pack()
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        packs = self.url_open("/my/packages?tab=packages", timeout=30).text
        self.assertNotIn(self.BOOK, packs)
        self.assertNotIn(self.BUY, packs)

    # -- the membership branch, and the ordering trap inside it ------------

    def _exhausted_membership(self):
        """A running membership with no slots left in it.

        The state is reached through the allowance rather than by booking
        classes all week: fitness_weekly_used_this_week is computed from
        bookings and cannot be written, while fitness_weekly_class_allowance
        is related to the product. Both routes arrive at the same thing the
        note actually reads - a membership pool whose remaining is 0.
        """
        membership = self.env["product.template"].create({
            "name": "Note Barre Membership",
            "list_price": 95.0,
            "type": "service",
            "fitness_is_subscription_plan": True,
            "recurring_invoice": True,
            "fitness_class_type": "barre",
            "fitness_session_type": "group",
            "weekly_class_allowance": 0,
        })
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "plan_id": self.env.ref("sale_subscription.subscription_plan_month").id,
            "order_line": [(0, 0, {
                "product_id": membership.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 95.0,
            })],
        })
        order.action_confirm()
        self.assertEqual(order.subscription_state, "3_progress",
                         "fixture is not a running membership")
        return order

    # Deliberately apostrophe-free: QWeb escapes ' to &#39;, so the clause
    # with the apostrophe in it can never match the rendered HTML.
    WEEK = "Your membership opens new slots next week"

    def test_a_member_with_no_slots_left_is_told_that_and_not_to_buy(self):
        """Neither of the other two notes is true for her: she cannot book,
        and telling her to buy a membership is absurd - she has one."""
        self._spend_her_trial()
        self._exhausted_membership()
        page = self._page()
        self.assertIn(self.WEEK, page,
                      "a member out of slots is not told why she cannot book")
        self.assertNotIn(self.BUY, page,
                         "a paying member is being told to buy a membership")
        self.assertNotIn(self.BOOK, page,
                         "she is sent to book with nothing left to book with")

    def test_a_member_out_of_slots_who_holds_a_pack_is_sent_to_book(self):
        """The ordering trap, and the reason the note takes the first pool
        with anything left rather than pools[0].

        _fitness_credit_pools puts the membership's weekly slots first,
        because they reset soonest. Reading pools[0] blindly would tell a
        student she has no slots this week while a perfectly bookable pack
        sat directly underneath it.
        """
        self._spend_her_trial()
        self._exhausted_membership()
        self._buy_the_pack()
        page = self._page()
        self.assertIn(self.BOOK, page,
                      "her pack is bookable and the note ignored it")
        self.assertIn("5 barre credits available", page,
                      "the note does not name the pack she can actually use")
        self.assertNotIn(
            self.WEEK, page,
            "she was told this week is used up while holding a usable pack")

    # -- the state this work did not know existed until the note was built --

    def test_a_claimed_but_unbooked_trial_is_a_credit_to_spend(self):
        """She took the free trial and has not booked the class yet.

        The trial products are credit-bearing packages, so claiming one mints
        a real credit. She is not someone to sell to - she is someone with a
        class already paid for and nothing on her timetable. This state was
        found by the note rendering "1 barre credit available" for a fixture
        that believed it had left her holding nothing.
        """
        self._claim_her_trial()
        page = self._page()
        self.assertIn("1 barre credit available", page,
                      "her unbooked trial class is not named")
        self.assertIn(self.BOOK, page,
                      "she is not sent to book the class she already has")
        self.assertNotIn(
            self.BUY, page,
            "she is told to buy a class while holding an unbooked one")

    def test_using_the_class_is_what_turns_the_note_into_an_offer(self):
        """The same student, one booking later. This is the pair that shows
        the note tracks her real position rather than her history."""
        order = self._claim_her_trial()
        before = self._page()
        self.assertIn(self.BOOK, before)

        order.order_line.write({"fitness_remaining_classes": 0})

        after = self._page()
        self.assertIn(self.BUY, after,
                      "with the class used up she is still not offered anything")
        self.assertNotIn(self.BOOK, after,
                         "she is sent to book with no credit left")
