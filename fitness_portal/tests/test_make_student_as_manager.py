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

from odoo.tests import TransactionCase, tagged


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
