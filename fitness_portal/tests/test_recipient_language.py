# -*- coding: utf-8 -*-
"""Written in the reader's language; when she has none, in the studio's.

  - The desk and booking dialogs a manager works in (Sell at the desk, Record
    a walk-in, Free classes given, gift, make-student, cancel, credit back,
    move, add a student) showed English to a Spanish or Catalan manager: the
    title, the cash/free choice, the button that records money (QA T1).
  - The booking refusals were f-strings: English to every student.
  - Bells spelled months with strftime ("1 Nov 2026") on a Spanish phone.
  - Nobody's language was the fallback: a code typed into the module
    (es_ES), and in places the SENDER's language.
  - The trial emails' subject fell back to Spanish and their body to English.
"""
import ast
import inspect
import re
from datetime import date, datetime, timedelta

from lxml import etree

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, common, tagged
from odoo.tools.translate import code_translations

from odoo.addons.fitness_core.models.studio_lang import (
    recipient_lang, studio_lang)

LANGS = ('es_ES', 'ca_ES')
DIALOGS = (
    'fitness.desk.sale.wizard',
    'fitness.record.attendance.wizard',
    'fitness.free.credit.report',
    'fitness.gift.wizard',
    'fitness.make.student.wizard',
    'fitness.booking.cancel.wizard',
    'fitness.booking.credit.back.wizard',
    'fitness.booking.reassign.wizard',
    'fitness.add.student.wizard',
)
# Words that are the same in all three languages.
SAME = {'Barre', 'Reformer', 'Reformer Pilates', 'Bizum', 'CoreLab', 'Total', 'Email', 'Online',
        'OK', 'Error'}
WORD = re.compile(r'[A-Za-z]{3}')


def _english(a, b):
    return a == b and WORD.search(a or '') and a.strip() not in SAME


@tagged('post_install', '-at_install')
class TestDialogsSpeakTheManagersLanguage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in LANGS:
            cls.env['res.lang']._activate_and_install_lang(code)

    def test_no_english_in_the_dialog_views(self):
        arch = self.env['ir.ui.view']._fields['arch_db']
        left = []
        for model in DIALOGS:
            for view in self.env['ir.ui.view'].search([('model', '=', model)]):
                en = arch.get_trans_terms(view.with_context(lang='en_US').arch_db)
                for code in LANGS:
                    tr = arch.get_trans_terms(view.with_context(lang=code).arch_db)
                    self.assertEqual(len(en), len(tr), view.xml_id)
                    left += ['%s %s: %s' % (code, view.xml_id, a)
                             for a, b in zip(en, tr) if _english(a, b)]
        self.assertFalse(left, 'English left:\n' + '\n'.join(left))

    def _shown_fields(self, model):
        """The fields a form can show: hidden helper fields are never read."""
        shown = set()
        for view in self.env['ir.ui.view'].search([('model', '=', model),
                                                   ('type', '=', 'form')]):
            for node in etree.fromstring(view.arch.encode()).iter('field'):
                if node.get('invisible') not in ('1', 'True'):
                    shown.add(node.get('name'))
        return shown

    def test_no_english_in_the_dialog_fields(self):
        left = []
        attrs = ['string', 'help', 'selection']
        for model in DIALOGS:
            shown = self._shown_fields(model)
            en = self.env[model].with_context(lang='en_US').fields_get(attributes=attrs)
            for code in LANGS:
                tr = self.env[model].with_context(lang=code).fields_get(attributes=attrs)
                for name, d in en.items():
                    # A language picker lists languages by their own names.
                    if name not in shown or name == 'lang':
                        continue
                    for attr in ('string', 'help'):
                        if _english(d.get(attr), tr[name].get(attr)):
                            left.append('%s %s.%s %s: %s' % (
                                code, model, name, attr, d[attr][:70]))
                    for (_k, a), (_k2, b) in zip(d.get('selection') or [],
                                                tr[name].get('selection') or []):
                        if _english(a, b):
                            left.append('%s %s.%s selection: %s' % (code, model, name, a))
        self.assertFalse(left, 'English left:\n' + '\n'.join(left))

    def test_no_english_in_what_the_dialogs_say(self):
        """Every _() message in the dialogs' code has an es and ca text."""
        left = []
        for model in DIALOGS:
            cls = type(self.env[model])
            files = {inspect.getsourcefile(c) for c in cls.__mro__
                     if c.__module__.startswith('odoo.addons.fitness_')}
            for path in files:
                module = re.search(r'(fitness_[a-z_]+)[\\/]models', path)[1]
                tree = ast.parse(open(path, encoding='utf-8').read())
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Call) and node.args
                            and isinstance(node.args[0], ast.Constant)
                            and isinstance(node.args[0].value, str)):
                        continue
                    f = node.func
                    if not ((isinstance(f, ast.Name) and f.id == '_')
                            or (isinstance(f, ast.Attribute) and f.attr == '_')):
                        continue
                    msgid = node.args[0].value
                    for code in LANGS:
                        tr = code_translations.get_python_translations(module, code)
                        if not tr.get(msgid):
                            left.append('%s %s:%s %s' % (
                                code, path.rsplit('fitness_', 1)[-1], node.lineno,
                                msgid[:70]))
        self.assertFalse(left, 'English left:\n' + '\n'.join(sorted(set(left))))

    def test_the_manager_bells_have_spanish_and_catalan(self):
        for module, msgid in (
                ('fitness_portal', 'Cash request: %(student)s'),
                ('fitness_portal', '%(student)s wants to pay for %(product)s in '
                                   'cash at the studio. Nothing is active until '
                                   'you approve it.'),
                ('fitness_bookings', 'Cannot book a class that has already '
                                     'started or passed (%(when)s).'),
                ('fitness_bookings', '%(student)s is already booked for this class.')):
            for code in LANGS:
                with self.subTest(msgid=msgid[:30], lang=code):
                    self.assertTrue(code_translations.get_python_translations(
                        module, code).get(msgid))


@tagged('post_install', '-at_install')
class TestRecipientLanguage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in LANGS:
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        cls.company_partner = cls.env.company.partner_id

    def _user(self, tag, lang):
        u = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RL %s' % tag, 'login': 'rl.%s@example.invalid' % tag,
            'email': 'rl.%s@example.invalid' % tag,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        # Written after create: res.users fills an empty lang from the context.
        self.env.cr.execute("UPDATE res_partner SET lang=%s WHERE id=%s",
                            (lang or None, u.partner_id.id))
        u.invalidate_recordset()
        u.partner_id.invalidate_recordset()
        return u

    def test_no_language_falls_back_to_the_studios(self):
        for studio in ('ca_ES', 'es_ES', 'en_US'):
            with self.subTest(studio=studio):
                self.company_partner.lang = studio
                self.assertEqual(studio_lang(self.env), studio)
                self.assertEqual(recipient_lang(self.env, self._user('n' + studio, False)), studio)
                self.assertEqual(recipient_lang(self.env, self._user('o' + studio, 'en_US')), 'en_US')

    def test_a_language_not_installed_is_not_used(self):
        self.company_partner.lang = 'ca_ES'
        u = self._user('fr', 'fr_FR')
        self.assertEqual(recipient_lang(self.env, u), 'ca_ES')

    def test_a_bell_spells_the_month_in_her_language(self):
        """The credit-expiry bell: '1 nov 2026', not '1 Nov 2026'."""
        self.company_partner.lang = 'es_ES'
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness_notifications.send_credit_expiry', 'True')
        student = self._user('expiry', 'es_ES')
        pack = self.env['product.template'].create({
            'name': 'RL pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 30, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 50.0})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        line = order.order_line[:1]
        line.sudo().write({'fitness_validity_end_date': date(2026, 11, 1)})
        with common.freeze_time(datetime(2026, 10, 27, 9, 0)):
            self.env['fitness.booking'].with_context(lang='en_US')._cron_check_credit_expiry()
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', student.id), ('notification_type', '=', 'credit_expiring')])
        self.assertEqual(len(bell), 1, 'no expiry bell')
        self.assertIn('1 nov 2026', bell.body)
        self.assertNotIn('Nov', bell.body)
        self.assertNotIn('Your pack', bell.body)

    def test_a_refusal_is_in_the_readers_language(self):
        student = self._user('refusal', 'ca_ES')
        ctype = self.env['fitness.class.type'].create({
            'name': 'RL Reformer', 'classroom_type': 'reformer', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        pack = self.env['product.template'].create({
            'name': 'RL reformer pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 120, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 50.0})]})
        order.with_context(skip_fitness_notification=True).action_confirm()
        start = datetime(2026, 10, 26, 8, 0)
        event = self.env['calendar.event'].sudo().create({
            'name': 'RL class', 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True, 'capacity': 8,
            'session_type': 'group'})
        for code, english in (('es_ES', 'Cannot book'), ('ca_ES', 'Cannot book')):
            with self.subTest(lang=code):
                with common.freeze_time(start + timedelta(minutes=5)):
                    with self.assertRaises(ValidationError) as caught:
                        self.env['fitness.booking'].sudo().with_context(lang=code).create({
                            'student_id': student.partner_id.id,
                            'calendar_event_id': event.id})
                msg = str(caught.exception)
                self.assertNotIn(english, msg)
                self.assertIn('09:00', msg)

    def test_a_class_is_named_with_the_readers_weekday(self):
        ctype = self.env['fitness.class.type'].create({
            'name': 'RL Named', 'classroom_type': 'barre', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        start = datetime(2026, 10, 25, 8, 0)     # Sunday 09:00 Madrid
        event = self.env['calendar.event'].sudo().create({
            'name': 'RL named', 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True, 'capacity': 8,
            'session_type': 'group'})
        en = event.with_context(lang='en_US').display_name
        es = event.with_context(lang='es_ES').display_name
        self.assertIn('Sun', en)
        self.assertIn('09:00', en)
        self.assertIn('dom', es)
        self.assertIn('09:00', es)
        self.assertNotIn('Sun', es)

    def test_the_trial_emails_agree_on_one_language(self):
        """Subject and body in the same language, whatever the request holds."""
        Req = self.env['fitness.trial.request'].sudo()
        tmpl = self.env.ref('fitness_trials.mail_template_trial_pending')
        for studio, stored, subject_word in (
                ('es_ES', False, 'Solicitud'),
                ('ca_ES', False, "Sol·licitud"),
                ('ca_ES', 'fr_FR', "Sol·licitud"),
                ('es_ES', 'en_US', 'request received')):
            with self.subTest(studio=studio, stored=stored):
                self.company_partner.lang = studio
                req = Req.create({'name': 'RL trial', 'email': 'rl.trial@example.invalid',
                                  'phone': '600000003', 'class_interest': 'barre'})
                self.env.cr.execute("UPDATE fitness_trial_request SET lang=%s WHERE id=%s",
                                    (stored or None, req.id))
                req.invalidate_recordset()
                subject = tmpl._render_field('subject', req.ids)[req.id]
                body = tmpl._render_field('body_html', req.ids)[req.id]
                self.assertIn(subject_word, subject)
                if subject_word == 'request received':
                    self.assertIn('Hello', body)
                else:
                    self.assertIn('Hola', body)
                self.assertEqual(tmpl._render_lang(req.ids)[req.id],
                                 stored if stored in ('es_ES', 'ca_ES', 'en_US') else studio)

    def test_a_new_trial_request_takes_the_studios_language(self):
        self.company_partner.lang = 'ca_ES'
        req = self.env['fitness.trial.request'].sudo().create({
            'name': 'RL new', 'email': 'rl.new@example.invalid', 'phone': '600000004',
            'class_interest': 'barre'})
        self.assertEqual(req.lang, 'ca_ES')
