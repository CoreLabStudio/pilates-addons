# -*- coding: utf-8 -*-
"""The swap and reschedule emails survive a student with an inactive language.

Both templates took {{ object.student_id.lang }} as their language, and
Odoo refuses to render in a code that is not active ("Invalid language
code"), so she was sent nothing. They now use fitness_mail_lang: hers when
active, else the studio's. Same fix and same reasoning as the booking
templates in fitness_notifications (test_mail_lang_falls_back).

The inactive code is written by SQL: the ORM will not store it, and will
not deactivate a language a partner holds.
"""
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 8, 0, 0)
INACTIVE = 'fr_FR'

TEMPLATES = {
    'fitness_teacher_swap.mail_template_teacher_swap':
        'El/La instructor/a de tu clase ha cambiado',
    'fitness_teacher_swap.mail_template_class_rescheduled':
        'Tu clase ha cambiado de horario',
}
SPANISH_FOOTER = 'Por favor, no respondas a este correo.'


@tagged('post_install', '-at_install')
class TestSwapMailLangFallsBack(TransactionCase):

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
        self.env.company.partner_id.lang = 'es_ES'
        lang = self.env['res.lang'].with_context(active_test=False).search(
            [('code', '=', INACTIVE)])
        self.assertTrue(lang and not lang.active,
                        'fixture: %s must exist and be inactive' % INACTIVE)
        ctype = self.env['fitness.class.type'].create({
            'name': 'SL Reformer', 'classroom_type': 'reformer',
            'duration': 50, 'level': 'all', 'session_type': 'group'})
        start = PINNED + timedelta(days=1, hours=2)
        event = self.env['calendar.event'].sudo().create({
            'name': 'SL class', 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True,
            'capacity': 6})
        tmpl = self.env['product.template'].create({
            'name': 'SL pack 5', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        self.partner = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'SL Student', 'login': 'sl.student@example.invalid',
                'email': 'sl.student@example.invalid',
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
                'calendar_event_id': event.id,
                'package_order_line_id': order.order_line[:1].id})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET lang = %s WHERE id = %s",
            (INACTIVE, self.partner.id))
        self.env.invalidate_all()
        self.assertEqual(self.booking.student_id.lang, INACTIVE)

    def test_both_swap_templates_render_in_the_studio_language(self):
        for xmlid, subject in TEMPLATES.items():
            with self.subTest(template=xmlid):
                mail_id = self.env.ref(xmlid).sudo().send_mail(
                    self.booking.id, force_send=False)
                mail = self.env['mail.mail'].sudo().browse(mail_id)
                self.assertTrue(mail.exists(), 'no mail was queued')
                self.assertEqual(mail.subject, subject)
                self.assertIn(SPANISH_FOOTER, str(mail.body_html))
