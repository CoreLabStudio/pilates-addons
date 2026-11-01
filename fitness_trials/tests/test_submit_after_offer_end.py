# -*- coding: utf-8 -*-
"""A trial request cannot be posted once the free trial is over.

/trial hides its form when fitness.trial_offer_end has passed, but
/trial/submit never asked: a direct POST with a CSRF token from any public
page created a pending request after the end. The submit now answers with
the same "the free trial has ended" page and writes nothing.

The control test posts the identical form while the offer is open and
expects the request, so the refusal cannot pass because the post was
malformed.
"""
from datetime import datetime, timedelta
import re

import pytz

from odoo.tests import HttpCase, common, tagged

MADRID = pytz.timezone('Europe/Madrid')
PINNED = datetime(2026, 10, 17, 10, 0)
ENDED = '2026-10-16'      # yesterday, relative to the pinned clock
STILL_OPEN = '2026-10-20'
SENTENCE = 'La clase de prueba gratuita ha terminado'


def _utc(local_naive):
    return MADRID.localize(local_naive).astimezone(pytz.UTC).replace(tzinfo=None)


@tagged("post_install", "-at_install")
class TestSubmitAfterOfferEnd(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(_utc(PINNED))
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['res.lang']._activate_lang('es_ES')
        self.ctype = self.env['fitness.class.type'].sudo().create({
            'name': 'Submit After End Barre', 'classroom_type': 'barre',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        TR = self.env['fitness.trial.request'].sudo()
        day = PINNED.date() + timedelta(days=2)
        while not TR._is_open_on(day):
            day += timedelta(days=1)
        self.day = day.isoformat()
        self.addCleanup(self.env.registry.clear_cache)

    def _offer_ends(self, value):
        self.env['ir.config_parameter'].sudo().set_param('fitness.trial_offer_end', value)
        self.env.registry.clear_cache()
        self.env.flush_all()

    def _post(self, email):
        """The form, posted straight to /trial/submit by a logged-out visitor.

        The token comes from /web/login: once the offer is over /trial has no
        form, and so no token, but any public page hands one out."""
        self.opener.cookies.set('mv_lang', 'es_ES')
        page = self.url_open('/web/login')
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        self.assertTrue(tok, "no CSRF token on /web/login - the post below would prove nothing")
        return self.url_open('/trial/submit', data={
            'csrf_token': tok.group(1),
            'name': 'Direct Post', 'email': email, 'phone': '',
            'class_interest': 'barre', 'class_type_id': str(self.ctype.id),
            'preferred_date': self.day, 'preferred_period': 'morning',
            'source': 'website',
        })

    def _requests(self, email):
        return self.env['fitness.trial.request'].sudo().search_count([('email', '=', email)])

    def test_the_post_creates_the_request_while_the_offer_is_open(self):
        self._offer_ends(STILL_OPEN)
        res = self._post('direct.open@example.invalid')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._requests('direct.open@example.invalid'), 1,
                         "the control post made no request - the form below is not a valid submission")

    def test_a_direct_post_after_the_end_creates_nothing(self):
        self._offer_ends(ENDED)
        res = self._post('direct.ended@example.invalid')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._requests('direct.ended@example.invalid'), 0,
                         "a request was created after the free trial ended")
        self.assertIn(SENTENCE, res.text,
                      "the refusal does not say the free trial has ended")
