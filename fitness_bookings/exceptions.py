# -*- coding: utf-8 -*-
"""Errors the booking flow raises, as types rather than sentences.

The portal used to recognise a late cancellation by searching the error's
English text for "less than 2 hours". That worked only while the wording and
the number both stayed still: change either and the portal silently stopped
recognising the case and showed a raw model error to the student instead.
Raising a type the caller can catch removes the coupling entirely - the
wording is then free to change, and to be translated, without breaking
anything downstream.
"""
from odoo.exceptions import UserError


class LateCancellationError(UserError):
    """A student tried to cancel inside the studio's cancellation window.

    Carries the window it was raised for, so a caller can word its own
    message without having to know the rule.
    """

    def __init__(self, message, window_hours=None):
        super().__init__(message)
        self.window_hours = window_hours
