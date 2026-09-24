# -*- coding: utf-8 -*-
"""Where a student lands after logging in to follow a link.

A deep link into the portal used to lose its destination: the post-login
safety net redirected every student to /my/home and threw the requested
destination away, so someone who clicked "Messages" in an email, was asked to
sign in, and signed in, arrived at Home with no explanation. The emails now
carry exactly such a link, so this is the difference between the link working
and the link lying.

Note on coverage: web_login itself cannot be exercised here. It begins

    if tools.config.get('test_enable'):
        return super().web_login(...)

so under --test-enable the override hands straight back to base Odoo and the
CoreLab behaviour is not the behaviour under test. The decision this file
pins is therefore the one piece that is testable in isolation - which
destinations are accepted - and the end-to-end journey was verified against a
running server instead, in all three states (logged out, logged in, no
account).
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoginDestination(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.fitness_portal.controllers.signup_override import (
            FitnessSignup)
        # The class, not the function: assigning a plain function to a class
        # attribute rebinds it as a method, so self would arrive as the first
        # argument. _mv_safe_dest is a staticmethod, so reaching it through
        # the class keeps it one.
        cls.Signup = FitnessSignup

    def safe(self, value):
        return self.Signup._mv_safe_dest(value)

    # ── the destinations that must be honoured ──────────────────────────────

    def test_a_portal_path_is_honoured(self):
        self.assertEqual(self.safe('/my/messages'), '/my/messages')

    def test_the_language_prefix_question_mark_is_still_honoured(self):
        """The frontend redirect leaves a bare '?' on the path, so the value
        that actually arrives is '/my/messages?'. It is not a generic
        destination and must not be mistaken for one."""
        self.assertEqual(self.safe('/my/messages?'), '/my/messages?')

    def test_a_deeper_path_with_a_query_is_honoured(self):
        self.assertEqual(self.safe('/my/classes/42?tab=roster'),
                         '/my/classes/42?tab=roster')

    # ── the destinations that must fall back to the portal home ─────────────

    def test_nothing_means_the_portal_home(self):
        for value in (None, '', False):
            self.assertIsNone(self.safe(value),
                              "%r should fall back, not be honoured" % (value,))

    def test_a_generic_destination_means_the_portal_home(self):
        """Odoo fills these in by default, so they express no preference. A
        student who asked for nothing in particular wants the portal, not the
        backend."""
        for value in ('/my', '/web', '/odoo', '/web#action='):
            self.assertIsNone(self.safe(value),
                              "%r is generic and should fall back" % value)

    def test_a_trailing_slash_does_not_smuggle_a_generic_past_the_check(self):
        self.assertIsNone(self.safe('/my/'),
                          "'/my/' is '/my' and should fall back")

    # ── the destinations that must be refused outright ──────────────────────

    def test_an_absolute_url_is_refused(self):
        """Otherwise the login page is an open redirect that arrives wearing
        the studio's own domain, which is exactly what makes it worth using
        against a student."""
        for value in ('https://evil.example/phish',
                      'http://evil.example',
                      'https://corelabstudio.es.evil.example/'):
            self.assertIsNone(self.safe(value),
                              "%r must not be followed" % value)

    def test_a_protocol_relative_url_is_refused(self):
        """//evil.example is an absolute URL wearing a relative disguise: it
        starts with '/' and passes a naive check."""
        self.assertIsNone(self.safe('//evil.example/phish'))
        self.assertIsNone(self.safe('//evil.example'))

    def test_a_non_string_is_refused(self):
        for value in (42, [], {}, object()):
            self.assertIsNone(self.safe(value))
