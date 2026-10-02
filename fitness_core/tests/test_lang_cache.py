# -*- coding: utf-8 -*-
"""The dashboard's computed text must not leak across languages.

Five non-stored computed fields on fitness.admin.dashboard return text
that depends on the reader's language. Odoo partitions a computed
field's cache only by the context keys the field declares, so each of
them needs depends_context=('lang',) or the first language to compute
it in a transaction is handed to everybody else in that transaction.

The same fault as fitness_subscriptions' fitness_fixed_slot_warning,
which is where it was first caught.

header_date is here for a different reason from the other four: its
compute never calls _(). It renders through babel's format_date, which
is driven by the locale, so it is language-dependent all the same and
sits in the same cache. It gets an assertion of its own because the
faked translation the others use cannot reach babel.

The previews were not translatable at all until this change - their
column headings and empty states were hardcoded English - so for two
of them the attribute would have been decorative and the test
unwritable. They are translated now, and these hold that too.
"""

from odoo.tests import TransactionCase, tagged

from .lang_cache_common import ENGLISH, SPANISH, LangCacheMixin

MODULE = 'fitness_core'

# Checked against header_date, which babel renders rather than _().
EN_WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
               'Saturday', 'Sunday')


@tagged("post_install", "-at_install")
class TestDashboardLangCache(LangCacheMixin, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_languages()

    def _dashboard(self):
        """A fresh dashboard, as opening Home makes one."""
        return self.env['fitness.admin.dashboard'].create({})

    # ── the greeting ────────────────────────────────────────────────────

    def test_header_greeting_does_not_inherit_the_other_language(self):
        self.assertDoesNotLeakLanguage(
            self._dashboard(), 'header_greeting', MODULE)

    # ── the date, which babel formats ───────────────────────────────────

    def test_header_date_does_not_inherit_the_other_language(self):
        """Spanish first, then English, same as the others.

        Asserted on real weekday names rather than a marker: babel does
        not go through _(), so there is nothing to fake. If es_ES were
        not resolvable the Spanish read would come back English and the
        second assertion would fail - which is the point, because a
        silently English "Spanish" read is how this test would rot into
        proving nothing.
        """
        rec = self._dashboard()
        spanish = rec.with_context(lang=SPANISH).header_date
        english = rec.with_context(lang=ENGLISH).header_date

        self.assertTrue(spanish and english, "header_date came back empty")
        self.assertTrue(
            any(day in english for day in EN_WEEKDAYS),
            "header_date was read in Spanish and then in English, and the "
            "English read came back %r - it was served the Spanish value "
            "cached a moment earlier" % english)
        self.assertFalse(
            any(day in spanish for day in EN_WEEKDAYS),
            "the Spanish read came back in English (%r), so this test is "
            "not comparing two languages at all" % spanish)

    # ── the three preview panels ────────────────────────────────────────

    def test_preview_classes_html_does_not_inherit_the_other_language(self):
        self.assertDoesNotLeakLanguage(
            self._dashboard(), 'preview_classes_html', MODULE)

    def test_preview_trials_html_does_not_inherit_the_other_language(self):
        self.assertDoesNotLeakLanguage(
            self._dashboard(), 'preview_trials_html', MODULE)

    def test_preview_messages_html_does_not_inherit_the_other_language(self):
        self.assertDoesNotLeakLanguage(
            self._dashboard(), 'preview_messages_html', MODULE)

    # ── the negative: reading one language twice is still cached ────────

    def test_reading_the_same_language_twice_is_not_broken_by_the_fix(self):
        """depends_context must partition the cache, not defeat it.

        Without this, a fix that simply disabled caching for these
        fields would pass every test above while recomputing the
        dashboard on every read.
        """
        rec = self._dashboard()
        first = rec.with_context(lang=ENGLISH).header_greeting
        second = rec.with_context(lang=ENGLISH).header_greeting
        self.assertEqual(
            first, second,
            "the same language read twice gave two different answers")
