# -*- coding: utf-8 -*-
"""The dark palette is written twice, so something has to keep it honest.

Plain CSS cannot declare a palette once and apply it under two different
conditions - the operating system's preference, and an explicit choice on
<html>. So the tokens exist in two blocks, and the day somebody adds a colour
to one and not the other, half the app would go dark and the other half would
not, on the exact devices nobody tests on. That is what this catches.
"""
import os
import re

from odoo.tests import TransactionCase, tagged

CSS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'src', 'css', 'corelab.css')

MEDIA_BLOCK = re.compile(
    r'@media \(prefers-color-scheme: dark\) \{\n'
    r'  :root:not\(\[data-theme="light"\]\) \{\n(.*?)\n  \}\n\}',
    re.S)
EXPLICIT_BLOCK = re.compile(
    r'^:root\[data-theme="dark"\] \{\n(.*?)\n\}', re.S | re.M)
TOKEN = re.compile(r'(--[a-z0-9-]+)\s*:\s*(.+?);', re.S)


@tagged('post_install', '-at_install')
class TestThemeSwitch(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(CSS, encoding='utf-8') as fh:
            cls.css = fh.read()

    def _tokens(self, pattern, what):
        found = pattern.search(self.css)
        self.assertTrue(
            found,
            "the %s dark block is gone or its selector changed - the switch "
            "silently stops working when that happens" % what)
        return {name: value.strip()
                for name, value in TOKEN.findall(found.group(1))}

    def test_both_dark_palettes_define_the_same_tokens(self):
        os_tokens = self._tokens(MEDIA_BLOCK, "operating-system")
        chosen = self._tokens(EXPLICIT_BLOCK, "explicit")

        self.assertTrue(os_tokens, "no tokens found in the dark block at all")
        self.assertEqual(
            set(os_tokens), set(chosen),
            "the two dark palettes have drifted apart, so the app would look "
            "different depending on whether dark came from the phone or from "
            "the switch")

    def test_both_dark_palettes_agree_on_every_value(self):
        os_tokens = self._tokens(MEDIA_BLOCK, "operating-system")
        chosen = self._tokens(EXPLICIT_BLOCK, "explicit")

        differing = {k: (os_tokens[k], chosen[k])
                     for k in set(os_tokens) & set(chosen)
                     if os_tokens[k] != chosen[k]}
        self.assertFalse(
            differing,
            "same token, different colour in the two dark blocks: %s"
            % sorted(differing))

    def test_an_explicit_light_choice_beats_a_dark_phone(self):
        """Without the :not() guard the media query wins and the switch does
        nothing for the person who most needs it - a dark phone in daylight."""
        self.assertIn(
            ':root:not([data-theme="light"])', self.css,
            "the OS dark block is unguarded, so choosing light cannot "
            "override a dark phone")

    def test_the_switch_is_in_the_portal_header(self):
        """A toggle nobody can find is not a toggle."""
        header = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(CSS))),
            'fitness_portal', 'views', 'portal_templates.xml')
        # fitness_core cannot see fitness_portal's path from here in every
        # layout, so fall back to searching the addons dir for the template.
        if not os.path.exists(header):
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(CSS))))
            header = os.path.join(root, 'fitness_portal', 'views',
                                  'portal_templates.xml')
        if not os.path.exists(header):
            self.skipTest("fitness_portal is not beside fitness_core here")
        with open(header, encoding='utf-8') as fh:
            markup = fh.read()
        self.assertEqual(
            markup.count('data-mv-theme-toggle'), 2,
            "both portal headers - student and teacher - need the switch, or "
            "one audience cannot reach it")
