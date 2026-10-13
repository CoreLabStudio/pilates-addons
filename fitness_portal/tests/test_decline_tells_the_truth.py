# -*- coding: utf-8 -*-
"""Declining a trial request tells the student the truth about her free class.

The bell always said "You are still welcome to ask for another - your free
class has not been used", and the dialog told the manager "Their free class
is not used up - they can ask again". For a student the one-trial rule
refuses - the case approval now sends to this very button - both are false:
asking again would be refused again. Found in the merge-1 five-minute look.

The email was neutral and is untouched.
"""
from odoo.tests import tagged

from odoo.addons.fitness_portal.tests.test_one_trial_rule import OneTrialFixture

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
OPEN = {
    'en_US': 'your free class has not been used',
    'es_ES': 'tu clase gratuita sigue disponible',
    'ca_ES': 'la teva classe gratuïta',
}


@tagged('post_install', '-at_install')
class TestDeclineTellsTheTruth(OneTrialFixture):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def _decline(self, req, reason=''):
        wiz = self.env['fitness.trial.decline.wizard'].with_user(self.manager).create(
            {'request_id': req.id, 'reason': reason})
        flag = wiz.trial_spent
        wiz.action_confirm()
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', req.partner_id.user_ids[:1].id),
            ('notification_type', '=', 'trial_declined')], order='id desc', limit=1)
        return flag, bell.body or ''

    def _student_in(self, lang):
        s = self._student()
        s.lang = lang
        return s

    def test_a_student_who_had_her_trial_is_not_told_to_ask_again(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            for reason in ('', 'No space that week.'):
                with self.subTest(lang=lang, reason=bool(reason)):
                    student = self._student_in(lang)
                    self._trial_order(student, 'reformer', 0.0, used=True)
                    flag, body = self._decline(self._request(student, 'reformer'), reason)
                    self.assertTrue(flag, 'the dialog still says her free class is unused')
                    self.assertIn(SPENT[lang], body)
                    self.assertNotIn(OPEN[lang], body)
                    if reason:
                        self.assertIn(reason, body)

    def test_she_is_sent_to_the_shop_not_to_the_studio(self):
        """Having had her trial, she books with a pack or a membership, which
        she buys herself: the bell says so and opens the Shop. A student who
        may still have one is still sent to the trial page."""
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            for reason in ('', 'No space that week.'):
                with self.subTest(lang=lang, reason=bool(reason)):
                    student = self._student_in(lang)
                    self._trial_order(student, 'reformer', 0.0, used=True)
                    self._decline(self._request(student, 'reformer'), reason)
                    bell = self.env['fitness.notification'].sudo().search([
                        ('user_id', '=', student.id),
                        ('notification_type', '=', 'trial_declined')],
                        order='id desc', limit=1)
                    self.assertIn(SHOP[lang], bell.body)
                    self.assertNotIn('studio if', bell.body)
                    self.assertEqual(bell.action_url, '/my/packages')
        open_student = self._student_in('en_US')
        self._decline(self._request(open_student, 'reformer'))
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', open_student.id),
            ('notification_type', '=', 'trial_declined')], limit=1)
        self.assertEqual(bell.action_url, '/my/trial')

    def test_a_paid_trial_already_had_counts_too(self):
        student = self._student_in('es_ES')
        self._trial_order(student, 'reformer', 18.0, used=True)
        flag, body = self._decline(self._request(student, 'reformer'))
        self.assertTrue(flag)
        self.assertIn(SPENT['es_ES'], body)

    def test_a_student_who_may_still_have_one_is_told_as_before(self):
        student = self._student_in('es_ES')
        flag, body = self._decline(self._request(student, 'reformer'))
        self.assertFalse(flag)
        self.assertIn(OPEN['es_ES'], body)

    def test_an_unspent_trial_credit_is_not_spent(self):
        student = self._student_in('en_US')
        self._trial_order(student, 'reformer', 18.0, used=False)
        flag, body = self._decline(self._request(student, 'reformer'))
        self.assertFalse(flag, 'she holds a trial she can still use')
        self.assertIn(OPEN['en_US'], body)

    def test_declining_a_scheduled_trial_says_one_thing_to_both(self):
        """Approved and booked, then declined: the booking is cancelled and
        the trial comes back, so the manager and the student are both told
        it is not used up."""
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student = self._student_in(lang)
                req = self._request(student, 'reformer')
                self._approve(req)
                booking = req._find_booking()
                self.assertEqual(booking.state, 'booked', 'fixture: approve must book')
                flag, body = self._decline(req)
                self.assertFalse(flag, 'the dialog told the manager her trial is spent')
                self.assertIn(OPEN[lang], body)
                self.assertNotIn(SPENT[lang], body)
                self.assertEqual(booking.state, 'cancelled')
                # A cancelled trial hands back the entitlement, not a credit:
                # the one-trial rule must let her ask again, or "not used" is false.
                refusal = req._free_trial_refusal(student.partner_id, req._trial_product())
                self.assertNotIn(refusal, ('used', 'taken'),
                                 'the trial did not come back: %s' % refusal)

    def test_the_dialog_reads_in_the_managers_language(self):
        for lang, word in (('es_ES', 'Ya ha tenido su clase de prueba'),
                           ('ca_ES', 'Ja ha fet la seva classe de prova'),
                           ('en_US', 'They have already had their trial class')):
            with self.subTest(lang=lang):
                arch = self.env['fitness.trial.decline.wizard'].with_context(
                    lang=lang).get_views([(False, 'form')])['views']['form']['arch']
                self.assertIn(word, arch)
