# -*- coding: utf-8 -*-
"""Scaffolding for the depends_context=('lang',) regression tests.

THE BUG THESE GUARD
-------------------
Odoo caches a computed field per field and record, and partitions that
cache only by the context keys the field declares in depends_context.
A non-stored computed field whose value is a translated string is
language-dependent; without ('lang',) the first language to compute it
inside a transaction is handed to every later reader in that same
transaction. An English user opening a record just after a Spanish one
is served the Spanish text.

It was found on fitness_subscriptions' fitness_fixed_slot_warning,
where it had been invisible for as long as the sentence had no Spanish
and became visible the day it got one.

WHY THE TRANSLATION IS FAKED
----------------------------
The obvious test - read in Spanish, read in English, check they differ
- only means something if a Spanish translation actually exists on the
database under test. The fresh-install shape has no Spanish loaded at
all, so both reads would come back English, the assertion would hold,
and the test would pass while proving nothing. The upgrade shape would
pass for a different reason, and neither would catch a regression.

So the translation is supplied by the test. get_python_translations
consults an in-memory cache before it reads any .po, and the lookup is
a plain `.get(source, source)`, so seeding that cache with a mapping
that answers for ANY source makes every _() in the module return a
marked string. That is deterministic on both shapes, needs no language
pack, and still exercises the real _() path rather than a stub.

Marking every source rather than listing them one by one also keeps
the tests honest about branches: a compute that picks a different
sentence depending on the data still returns a marked one.
"""

from contextlib import contextmanager

from odoo.tools.translate import code_translations

SPANISH = 'es_ES'
ENGLISH = 'en_US'

# No HTML-special characters: these values pass through html.escape on
# their way into the dashboard previews, and a marker containing < or &
# would come back escaped and no longer match.
MARK = '~ES~'


class _EverySourceTranslated(dict):
    """A translation table that answers for every source string.

    odoo.tools.translate looks a term up with `.get(source, source)`,
    so overriding get is the whole of it.
    """

    def get(self, source, default=None):
        return '%s%s' % (MARK, source)


@contextmanager
def spanish_for(*modules):
    """Give these modules a Spanish translation, for this block only.

    Restores whatever was there before, including the common case of
    nothing having been loaded yet, so one test cannot leave a fake
    translation behind for the next.
    """
    store = code_translations.python_translations
    previous = []
    for module in modules:
        key = (module, SPANISH)
        previous.append((key, key in store, store.get(key)))
        store[key] = _EverySourceTranslated()
    try:
        yield
    finally:
        for key, had, saved in previous:
            if had:
                store[key] = saved
            else:
                store.pop(key, None)


class LangCacheMixin:
    """Shared assertion for "this field must not leak across languages"."""

    @classmethod
    def _activate_languages(cls):
        """Make both es_ES and en_US resolvable.

        Only flips res.lang.active. It imports no .po, so it costs
        nothing and does not alter the translations the database
        already has - which matters on the upgrade shape, where those
        are the studio's real ones.

        Both, not just Spanish: format_date resolves through res.lang
        and falls back to an active language when the one it is asked
        for is inactive. On a database where en_US is inactive the
        "English" read of header_date comes back Spanish, the two
        languages look identical, and the test fails for a reason
        that has nothing to do with the cache it is guarding.
        """
        cls.env['res.lang']._activate_lang(SPANISH)
        cls.env['res.lang']._activate_lang(ENGLISH)

    def assertDoesNotLeakLanguage(self, record, field, module):
        """Compute in Spanish, then read in English, and check.

        Order matters and is the point: Spanish goes first so that a
        field without depends_context has already cached a Spanish
        value by the time English asks for one.
        """
        with spanish_for(module):
            spanish = record.with_context(lang=SPANISH)[field]
            english = record.with_context(lang=ENGLISH)[field]

        self.assertTrue(
            spanish,
            "fixture wrong: %s is empty in Spanish, so this test could not "
            "tell a leak from a blank" % field)
        self.assertIn(
            MARK, spanish or '',
            "fixture wrong: %s came back with no translated text in it, so "
            "there is nothing in it that could differ between languages and "
            "the English assertion below would pass whatever happened"
            % field)
        self.assertNotIn(
            MARK, english or '',
            "%s was read in Spanish and then in English, and the English "
            "read was served the Spanish value computed moments earlier - "
            "the field needs depends_context=('lang',)" % field)
        self.assertNotEqual(
            spanish, english,
            "%s reads identically in both languages after a Spanish read"
            % field)
        return spanish, english
