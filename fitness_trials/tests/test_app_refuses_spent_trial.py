# -*- coding: utf-8 -*-
"""In the app, a spent trial cannot be asked for again. On the website it can.

The studio's rule, and the two halves are deliberately different.

Inside the app she is signed in and the shop is one tap away, so handing her
a form that approval will refuse is a dead end dressed up as a next step.
She is sent to the trial she has NOT had, at its price - or, once both are
taken, to the Classes tab where the note already says what to do instead.

On the public website the form stays open. There is nothing to buy there,
the studio wants the request so it can ring her, and a public visitor is not
identified - checking a typed address would tell a stranger whether it has
an account here.

This reverses an earlier deliberate choice, which is why the test asserts
both directions: refusing everything would pass half of this and be a worse
bug than the one it replaced.
"""

from datetime import date, timedelta

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestAppRefusesSpentTrial(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        # The trial offer has a deadline, and it lapsed on 30 September
        # 2026. fitness_portal falls back to a hardcoded
        # TRIAL_OFFER_END_DEFAULT when the parameter is unset, so from
        # 1 October every test that needs a claimable trial began failing
        # on the calendar rather than on anything it asserts. Pinned here
        # so these keep testing what they name.
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        self.TR = self.env["fitness.trial.request"].sudo()
        trials = self.TR._all_trial_products()
        self.assertGreaterEqual(
            len(trials), 2, "this test needs both trial products")
        self.first_id, self.second_id = trials[0].id, trials[1].id
        self.password = "spent-app-pw-1"

    def _student(self, suffix):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Spent %s" % suffix,
                "login": "spent.%s@example.invalid" % suffix,
                "email": "spent.%s@example.invalid" % suffix,
                "password": self.password,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        user.partner_id.write({"email": user.login, "phone": "600111222"})
        return user

    def _take(self, partner, template_id, price=0.0):
        product = self.env["product.template"].sudo().browse(template_id)
        order = self.env["sale.order"].sudo().create(
            {"partner_id": partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": price,
        })
        order.action_confirm()
        self.env.flush_all()

    def _a_slot(self):
        """A real offered slot, from the endpoint the form itself calls.

        Skips days the studio is shut. _is_open_on() derives the open
        weekdays from the active schedules and /trial/submit enforces it,
        so a day that offers slots is not necessarily a day a request can
        be made on.

        Taking the first day with slots was enough until three leftover
        test classes turned up on a Saturday and a Sunday: this picked the
        Sunday, the submit refused it, and four tests failed on data
        rather than on anything they were asserting. Asking the same
        question the submit asks means it cannot happen again, whatever a
        database happens to be carrying.
        """
        trials = self.env["fitness.trial.request"].sudo()
        for n in range(2, 21):
            the_day = date.today() + timedelta(days=n)
            if not trials._is_open_on(the_day):
                continue
            day = the_day.isoformat()
            for period in ("morning", "evening"):
                res = self.url_open(
                    "/trial/classes?date=%s&period=%s" % (day, period))
                try:
                    slots = res.json().get("slots", [])
                except Exception:
                    slots = []
                if slots:
                    return day, period, slots[0]
        self.skipTest("no trial slots offered on this database")

    def _submit(self, user, source):
        day, period, slot = self._a_slot()
        page = self.url_open("/my/trial" if source == "app" else "/trial")
        import re
        tok = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        return self.url_open("/trial/submit", allow_redirects=False, data={
            "csrf_token": tok.group(1) if tok else "",
            "name": user.name,
            "email": user.login,
            "phone": "600111222",
            "class_interest": slot["discipline"],
            "class_type_id": str(slot["class_type_id"]),
            "occurrence_id": str(slot["id"]),
            "preferred_date": day,
            "preferred_period": period,
            "reformer_is_first_time": "yes",
            "source": source,
        })

    def _requests_for(self, user):
        return self.TR.search_count([("email", "=ilike", user.login)])

    # ── the app refuses ─────────────────────────────────────────────────────

    def test_a_spent_student_cannot_submit_in_the_app(self):
        user = self._student("app_spent")
        self._take(user.partner_id, self.first_id)
        self.authenticate(user.login, self.password)

        res = self._submit(user, "app")

        self.assertEqual(
            res.status_code, 303,
            "the app accepted a trial request from a student whose free "
            "trial is spent")
        self.assertEqual(
            self._requests_for(user), 0,
            "a request was written even though the route refused")

    def test_she_is_sent_to_the_trial_she_has_not_had(self):
        user = self._student("app_other")
        self._take(user.partner_id, self.first_id)
        self.authenticate(user.login, self.password)

        res = self._submit(user, "app")

        self.assertIn(
            "/my/packages/%d" % self.second_id,
            res.headers.get("Location") or "",
            "she was not sent to the discipline she has never tried, which "
            "is the one thing she can still buy")

    def test_with_both_taken_she_is_sent_somewhere_useful_not_nowhere(self):
        """The wrinkle: once both are taken there is nothing single to sell,
        which is the studio's rule and not an oversight."""
        user = self._student("app_both")
        self._take(user.partner_id, self.first_id)
        self._take(user.partner_id, self.second_id, price=18.0)
        self.authenticate(user.login, self.password)

        res = self._submit(user, "app")
        location = res.headers.get("Location") or ""

        self.assertEqual(res.status_code, 303)
        self.assertIn(
            "/my/packages", location,
            "she was left on a dead end with nothing to do next")
        self.assertNotIn(
            "/my/packages/%d" % self.first_id, location,
            "she was sent to a trial she has already had")
        self.assertNotIn(
            "/my/packages/%d" % self.second_id, location,
            "she was sent to a trial she has already had")

    # ── and still lets everyone else through ────────────────────────────────

    def test_an_unspent_student_can_still_submit_in_the_app(self):
        """Refusing everybody would pass every test above."""
        user = self._student("app_fresh")
        self.authenticate(user.login, self.password)

        res = self._submit(user, "app")

        self.assertNotEqual(
            res.status_code, 303,
            "a student entitled to a free trial was refused")
        self.assertEqual(
            self._requests_for(user), 1,
            "her request was not written")

    def test_the_website_still_takes_a_spent_students_request(self):
        """There is nothing to buy there and the studio wants to ring her."""
        user = self._student("web_spent")
        self._take(user.partner_id, self.first_id)

        res = self._submit(user, "website")

        self.assertNotEqual(
            res.status_code, 303,
            "the website refused a request the studio wants to receive")
        self.assertEqual(
            self._requests_for(user), 1,
            "the website dropped a spent-trial request instead of "
            "recording it for the studio to follow up")

    def test_the_studio_sees_it_was_already_used_with_a_way_to_contact_her(self):
        user = self._student("web_flagged")
        self._take(user.partner_id, self.first_id)
        self._submit(user, "website")

        req = self.TR.search([("email", "=ilike", user.login)], limit=1)
        self.assertTrue(req, "no request to look at")
        self.assertTrue(
            req.trial_already_used,
            "the studio has no way to see this person already had her trial")
        self.assertTrue(req.name, "no name to call her by")
        self.assertTrue(req.email, "no email on the request")
        self.assertTrue(
            req.phone,
            "no phone - the studio cannot ring her to ask for payment")
