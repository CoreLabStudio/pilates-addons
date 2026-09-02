# -*- coding: utf-8 -*-
"""Company details on the Terms.

The Terms named "Yoleyva Studio" as the provider, which is not the legal
entity, and carried no company details at all. The details block reads
res.company at render time so the studio filling Settings once updates the
Terms, the signup consent and its invoices together.

The pending-marker test is the important one: an address the studio has not
filled in must be visibly missing on the page. A block that silently renders
nothing looks finished and would ship that way.
"""
from odoo.tests import HttpCase, tagged

LEGAL_NAME = "Core Lab Studio, S.L."


@tagged("post_install", "-at_install")
class TestLegalDetails(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "legal-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Legal Test Student",
            "login": "legal.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.company = cls.env.company

    def _terms(self):
        # the HTTP request reads from the database, so pending ORM writes have
        # to be on disk first - without this the page renders the pre-write row
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/terms")
        self.assertEqual(res.status_code, 200, "terms did not load")
        self.assertNotIn('name="password"', res.text,
                         "got the login page, not the Terms")
        return res.text

    def test_terms_name_the_legal_entity(self):
        html = self._terms()
        self.assertIn(LEGAL_NAME, html, "Terms do not name the legal entity")
        self.assertNotIn("Yoleyva Studio", html,
                         "Terms still name a non-legal entity as the provider")

    def test_missing_address_is_visibly_flagged(self):
        """An unfilled address must be obvious, not silently absent."""
        self.company.write({"street": False, "street2": False,
                            "city": False, "zip": False, "vat": False})
        html = self._terms()
        self.assertIn("Domicilio social pendiente", html,
                      "a missing address rendered as nothing at all")
        self.assertIn("NIF pendiente", html, "a missing NIF rendered as nothing")

    def test_real_company_details_render_on_the_terms(self):
        """The studio's actual legal identity, as supplied by the client."""
        html = self._terms()
        self.assertIn("Carrer de la Noguera 39", html, "street missing")
        self.assertIn("08230", html, "postcode missing")
        self.assertIn("Matadepera", html, "town missing")
        self.assertIn("B88940010", html, "NIF missing")
        self.assertIn("info@corelabstudio.es", html, "contact email missing")
        self.assertIn(LEGAL_NAME, html, "legal name missing")

    def test_nif_is_shown_without_the_country_prefix(self):
        """Odoo stores ESB88940010; a Spanish legal notice shows the bare NIF."""
        html = self._terms()
        self.assertIn("NIF: B88940010", html,
                      "the ES prefix leaked into the displayed NIF")

    def test_details_appear_on_the_payment_step(self):
        """Who the customer is buying from, before they commit."""
        product = self.env["product.template"].sudo().search(
            [("fitness_is_package", "=", True), ("sale_ok", "=", True)], limit=1)
        self.assertTrue(product, "no purchasable package to open a checkout for")
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/packages/%d/checkout" % product.id)
        self.assertEqual(res.status_code, 200, "checkout did not load")
        self.assertNotIn('name="password"', res.text, "got the login page")
        self.assertIn("Carrer de la Noguera 39", res.text,
                      "seller identity missing from the payment step")
        self.assertIn("B88940010", res.text, "NIF missing from the payment step")

    def test_filled_address_replaces_the_marker(self):
        """Once Settings is filled the Terms pick it up with no code change."""
        self.company.write({
            "street": "Carrer d'Exemple 1",
            "city": "Matadepera",
            "zip": "08230",
            "vat": "ESB12345674",
        })
        html = self._terms()
        # QWeb escapes the apostrophe, so assert on the served form - a Catalan
        # street name containing one is exactly the realistic case here
        self.assertIn("Carrer d&#39;Exemple 1", html, "street not rendered")
        self.assertIn("Matadepera", html, "city not rendered")
        self.assertIn("08230", html, "postcode not rendered")
        # stored country-prefixed for Odoo/VIES, displayed bare for a
        # Spanish legal notice - see the NIF test above
        self.assertIn("B12345674", html, "NIF not rendered")
        self.assertNotIn("ESB12345674", html, "the ES prefix leaked into the page")
        self.assertNotIn("Domicilio social pendiente", html,
                         "pending marker survived a filled-in address")
        self.assertNotIn("NIF pendiente", html,
                         "pending marker survived a filled-in NIF")
