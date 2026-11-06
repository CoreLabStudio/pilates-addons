# -*- coding: utf-8 -*-
"""A student whose language is not active still gets her email.

Every booking template took its language straight from the student:
{{ object.student_id.lang }}. Odoo renders a template in that language,
and env.lang refuses a code that is not active on the database:

    raise UserError(f'Invalid language code: {lang}')

so a partner carrying a deactivated language - one switched on once and
off later, or a contact imported with one - had every booking email fail.
_send_notification swallows the error, so nothing reached her and nothing
told the studio. The trial emails had exactly this bug (_trial_lang).

Now the template asks fitness_mail_lang: hers when it is active, else the
studio's - the same rule the bells use (recipient_lang). The subject,
the body and the footer follow the same field, so the email is in one
language from top to bottom.

The student's language is set by SQL because Odoo will neither store an
inactive code through the ORM nor deactivate a language a partner holds -
which is the point: the state is real, but only reachable from outside.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
INACTIVE = 'fr_FR'

# Template -> the subject it has in Spanish, the studio's language here.
TEMPLATES = {
    'fitness_notifications.mail_template_booking_confirmation':
        'Reserva Confirmada',
    'fitness_notifications.mail_template_booking_cancellation':
        'Reserva Cancelada',
    'fitness_notifications.mail_template_class_reminder':
        'Recordatorio de Clase',
    'fitness_notifications.mail_template_booking_moved':
        'Hemos cambiado tu clase',
    'fitness_notifications.mail_template_credit_expiring':
        'Tus créditos caducan pronto',
}
SPANISH_FOOTER = 'Por favor, no respondas a este correo.'


@tagged('post_install', '-at_install')
class TestMailLangFallsBack(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_and_install_lang('es_ES')

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env['ir.config_parameter'].sudo().set_param(
            'fitness.opening_date', '')
        # The studio writes in Spanish; that is the fallback asked for.
        self.env.company.partner_id.lang = 'es_ES'
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', INACTIVE)])
        self.assertTrue(lang and not lang.active,
                        'fixture: %s must exist and be inactive' % INACTIVE)
        ctype = self.env['fitness.class.type'].create({
            'name': 'ML Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        start = PINNED + timedelta(days=1, hours=2)
        self.event = self.env['calendar.event'].sudo().create({
            'name': 'ML class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True,
            'capacity': 6})
        tmpl = self.env['product.template'].create({
            'name': 'ML pack 5', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        self.partner = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'ML Student', 'login': 'ml.student@example.invalid',
                'email': 'ml.student@example.invalid',
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id,
                ])],
            }).partner_id
        order = self.env['sale.order'].sudo().create(
            {'partner_id': self.partner.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': tmpl.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.with_context(skip_fitness_notification=True).action_confirm()
        self.booking = self.env['fitness.booking'].sudo().with_context(
            skip_fitness_notification=True).create({
                'student_id': self.partner.id,
                'calendar_event_id': self.event.id,
                'package_order_line_id': order.order_line[:1].id})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET lang = %s WHERE id = %s",
            (INACTIVE, self.partner.id))
        self.env.invalidate_all()
        self.assertEqual(self.booking.student_id.lang, INACTIVE)

    def test_every_booking_template_renders_in_the_studio_language(self):
        for xmlid, subject in TEMPLATES.items():
            with self.subTest(template=xmlid):
                template = self.env.ref(xmlid)
                mail_id = template.sudo().send_mail(
                    self.booking.id, force_send=False)
                mail = self.env['mail.mail'].sudo().browse(mail_id)
                self.assertTrue(mail.exists(), 'no mail was queued')
                self.assertEqual(mail.subject, subject)
                self.assertIn(SPANISH_FOOTER, str(mail.body_html))

    def test_her_own_active_language_is_still_hers(self):
        self.env.cr.execute(
            "UPDATE res_partner SET lang = 'en_US' WHERE id = %s",
            (self.partner.id,))
        self.env.invalidate_all()
        template = self.env.ref(
            'fitness_notifications.mail_template_booking_confirmation')
        mail = self.env['mail.mail'].sudo().browse(
            template.sudo().send_mail(self.booking.id, force_send=False))
        self.assertEqual(mail.subject, 'Booking Confirmed')
