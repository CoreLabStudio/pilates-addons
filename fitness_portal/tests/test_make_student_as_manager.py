# -*- coding: utf-8 -*-
"""The make-student flow, run as a real manager rather than as admin.

The wizard shipped with tests and the click-through was never completed, so
what had actually been exercised was the method - called by a user who
happens to bypass every access rule. A studio manager is not an
administrator: she has no rights on res.users, and the whole point of the
button is that she does not need them.

Everything here runs with_user(manager) and invalidates the cache first, so
a value cached while admin was asking cannot answer for her.
"""

import logging

from odoo.tests import TransactionCase, tagged


_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestMakeStudentAsRealManager(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.student_group = cls.env.ref("fitness_core.group_fitness_student")
        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Real Desk Manager",
                "login": "real.desk@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })

    def setUp(self):
        super().setUp()
        # Nothing cached while admin was asking may answer for her.
        self.env.invalidate_all()

    def _as_manager(self):
        return self.env(user=self.manager)

    def _wizard_for(self, partner, **vals):
        env = self._as_manager()
        wiz = env["fitness.make.student.wizard"].with_context(
            active_id=partner.id, active_model="res.partner")
        defaults = wiz.default_get(["partner_id", "login", "password", "lang"])
        defaults.update(vals)
        defaults.setdefault("password", "real-manager-pw-1")
        return wiz.create(defaults)

    # ── the form she is looking at ──────────────────────────────────────────

    def test_the_button_is_in_the_form_she_is_served(self):
        arch = self.env["res.partner"].with_user(
            self.manager).get_view(view_type="form")["arch"]
        self.assertIn(
            "Make This Person a Student", arch,
            "the button is not in the form a manager is served - she cannot "
            "reach the wizard at all")
        self.assertIn(
            "fitness_is_student", arch,
            "the flag the button's visibility depends on is not in the view")

    def test_a_contact_with_a_login_and_no_email_can_still_be_saved(self):
        """What blocked Eli: Odoo marks the address required once a contact
        has a user, and hers was deliberately blank."""
        arch = self.env["res.partner"].with_user(
            self.manager).get_view(view_type="form")["arch"]
        self.assertNotIn(
            'required="user_ids"', arch,
            "the form still demands an address from an account holder, so a "
            "student without one cannot be edited")

    # ── (a) no email ────────────────────────────────────────────────────────

    def test_a_manager_can_make_a_no_email_contact_a_student(self):
        partner = self.env["res.partner"].create(
            {"name": "Manager Walkin", "email": False, "phone": "600222333"})
        wiz = self._wizard_for(partner)
        self.assertNotIn("@", wiz.login, "a username was not suggested")

        wiz.action_make_student()
        self.env.invalidate_all()

        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1)
        self.assertTrue(user, "no account was created")
        self.assertEqual(user.partner_id, partner,
                         "the account is attached to a different contact")
        self.assertFalse(user.email, "an address was invented for her")
        self.assertFalse(partner.email, "an address was written to her contact")
        self.assertIn(self.student_group, user.all_group_ids)
        self.assertTrue(partner.fitness_is_student)

    # ── (b) real email ──────────────────────────────────────────────────────

    def test_a_contact_with_an_email_keeps_it_as_her_login(self):
        partner = self.env["res.partner"].create({
            "name": "Manager Emailed", "email": "mgr.emailed@example.invalid"})
        wiz = self._wizard_for(partner)
        self.assertEqual(wiz.login, "mgr.emailed@example.invalid")

        wiz.action_make_student()
        self.env.invalidate_all()

        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1)
        self.assertEqual(user.email, "mgr.emailed@example.invalid")
        self.assertIn(self.student_group, user.all_group_ids)

    # ── (c) already has an account ──────────────────────────────────────────

    def test_an_existing_account_gains_the_role_not_a_second_user(self):
        """Eli's shape: portal access granted, student role never added."""
        existing = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Manager Haslogin",
                "login": "mgr.haslogin@example.invalid",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            })
        partner = existing.partner_id
        before = self.env["res.users"].sudo().search_count(
            [("partner_id", "=", partner.id)])

        self._wizard_for(partner).action_make_student()
        self.env.invalidate_all()

        after = self.env["res.users"].sudo().search_count(
            [("partner_id", "=", partner.id)])
        self.assertEqual(after, before, "a second account was created")
        self.assertIn(
            self.student_group, existing.all_group_ids,
            "her existing account did not gain the student role")

    # ── she then shows up where the studio looks ────────────────────────────

    def test_the_new_student_is_reachable_from_the_students_list(self):
        partner = self.env["res.partner"].create({"name": "Manager Listed"})
        self._wizard_for(partner).action_make_student()
        self.env.invalidate_all()

        listed = self.env["res.partner"].with_user(self.manager).search(
            [("fitness_is_student", "=", True)])
        self.assertIn(partner, listed, "she is not in the Students list")

        user = self.env["res.users"].sudo().search(
            [("partner_id", "=", partner.id)], limit=1)
        for meth in ("action_view_student_bookings",
                     "action_view_student_credits",
                     "action_view_student_packages",
                     "action_view_student_subscriptions"):
            self.assertTrue(
                getattr(user, meth)(),
                "%s does not resolve - the profile button is dead" % meth)

    def test_a_hands_off_student_can_be_sold_to_and_booked(self):
        """She will never open the app. Everything must be doable for her."""
        pack = self.env["product.template"].create({
            "name": "Handsoff Pack", "list_price": 100.0, "type": "service",
            "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group",
        })
        # The id, captured now. invalidate_all() below empties the cache, and
        # reading product_variant_ids off a record fetched before it raises
        # KeyError('product.product.name') rather than refetching.
        variant_id = pack.product_variant_ids[:1].id

        partner = self.env["res.partner"].create(
            {"name": "Manager Handsoff", "email": False})
        self._wizard_for(partner).action_make_student()
        self.env.invalidate_all()

        order = self.env["sale.order"].sudo().create({
            "partner_id": partner.id, "fitness_payment_method": "cash"})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": variant_id,
            "product_uom_qty": 1, "price_unit": 100.0,
        })
        order.action_confirm()
        self.env.invalidate_all()

        self.assertEqual(
            partner._fitness_credit_total(), 5,
            "a cash purchase for a hands-off student granted no credits")

    # ── the language it writes to her account ───────────────────────────────

    def test_it_never_proposes_a_language_the_database_does_not_have(self):
        """Odoo does not validate a language code on write, and the failure
        surfaces nowhere near this wizard: the next thing that reads her
        partner through env.lang - a sale order line building its own
        description, say - raises "Invalid language code" instead.

        Spanish is the right default for this studio and is installed on
        production. This is about the wizard not writing a code blind.
        """
        installed = set(
            self.env["res.lang"].sudo().search([]).mapped("code"))
        partner = self.env["res.partner"].create({"name": "Manager Lang"})
        wiz = self._wizard_for(partner)
        self.assertIn(
            wiz.lang, installed,
            "the wizard proposed %r, which this database does not have"
            % wiz.lang)

    def test_a_contacts_own_language_is_kept_when_it_is_installed(self):
        """The fallback must not flatten somebody who has a language set."""
        # A second language is activated rather than hoped for. A fresh
        # database ships en_US alone, so this skipped there and ran only
        # on the restore - and the studio works in three languages, so
        # the one test that protects a contact's own language has to run
        # everywhere.
        #
        # WHICH language is chosen by looking first. On the production
        # restore es_ES and ca_ES are both already installed, so
        # activating es_ES there would be a no-op dressed up as a step -
        # and an earlier draft of this asserted es_ES had NOT been
        # installed, which would simply have failed on that shape.
        import time as _time

        before = [code for code, _name in self.env["res.lang"].get_installed()]
        wanted = next((c for c in ("es_ES", "ca_ES") if c not in before), None)

        if wanted:
            started = _time.monotonic()
            self.env["res.lang"]._activate_lang(wanted)
            self.env.registry.clear_cache()
            _logger.info("[LANG] activating %s took %.2fs",
                         wanted, _time.monotonic() - started)
            installed = self.env["res.lang"].sudo().search([])
            self.assertGreaterEqual(
                len(installed), 2,
                "%s could not be activated, so the fallback cannot be "
                "tested against a second language" % wanted)
        else:
            # Everything this test might have turned on is already on.
            # Nothing is activated, nothing is asserted about activating,
            # and the test goes on to check what it is actually named
            # for - which is the point, not the setup.
            _logger.info("[LANG] es_ES and ca_ES already installed; "
                         "nothing activated")
            self.assertGreaterEqual(
                len(before), 2,
                "neither es_ES nor ca_ES is installable or installed")

        # The leak, asserted rather than hoped for. The res_lang row goes
        # with the transaction rollback; the ormcache behind
        # get_installed() does NOT - that is exactly how the
        # trial_offer_end parameter survived into whatever class ran
        # next. Comparing the list before and after would say nothing
        # here, because activating is the point when a language is
        # missing and a no-op when it is not. The invariant that holds
        # either way is that the cache AGREES WITH THE DATABASE.
        self._assert_cache_matches_database()
        self.addCleanup(self._assert_cache_matches_database)
        self.addCleanup(self.env.registry.clear_cache)

        # The thing this test is named for. The language to keep is one
        # that is NOT the fallback, asked of the wizard itself rather
        # than written in: this used to hardcode "anything but es_ES",
        # which only holds on a database where es_ES is the default.
        installed = self.env["res.lang"].sudo().search([])
        blank = self.env["res.partner"].create({"name": "Manager Nolang"})
        fallback = self._wizard_for(blank).lang
        other = installed.filtered(lambda l: l.code != fallback)[:1]
        self.assertTrue(
            other,
            "every installed language is the fallback %r, so there is no "
            "second language to keep" % fallback)
        partner = self.env["res.partner"].create(
            {"name": "Manager Haslang", "lang": other.code})
        self.assertEqual(
            self._wizard_for(partner).lang, other.code,
            "her own language was replaced by the default")

    def _assert_cache_matches_database(self):
        """get_installed() must not answer from a cache the rows no
        longer support."""
        self.env.registry.clear_cache()
        cached = {code for code, _name in self.env["res.lang"].get_installed()}
        self.env.cr.execute(
            "SELECT code FROM res_lang WHERE active = true")
        rows = {code for (code,) in self.env.cr.fetchall()}
        self.assertEqual(
            cached, rows,
            "get_installed() says %s but res_lang says %s - the language "
            "cache is out of step with the database and the next test "
            "class would inherit it" % (sorted(cached), sorted(rows)))
