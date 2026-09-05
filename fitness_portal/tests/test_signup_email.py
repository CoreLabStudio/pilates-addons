# -*- coding: utf-8 -*-
"""The signup address check.

Signup is verification-gated: the address typed on that form is the only way
an account is ever activated. So an address with a typo does not merely look
wrong - it strands the student on a "check your email" page waiting for a
message that was never deliverable. That is exactly what happened with
"priyajyothsna10", which has no @ at all: accepted, account created, and the
confirmation page reported it as sent.

These tests call the validator directly rather than driving /web/signup,
because web_auth_signup() short-circuits to the base auth_signup flow when
config['test_enable'] is set - which keeps core Odoo's signup tests behaving
as they expect, and takes every guard in that branch out of the picture along
with it. Calling the static method sidesteps the short-circuit and tests the
rule itself.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_portal.controllers.signup_override import FitnessSignup


@tagged("post_install", "-at_install")
class TestSignupEmailValidation(TransactionCase):

    longMessage = False

    def _check(self, cases, expected):
        for raw, why in cases:
            with self.subTest(address=raw):
                self.assertEqual(
                    FitnessSignup._mv_is_valid_email(raw), expected,
                    "%r should be %s: %s"
                    % (raw, "accepted" if expected else "rejected", why))

    def test_rejects_addresses_a_link_could_never_reach(self):
        self._check([
            ("priyajyothsna10", "the reported case - no @ at all"),
            ("priyajyothsna10@", "no domain to deliver to"),
            ("@gmail.com", "no mailbox to deliver to"),
            ("two@@at.com", "two @ signs is not an address"),
            ("trailing.dot@example.", "domain ends on a dot"),
            ("no-at-sign.example.com", "reads like a domain, is not an address"),
        ], False)

    def test_rejects_empty_and_whitespace(self):
        self._check([
            ("", "nothing typed"),
            ("   ", "spaces only"),
            (None, "field absent from the POST entirely"),
        ], False)

    def test_rejects_rather_than_silently_correcting(self):
        """email_normalize salvages an address out of surrounding text.

        Left to itself it turns "a b@c.com" into "b@c.com" - a silent
        correction to an address the student never typed, and a verification
        link sent somewhere they are not watching. Better to ask than guess.
        """
        for raw in ("a b@c.com", "Name <real@example.com>", "two@example.com, three@example.com"):
            with self.subTest(address=raw):
                self.assertFalse(
                    FitnessSignup._mv_is_valid_email(raw),
                    "%r must be rejected, not quietly rewritten" % (raw,))

    def test_rejects_a_domain_with_no_dotted_tld(self):
        """email_normalize accepts "a@b"; no public mailbox lives there."""
        self._check([
            ("a@b", "no TLD"),
            ("student@localhost", "not routable from the outside"),
        ], False)

    def test_rejects_absurdly_long_input(self):
        long_local = "a" * 250
        self.assertFalse(
            FitnessSignup._mv_is_valid_email("%s@example.com" % long_local),
            "an address past the 254-character limit must be rejected")

    def test_accepts_real_addresses(self):
        self._check([
            ("ana@yoleyva.test", "the studio's own test account"),
            ("info@corelabstudio.es", "the studio's address"),
            ("nom+etiqueta@corelabstudio.es", "plus addressing is legitimate"),
            ("first.last@sub.domain.example.com", "subdomains are fine"),
            ("a@b.co", "short but complete"),
            ("  spaced@example.com  ", "surrounding whitespace is trimmed, not a typo"),
        ], True)

    def test_accepts_mixed_case(self):
        """Case is not a typo. The local part is lowered on the way in, which
        is what res.users does with a login anyway."""
        self.assertTrue(FitnessSignup._mv_is_valid_email("Test.User@Example.COM"))
