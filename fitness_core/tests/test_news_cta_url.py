# -*- coding: utf-8 -*-
"""A call-to-action link has to point where the studio meant.

Anyone writing a link types "corelabstudio.es". A browser reads a value with no
scheme as a path, so the button on the post rendered as a relative link and
landed on /my/news/<id>/corelabstudio.es - a 404. The admin form showed exactly
what had been typed and gave no hint anything was wrong, which is why it was
reported as the button "breaking" rather than as a bad link.

Normalisation happens on write and create, not only in the form's onchange, so
these go through the ORM the way an import or the shell would.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNewsCtaUrl(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.post = cls.env["fitness.news.post"].create({
            "title": "CTA URL test post",
            "publish_date": "2026-09-12",
        })

    def _url(self, raw):
        self.post.write({"cta_url": raw})
        return self.post.cta_url

    # ── the bug ──────────────────────────────────────────────────────────────
    def test_a_bare_domain_becomes_absolute(self):
        self.assertEqual(self._url("corelabstudio.es"),
                         "https://corelabstudio.es")

    def test_a_bare_domain_with_a_path_becomes_absolute(self):
        self.assertEqual(self._url("corelabstudio.es/precios"),
                         "https://corelabstudio.es/precios")

    def test_www_becomes_absolute(self):
        self.assertEqual(self._url("www.corelabstudio.es"),
                         "https://www.corelabstudio.es")

    def test_surrounding_whitespace_is_not_part_of_the_link(self):
        self.assertEqual(self._url("  corelabstudio.es  "),
                         "https://corelabstudio.es")

    # ── what must not be touched ─────────────────────────────────────────────
    def test_an_absolute_url_is_left_alone(self):
        self.assertEqual(self._url("https://corelabstudio.es"),
                         "https://corelabstudio.es")

    # ── a portal path typed without its leading slash ────────────────────────
    #
    # The likeliest link in a CoreLab post is to CoreLab. Writing "my/studio"
    # used to save as "https://my/studio" - a link to a host called "my", which
    # is a real top-level domain, so nothing downstream complained and the
    # button simply went nowhere.

    def test_a_portal_path_without_its_slash_becomes_internal(self):
        self.assertEqual(self._url("my/studio"), "/my/studio")

    def test_a_deeper_portal_path_without_its_slash(self):
        self.assertEqual(self._url("my/packages/12"), "/my/packages/12")

    def test_a_single_segment_becomes_internal(self):
        self.assertEqual(self._url("my"), "/my")

    def test_a_query_string_does_not_look_like_a_host(self):
        self.assertEqual(self._url("my/studio?view=schedule"),
                         "/my/studio?view=schedule")

    def test_a_dotted_host_is_still_treated_as_a_host(self):
        """The fix must not reach the case the rule was written for."""
        self.assertEqual(self._url("corelabstudio.es/precios"),
                         "https://corelabstudio.es/precios")

    def test_a_host_with_a_port_is_still_a_host(self):
        self.assertEqual(self._url("localhost:8069/my"),
                         "https://localhost:8069/my")

    def test_an_internal_path_stays_relative(self):
        """/my/packages is deliberately internal - making it absolute would
        send a student to the wrong host."""
        self.assertEqual(self._url("/my/packages"), "/my/packages")

    def test_mailto_and_tel_are_left_alone(self):
        self.assertEqual(self._url("mailto:info@corelabstudio.es"),
                         "mailto:info@corelabstudio.es")
        self.assertEqual(self._url("tel:+34600000000"), "tel:+34600000000")

    def test_an_uppercase_scheme_is_recognised(self):
        self.assertEqual(self._url("HTTPS://CORELABSTUDIO.ES"),
                         "HTTPS://CORELABSTUDIO.ES")

    def test_empty_stays_empty(self):
        self.post.write({"cta_url": "https://corelabstudio.es"})
        self.post.write({"cta_url": False})
        self.assertFalse(self.post.cta_url)

    # ── and on the way in, not only on update ────────────────────────────────
    def test_create_normalises_too(self):
        post = self.env["fitness.news.post"].create({
            "title": "Created with a bare domain",
            "publish_date": "2026-09-12",
            "cta_url": "corelabstudio.es",
        })
        self.assertEqual(post.cta_url, "https://corelabstudio.es")
