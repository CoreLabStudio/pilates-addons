# -*- coding: utf-8 -*-
"""What the app says to a student who has asked for her trial and is waiting.

Three screens were reported by a student in that state. The shop's Classes
tab still told her "Your first class is free - choose Barre or Reformer"
beside a card that already said "Request sent". The Timetable told her "You
have no credit for these classes yet - tap any class to see the options",
and the only option she can act on is the form that refuses a second
request. The empty-state prompt on the schedule pointed her at that form.

All three asked _trial_request_open, which answers whether the trial is
still hers to ask for - true while her request sits in the studio's list.
Home was given the distinction when it was noticed on Home; nothing else
was. _trial_awaiting_studio is the question these three needed.

An approved trial is a different state and must stay one: approval mints a
real order, the trial products are packages, and the credit shows up like
any other - so these notes have to disappear the moment it lands.
"""
from odoo.tests import HttpCase, tagged

TRIAL_WITH_STUDIO = "Your trial request is with the studio"
# The banner's own last sentence, which nothing else on the page says.
PICK_ONE = "One trial per student"
NO_CREDIT = "You have no credit for these classes yet"


@tagged("post_install", "-at_install")
class TestWaitingOnTheStudio(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The trial offer lapsed on 30 September 2026 and the portal falls
        # back to a hardcoded default when the parameter is unset, so
        # without this every assertion here would pass or fail on the date
        # the suite happens to run rather than on what it names.
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        cls.password = "waiting-studio-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Waiting Student",
            "login": "waiting.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        # By xmlid: a guessed name would skip silently and prove nothing.
        cls.barre = cls.env.ref("fitness_packages.product_barre_trial")
        cls.reformer = cls.env.ref("fitness_packages.product_reformer_trial")
        # The banner is shown only when a trial is actually free for this
        # student, and "free" is a promotion window with mode 'free' - the
        # same mechanism the studio uses. A fresh install ships the trials
        # at 10 and 15 EUR with no promotion, so without this the banner is
        # never on the page and the test would pass while proving nothing.
        # Both ends are left open so the window cannot lapse under the suite.
        (cls.barre | cls.reformer).write({
            "fitness_promo_mode": "free",
            "fitness_promo_start": False,
            "fitness_promo_end": False,
        })

    # -- helpers -----------------------------------------------------
    def _page(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url, timeout=30)
        self.assertEqual(res.status_code, 200, res.text[:200])
        self.assertNotIn('name="password"', res.text, "session lost")
        return res.text

    def _ask_for_a_trial(self):
        return self.env["fitness.trial.request"].create({
            "name": "Waiting Student",
            "email": "waiting.student@example.invalid",
            "partner_id": self.partner.id,
            "class_interest": "barre",
            "status": "pending",
        })

    # == the shop banner =============================================
    def test_the_shop_stops_telling_her_to_choose_once_she_has(self):
        before = self._page("/my/packages")
        self.assertIn(
            PICK_ONE, before,
            "fixture is wrong: the shop is not offering a trial at all, so "
            "this proves nothing about what happens after she asks")

        self._ask_for_a_trial()

        after = self._page("/my/packages")
        self.assertIn(
            "Request sent", after,
            "fixture is wrong: the cards do not know about the request")
        self.assertNotIn(
            PICK_ONE, after,
            "the shop still tells her to choose a discipline beside a card "
            "that says her request has already been sent")

    def test_the_banner_comes_back_if_the_request_is_declined(self):
        """Declined is finished, and she may ask again."""
        req = self._ask_for_a_trial()
        # Through the wizard: the model refuses a bare status write, because
        # cancelling is something the student is told about.
        self.env["fitness.trial.decline.wizard"].create({
            "request_id": req.id, "reason": "No space that week.",
        }).action_confirm()

        self.assertIn(
            PICK_ONE, self._page("/my/packages"),
            "a declined request keeps the offer suppressed, so she is never "
            "told she can ask again")

    # == the timetable hint ==========================================
    def test_the_timetable_says_who_is_holding_her_request(self):
        before = self._page("/my/timetable")
        self.assertIn(
            NO_CREDIT, before,
            "fixture is wrong: this student already has credit, so the hint "
            "under test is not on the page")

        self._ask_for_a_trial()

        after = self._page("/my/timetable")
        self.assertIn(
            TRIAL_WITH_STUDIO, after,
            "the Timetable still says she has no credit and tells her to "
            "tap a class for options, while her request sits with the studio")
        self.assertNotIn(
            NO_CREDIT, after,
            "both notes are on the page at once, so she is told to go and "
            "buy something and to wait, in the same breath")

    def test_the_timetable_still_tells_an_ordinary_student_to_buy(self):
        """The other branch, which must not be swallowed by the new one."""
        self.assertIn(
            NO_CREDIT, self._page("/my/timetable"),
            "a student who has asked for nothing is no longer told how to "
            "get credit at all")

    # == the empty-state prompt ======================================
    def test_the_schedule_stops_sending_her_back_to_the_form(self):
        self._ask_for_a_trial()
        html = self._page("/my/studio")
        self.assertIn(
            TRIAL_WITH_STUDIO, html,
            "the schedule does not say her request is being dealt with")
        self.assertNotIn(
            "Request your free trial class", html,
            "the schedule still offers her the trial form, which refuses a "
            "second request from the same student")

    # == an approved trial is a different state ======================
    def test_an_approved_trial_is_not_a_student_still_waiting(self):
        """Approval mints a real credit, so every waiting note must go."""
        req = self._ask_for_a_trial()
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": self.barre.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 0.0,
            })],
        })
        order.action_confirm()
        # The request is closed by the same act in the product; closing it
        # here keeps the fixture honest about the state being described.
        req.status = "scheduled"

        html = self._page("/my/timetable")
        self.assertNotIn(
            TRIAL_WITH_STUDIO, html,
            "a student whose trial has been placed is still being told the "
            "studio is holding her request")
        self.assertNotIn(
            NO_CREDIT, html,
            "the trial credit approval minted is not being seen as credit")
