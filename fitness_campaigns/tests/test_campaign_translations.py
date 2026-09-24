# -*- coding: utf-8 -*-
"""The campaign notification reaches a student in her own language.

fitness_campaigns shipped with no i18n directory at all, so the two strings
a student actually sees - the bell title and body - rendered in English to a
Spanish studio. The email was never affected; it carries per-language blocks
inline.

Asserted through code_translations rather than env._(), because env._()
resolves the module from the CALLER's stack frame - called from a test it
answers for the test's module, not for fitness_campaigns, and would pass
against an empty catalogue.
"""

from odoo.tests import TransactionCase, tagged
from odoo.tools.translate import code_translations

STUDENT_FACING = (
    "%(studio)s would like your answer",
    "%(name)s - it takes a moment.",
)


@tagged("post_install", "-at_install")
class TestCampaignTranslations(TransactionCase):

    longMessage = False

    def test_the_bell_strings_are_translated(self):
        for lang in ("es_ES", "ca_ES"):
            catalogue = code_translations.get_python_translations(
                "fitness_campaigns", lang)
            for src in STUDENT_FACING:
                self.assertIn(
                    src, catalogue,
                    "%s has no %s translation - a student would read it in "
                    "English" % (src, lang))
                self.assertTrue(
                    catalogue[src].strip(),
                    "%s is present but empty in %s" % (src, lang))
                self.assertNotEqual(
                    catalogue[src], src,
                    "%s in %s is just the English copied back" % (src, lang))

    def test_the_placeholders_survive_translation(self):
        """A translated string that drops %(studio)s crashes at render."""
        for lang in ("es_ES", "ca_ES"):
            catalogue = code_translations.get_python_translations(
                "fitness_campaigns", lang)
            self.assertIn(
                "%(studio)s", catalogue["%(studio)s would like your answer"],
                "the %(studio)s placeholder was lost in the " + lang +
                " translation")
            self.assertIn(
                "%(name)s", catalogue["%(name)s - it takes a moment."],
                "the %(name)s placeholder was lost in the " + lang +
                " translation")
