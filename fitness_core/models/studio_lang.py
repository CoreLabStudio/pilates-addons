# -*- coding: utf-8 -*-
"""Whose language a message is written in.

A bell, an email or a refusal is written in the language of the person who
will READ it. When that person has no language set, the studio's own
language answers - the company's - and never a code typed into the module.

This used to be `user.lang or 'es_ES'` in a dozen places, and in a few the
sender's language instead of the recipient's: a Catalan student booked by a
Spanish manager got a Spanish bell, and a studio set up in Catalan would
still have fallen back to Spanish everywhere.
"""
from odoo.tools import format_date, format_datetime

from .studio_time import STUDIO_TZ


def studio_lang(env):
    """The studio's language: the company's, if it is installed."""
    installed = dict(env['res.lang'].get_installed())
    lang = env.company.partner_id.lang
    if lang in installed:
        return lang
    # The source language: every msgid is written in it, so a message in it
    # is never half-translated.
    return 'en_US'


def recipient_lang(env, who):
    """The language to write to `who` in (a user or a partner).

    Their own when it is installed, else the studio's.
    """
    lang = who.lang if who else False
    if lang and lang in dict(env['res.lang'].get_installed()):
        return lang
    return studio_lang(env)


def studio_date(env, value, pattern, lang):
    """A date spelled in `lang` (babel pattern, e.g. 'd MMM y').

    strftime spells month and weekday names in the server's locale, which
    is English whatever the reader reads.
    """
    if not value:
        return ''
    return format_date(env, value, lang_code=lang, date_format=pattern)


def studio_datetime(env, value, pattern, lang):
    """A stored (naive UTC) datetime, on the studio's clock, in `lang`."""
    if not value:
        return ''
    return format_datetime(env, value, tz=STUDIO_TZ, dt_format=pattern,
                           lang_code=lang)
