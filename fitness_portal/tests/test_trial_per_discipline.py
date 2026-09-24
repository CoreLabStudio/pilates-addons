# -*- coding: utf-8 -*-
"""The other trial stays on sale; a taken one never comes back.

Marta Muñoz had her free Reformer trial, then wrote to the studio asking why
she could no longer book a trial class. She had never done Barre, the studio
sells it at 12 EUR, and the shop was quietly refusing to take her money - the
rule hid BOTH trial cards the moment the free entitlement was spent.

The rule now:

  one taken  -> the other is still buyable, at its own price
  both taken -> neither comes back; packs, memberships, privates and duos
                are what is left

The free entitlement is unchanged: one per student, either discipline. What
changed is what remains on sale afterwards.

Everything is asserted over HTTP, on the page the student actually receives.
An earlier version called _hidden_from_shop directly and every test errored -
it is a controller method and needs a live request. Product names and ids are
read into plain values in setUp, because authenticate() replaces the
environment and records fetched before it go stale underneath the test.
"""

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestTrialPerDiscipline(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        TR = self.env["fitness.trial.request"].sudo()
        trials = TR._all_trial_products()
        self.assertGreaterEqual(
            len(trials), 2, "this test needs both trial products to exist")

        self.password = "per-discipline-pw-1"
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Per Discipline Student",
                "login": "per.discipline@example.invalid",
                "email": "per.discipline@example.invalid",
                "password": self.password,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        user.partner_id.write({"email": user.login})
        self.login = user.login
        self.partner_id = user.partner_id.id

        # Plain values, captured now. Reading these off a recordset after
        # authenticate() raises a cache KeyError.
        self.first_id, self.first_name = trials[0].id, trials[0].name
        self.second_id, self.second_name = trials[1].id, trials[1].name
        self.second_price = trials[1].list_price

    # ── helpers ─────────────────────────────────────────────────────────────

    def _take(self, template_id, price):
        """Her having had this class - free at 0.00, or paid at its price."""
        product = self.env["product.template"].sudo().browse(template_id)
        order = self.env["sale.order"].sudo().create(
            {"partner_id": self.partner_id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": price,
        })
        order.action_confirm()
        self.env.flush_all()

    def _classes_tab(self):
        self.authenticate(self.login, self.password)
        page = self.url_open("/my/packages?tab=classes")
        self.assertEqual(page.status_code, 200)
        return page.text

    # ── nothing taken yet ───────────────────────────────────────────────────

    def test_a_new_student_is_offered_both(self):
        tab = self._classes_tab()
        for name in (self.first_name, self.second_name):
            self.assertIn(
                name, tab,
                "%s should be on the shop for a student who has had neither"
                % name)

    # ── one taken ───────────────────────────────────────────────────────────

    def test_taking_one_free_leaves_the_other_on_sale(self):
        """Marta's case, which is the whole reason for this change."""
        self._take(self.first_id, 0.0)
        tab = self._classes_tab()

        self.assertNotIn(
            self.first_name, tab,
            "the class she has already had is still being offered")
        self.assertIn(
            self.second_name, tab,
            "she has never done %s and the studio sells it - hiding it "
            "refuses her money" % self.second_name)

    def _lands_on(self, path):
        """Where the browser ends up, following redirects.

        Asserted on the destination rather than the status code, because the
        two differ by database and not by behaviour: a shape with the website
        module rewrites /my/... to /es/my/... and answers 303 where a shape
        without it answers 200. Both are the page opening. What tells a
        refusal apart is being sent somewhere else.
        """
        resp = self.url_open(path, allow_redirects=True)
        self.assertEqual(resp.status_code, 200, "%s did not resolve" % path)
        return resp.url

    def test_the_untaken_one_can_be_reached_and_bought(self):
        """Refusing everything would also pass the test above, and would be
        the bug this set out to fix."""
        self._take(self.first_id, 0.0)
        self.authenticate(self.login, self.password)

        self.assertIn(
            "/my/packages/%d" % self.second_id,
            self._lands_on("/my/packages/%d" % self.second_id),
            "she was sent away from the class she is entitled to buy")
        self.assertIn(
            "/my/packages/%d/checkout" % self.second_id,
            self._lands_on("/my/packages/%d/checkout" % self.second_id),
            "she can see it but cannot buy it")

    def test_the_free_entitlement_is_still_one_per_student(self):
        """Buying the second is not a second free trial. The entitlement
        rule is untouched; only what is on sale afterwards changed."""
        self._take(self.first_id, 0.0)
        partner = self.env["res.partner"].browse(self.partner_id)
        self.assertTrue(
            self.env["fitness.trial.request"].sudo()._trial_already_claimed(
                partner),
            "her free entitlement should be spent after one free trial")

    # ── both taken ──────────────────────────────────────────────────────────

    def test_once_both_are_taken_neither_comes_back(self):
        self._take(self.first_id, 0.0)
        self._take(self.second_id, self.second_price)
        tab = self._classes_tab()

        for name in (self.first_name, self.second_name):
            self.assertNotIn(name, tab, "%s is offered a third time" % name)

    def test_the_card_the_page_and_the_checkout_all_refuse(self):
        """A hidden card with a live checkout URL is not hidden. That was
        real: /checkout only asked _is_buyable, so a kept link would have
        sold a third trial."""
        self._take(self.first_id, 0.0)
        self._take(self.second_id, self.second_price)
        self.authenticate(self.login, self.password)

        for pid, name in ((self.first_id, self.first_name),
                          (self.second_id, self.second_name)):
            self.assertNotIn(
                "/my/packages/%d" % pid,
                self._lands_on("/my/packages/%d" % pid),
                "the product page for %s still opens" % name)
            self.assertNotIn(
                "/my/packages/%d/checkout" % pid,
                self._lands_on("/my/packages/%d/checkout" % pid),
                "checkout for %s still sells it - a kept link would buy a "
                "third trial" % name)
