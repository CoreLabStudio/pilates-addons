# -*- coding: utf-8 -*-
"""Assert a string really is translated, on a database with no languages.

A fresh install carries en_US alone. Activating es_ES inside a test marks
the language active and makes the gettext catalogues available - so a
sentence built in a controller with ``env._`` comes out Spanish - but it
does NOT import the modules' .po into the views' ``arch_db``. A term
written in a template therefore renders in English while a term written
in Python beside it renders in Spanish, in the same response.

That asymmetry is a property of the test database, not of the product, so
asserting a translated TEMPLATE term over HTTP on a gate database can
only ever fail. The repo's own convention - see
test_payment_return_states.test_every_flash_is_translated_in_spanish_and_catalan
- is to assert against the catalogue files instead.

This adds the part that convention misses. A .po entry is bound by its
``#:`` reference, and a view term is translated PER VIEW: the same words
come out translated on one page and English on the next when the
reference names the wrong view. So each term is checked three ways:

  1. the catalogue has it, with a non-empty translation that is not just
     the English copied across;
  2. the view the reference names exists;
  3. that view's arch really contains the English text.

(3) is the one that catches the binding bug, and it is the bug this
codebase has had four times.
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.dirname(os.path.dirname(HERE))
LANGS = {'es_ES': 'es_ES.po', 'ca_ES': 'ca_ES.po'}
VIEW_REF = re.compile(
    r'model_terms:ir\.ui\.view,arch_db:([a-z0-9_]+)\.([A-Za-z0-9_]+)')


def _unquote(text):
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return (text.replace('\\"', '"')
                .replace('\\n', '\n')
                .replace('\\\\', '\\'))


def catalogue(module, filename):
    """{msgid: (msgstr, [references])} from a .po file.

    Entries in an Odoo catalogue are separated by a blank line, so the
    file is split on those rather than parsed line by line with state -
    which is what made the first version of this wrong about which
    reference belonged to which entry.
    """
    path = os.path.join(ADDONS, module, 'i18n', filename)
    entries = {}
    for chunk in io.open(path, encoding='utf-8').read().split('\n\n'):
        refs, msgid, msgstr, part = [], [], [], None
        for line in chunk.split('\n'):
            line = line.strip()
            if line.startswith('#:'):
                refs.append(line[2:].strip())
            elif line.startswith('#'):
                continue
            elif line.startswith('msgid '):
                part, msgid = 'id', [_unquote(line[6:])]
            elif line.startswith('msgstr '):
                part, msgstr = 'str', [_unquote(line[7:])]
            elif line.startswith('"'):
                (msgid if part == 'id' else msgstr).append(_unquote(line))
        key = ''.join(msgid)
        if key:
            entries[key] = (''.join(msgstr), refs)
    return entries


class TranslationCheck:
    """Mix in beside HttpCase or TransactionCase."""

    def assert_translated(self, module, english, expected=None):
        """`english` has a real translation in Spanish and Catalan.

        `expected` is an optional {lang: fragment} the translation must
        contain, for the cases where the exact words matter - a forfeit
        badge and a refund badge must not read the same.
        """
        for lang, filename in sorted(LANGS.items()):
            cat = catalogue(module, filename)
            self.assertIn(
                english, cat,
                "%s/i18n/%s has no entry for %r, so it ships in English"
                % (module, filename, english[:60]))
            msgstr, refs = cat[english]
            self.assertTrue(
                msgstr.strip(),
                "%s leaves %r untranslated" % (filename, english[:60]))
            self.assertNotEqual(
                msgstr.strip(), english,
                "%s copies the English for %r" % (filename, english[:60]))
            if expected and lang in expected:
                self.assertIn(
                    expected[lang], msgstr,
                    "%s translates %r as %r, which is not the agreed wording"
                    % (filename, english[:40], msgstr[:60]))
            self._assert_reference_binds(english, refs, filename)

    def _assert_reference_binds(self, english, refs, filename):
        """A term written in a template is translated PER VIEW.

        When the reference names a view that does not hold the words the
        entry is dead: the page renders in English and nothing says so.
        """
        for ref in refs:
            match = VIEW_REF.search(ref)
            if not match:
                continue            # a code term; nothing to bind
            xmlid = '%s.%s' % match.groups()
            view = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(
                view,
                "%s binds %r to the view %s, which does not exist"
                % (filename, english[:40], xmlid))
            self.assertIn(
                english, view.arch,
                "%s binds %r to %s, whose arch does not contain it - the "
                "entry is dead and the page renders in English"
                % (filename, english[:40], xmlid))
