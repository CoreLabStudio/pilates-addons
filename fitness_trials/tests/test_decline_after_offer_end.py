# -*- coding: utf-8 -*-
"""Declining a trial request once the free trial offer has ended.

Two sentences that were false.

B3-16: with the offer closed the bell still said "You are still welcome to
ask for another - your free class has not been used", and the dialog told
the manager she could ask again. Once the offer has ended no free trial can
be had: asking again is refused. Both now say the offer has ended, and the
student is told she can book a trial class in the app at its price.

F7: a free trial whose credit EXPIRED UNUSED was told "Your free trial has
already been used", and the manager "They have already had their trial
class". She never came. Both now say it was given and expired.

Clock pinned; every sentence in es, ca and en.
"""
from datetime import date, datetime, timedelta

from lxml import etree

from odoo.tests import TransactionCase, common, tagged
from odoo.tools.safe_eval import safe_eval

PINNED = datetime(2026, 10, 20, 9, 0, 0)       # Tuesday, 11:00 Madrid
OFFER_OPEN_UNTIL = '2026-10-31'
OFFER_ENDED_ON = '2026-10-19'                  # yesterday, Madrid
REFORMER_PRICE = 18.0
LANGS = ('es_ES', 'ca_ES', 'en_US')

ENDED = {
    'en_US': 'The free trial offer has ended',
    'es_ES': 'La oferta de clase de prueba gratuita ha terminado',
    'ca_ES': "L'oferta de classe de prova gratuïta s'ha acabat",
}
BOOK_IN_APP = {
    'en_US': 'You can book a trial class in the app for 18 €',
    'es_ES': 'Puedes reservar una clase de prueba en la app por 18 €',
    'ca_ES': "Pots reservar una classe de prova a l'app per 18 €",
}
#: anything that invites her to ask again, or says the free class is hers
ASK_AGAIN = {
    'en_US': ('ask for another', 'has not been used'),
    'es_ES': ('Puedes pedir otra', 'sigue disponible'),
    'ca_ES': ('Pots demanar-ne una altra', 'segueix disponible'),
}
EXPIRED = {
    'en_US': 'Your free trial was given to you but expired before you used it',
    'es_ES': 'Tu clase de prueba gratuita se te concedió pero caducó sin que '
             'la usaras',
    'ca_ES': "La teva classe de prova gratuïta se't va concedir però va "
             "caducar sense que la fessis servir",
}
SPENT = {
    'en_US': 'Your free trial has already been used',
    'es_ES': 'Tu clase de prueba gratuita ya se ha usado',
    'ca_ES': "La teva classe de prova gratuïta ja s'ha fet servir",
}
SHOP = {
    'en_US': 'You can buy a class pack or membership in the Shop',
    'es_ES': 'Puedes comprar un bono o una membresía en la Tienda',
    'ca_ES': 'Pots comprar un bo o una membresia a la Botiga',
}

DIALOG_ENDED = {
    'en_US': 'The free trial offer has ended, so they cannot ask for a free '
             'class again.',
    'es_ES': 'La oferta de clase de prueba gratuita ha terminado, así que no '
             'puede volver a pedir una clase gratis.',
    'ca_ES': "L'oferta de classe de prova gratuïta s'ha acabat, així que no "
             "pot tornar a demanar una classe gratis.",
}
DIALOG_EXPIRED = {
    'en_US': 'Their free trial was given but expired unused',
    'es_ES': 'Su clase de prueba gratuita se le concedió pero caducó sin usarse',
    'ca_ES': 'La seva classe de prova gratuïta se li va concedir però va '
             'caducar sense fer-se servir',
}
DIALOG_ASK_AGAIN = {
    'en_US': 'they can ask again',
    'es_ES': 'puede volver a pedirla',
    'ca_ES': 'la pot tornar a demanar',
}
DIALOG_HAD_IT = {
    'en_US': 'They have already had their trial class',
    'es_ES': 'Ya ha tenido su clase de prueba',
    'ca_ES': 'Ja ha fet la seva classe de prova',
}


@tagged('post_install', '-at_install')
class TestDeclineAfterOfferEnd(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.ICP = self.env['ir.config_parameter'].sudo()
        self.ICP.set_param('fitness.opening_date', '')
        self._offer_until(OFFER_OPEN_UNTIL)
        self.addCleanup(self.env.registry.clear_cache)
        self.TR = self.env['fitness.trial.request'].sudo()
        self.trial = {
            'reformer': self.env.ref('fitness_packages.product_reformer_trial'),
            'barre': self.env.ref('fitness_packages.product_barre_trial'),
        }
        for p in self.trial.values():
            p.write({'fitness_promo_mode': 'free', 'fitness_promo_start': False,
                     'fitness_promo_end': OFFER_OPEN_UNTIL})
        self.trial['reformer'].list_price = REFORMER_PRICE
        self.ctype = self.env['fitness.class.type'].create({
            'name': 'DAOE reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        self.manager = self._user('manager', ['base.group_user',
                                              'fitness_core.group_fitness_manager'])
        self.teacher = self._user('teacher', ['base.group_user',
                                              'fitness_core.group_fitness_teacher'])
        self._seq = 0

    # ── fixture ──────────────────────────────────────────────────────
    def _offer_until(self, day):
        self.ICP.set_param('fitness.trial_offer_end', day)
        self.env.registry.clear_cache()

    def _close_offer(self):
        self._offer_until(OFFER_ENDED_ON)
        for p in self.trial.values():
            p.fitness_promo_end = OFFER_ENDED_ON

    def _user(self, tag, groups, lang='en_US'):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'DAOE %s' % tag, 'login': 'daoe.%s@example.invalid' % tag,
            'email': 'daoe.%s@example.invalid' % tag, 'lang': lang,
            'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])]})

    def _student(self, lang):
        self._seq += 1
        return self._user('student%d' % self._seq,
                          ['base.group_portal', 'fitness_core.group_fitness_student'],
                          lang=lang)

    def _class(self, hours):
        start = PINNED + timedelta(hours=hours)
        return self.env['calendar.event'].sudo().create({
            'name': 'DAOE class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'is_fitness_class': True,
            'capacity': 6, 'session_type': 'group', 'user_id': self.teacher.id})

    def _request(self, student):
        req = self.TR.create({
            'name': student.name, 'email': student.email, 'phone': '600000000',
            'class_interest': 'reformer', 'partner_id': student.partner_id.id,
            'occurrence_id': self._class(48 + self._seq).id})
        # create_date is PostgreSQL's now(), which freeze_time does not reach.
        self.env.cr.execute(
            "UPDATE fitness_trial_request SET create_date = %s WHERE id = %s",
            (PINNED, req.id))
        req.invalidate_recordset(['create_date'])
        return req

    def _free_trial(self, student, expired_on=None):
        p = self.trial['reformer']
        order = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': p.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 0.0})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        line = order.order_line[:1]
        if expired_on:
            line.fitness_validity_end_date = expired_on
        return line

    def _wizard(self, req):
        return self.env['fitness.trial.decline.wizard'].with_user(
            self.manager).create({'request_id': req.id})

    def _dialog_says(self, wiz, lang):
        """The sentences the manager actually sees: the alert's divs whose
        `invisible` expression is false for this wizard."""
        arch = self.env['fitness.trial.decline.wizard'].with_context(
            lang=lang).get_views([(False, 'form')])['views']['form']['arch']
        values = {name: wiz[name] for name in wiz._fields
                  if name in ('trial_spent', 'decline_case')}
        shown = []
        for div in etree.fromstring(arch).iter('div'):
            expr = div.get('invisible')
            if expr is None or safe_eval(expr, dict(values)):
                continue
            shown.append(' '.join(''.join(div.itertext()).split()))
        return ' | '.join(shown)

    def _decline(self, req, reason=''):
        wiz = self._wizard(req)
        wiz.reason = reason
        wiz.action_confirm()
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', req.partner_id.user_ids[:1].id),
            ('notification_type', '=', 'trial_declined')],
            order='id desc', limit=1)
        self.assertTrue(bell, 'no bell was sent')
        return bell

    # ── B3-16: the offer has ended ───────────────────────────────────
    def test_offer_ended_the_bell_says_so_and_does_not_invite_her_back(self):
        for lang in LANGS:
            for reason in ('', 'No space that week.'):
                with self.subTest(lang=lang, reason=bool(reason)):
                    self._close_offer()
                    student = self._student(lang)
                    bell = self._decline(self._request(student), reason)
                    body = bell.body or ''
                    self.assertIn(ENDED[lang], body,
                                  '%s bell does not say the offer has ended: %r'
                                  % (lang, body))
                    self.assertIn(BOOK_IN_APP[lang], body,
                                  '%s bell does not offer the paid trial: %r'
                                  % (lang, body))
                    for phrase in ASK_AGAIN[lang]:
                        self.assertNotIn(phrase, body,
                                         '%s bell still invites her to ask '
                                         'again: %r' % (lang, body))
                    if reason:
                        self.assertIn(reason, body)
                    self.assertEqual(bell.action_url, '/my/packages')

    def test_offer_ended_the_dialog_says_so(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                self._close_offer()
                wiz = self._wizard(self._request(self._student(lang)))
                says = self._dialog_says(wiz, lang)
                self.assertIn(DIALOG_ENDED[lang], says,
                              '%s dialog does not say the offer has ended: %r'
                              % (lang, says))
                self.assertNotIn(DIALOG_ASK_AGAIN[lang], says,
                                 '%s dialog still says she can ask again: %r'
                                 % (lang, says))

    def test_approved_before_the_end_declined_after_it(self):
        """Booked while the offer ran, cancelled once it had closed: the
        booking is cancelled and nothing free can be asked for again."""
        for lang in LANGS:
            with self.subTest(lang=lang):
                # Each round approves while the offer runs.
                self._offer_until(OFFER_OPEN_UNTIL)
                for p in self.trial.values():
                    p.fitness_promo_end = OFFER_OPEN_UNTIL
                student = self._student(lang)
                req = self._request(student)
                req.with_user(self.manager).action_approve_and_book()
                booking = req._find_booking()
                self.assertEqual(booking.state, 'booked',
                                 'fixture: approval must book')
                self._close_offer()
                says = self._dialog_says(self._wizard(req), lang)
                self.assertIn(DIALOG_ENDED[lang], says)
                self.assertNotIn(DIALOG_ASK_AGAIN[lang], says)
                body = self._decline(req).body or ''
                self.assertEqual(booking.state, 'cancelled')
                self.assertIn(ENDED[lang], body)
                for phrase in ASK_AGAIN[lang]:
                    self.assertNotIn(phrase, body)

    def test_while_the_offer_runs_she_is_still_invited_back(self):
        """The negative: nothing changes while the offer is open."""
        for lang in LANGS:
            with self.subTest(lang=lang):
                student = self._student(lang)
                req = self._request(student)
                says = self._dialog_says(self._wizard(req), lang)
                self.assertIn(DIALOG_ASK_AGAIN[lang], says)
                self.assertNotIn(DIALOG_ENDED[lang], says)
                bell = self._decline(req)
                self.assertIn(ASK_AGAIN[lang][1], bell.body)
                self.assertNotIn(ENDED[lang], bell.body)
                self.assertEqual(bell.action_url, '/my/trial')

    # ── F7: a free trial that expired unused ────────────────────────
    def test_an_expired_unused_free_trial_is_not_called_used(self):
        for lang in LANGS:
            for reason in ('', 'No space that week.'):
                with self.subTest(lang=lang, reason=bool(reason)):
                    student = self._student(lang)
                    line = self._free_trial(student,
                                            expired_on=date(2026, 10, 10))
                    self.assertGreater(line.fitness_remaining_classes, 0,
                                       'fixture: the credit must be unused')
                    req = self._request(student)
                    wiz = self._wizard(req)
                    self.assertTrue(wiz.trial_spent,
                                    'she may not ask for a free one again')
                    says = self._dialog_says(wiz, lang)
                    self.assertIn(DIALOG_EXPIRED[lang], says,
                                  '%s dialog: %r' % (lang, says))
                    self.assertNotIn(DIALOG_HAD_IT[lang], says,
                                     '%s dialog says she had a class she '
                                     'never came to: %r' % (lang, says))
                    bell = self._decline(req, reason)
                    body = bell.body or ''
                    self.assertIn(EXPIRED[lang], body,
                                  '%s bell: %r' % (lang, body))
                    self.assertNotIn(SPENT[lang], body)
                    self.assertIn(SHOP[lang], body)
                    if reason:
                        self.assertIn(reason, body)
                    self.assertEqual(bell.action_url, '/my/packages')

    def test_a_free_trial_she_came_to_is_still_called_used(self):
        """The negative: a spent credit keeps the old sentence."""
        for lang in LANGS:
            with self.subTest(lang=lang):
                student = self._student(lang)
                line = self._free_trial(student, expired_on=date(2026, 10, 10))
                line.fitness_remaining_classes = 0
                req = self._request(student)
                says = self._dialog_says(self._wizard(req), lang)
                self.assertIn(DIALOG_HAD_IT[lang], says)
                self.assertNotIn(DIALOG_EXPIRED[lang], says)
                body = self._decline(req).body or ''
                self.assertIn(SPENT[lang], body)
                self.assertNotIn(EXPIRED[lang], body)
