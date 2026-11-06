# -*- coding: utf-8 -*-
"""A private class the weekly schedule generates is private, so a private credit pays for it.

The generator wrote the class type and not its session type, so every class
a "Barre Privada" schedule produced was session_type 'group'. The studio's
Add a student then refused a private credit on it ("no credit covers this
class") and took a group credit from a student who held both.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPrivateScheduleSession(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.room = env['fitness.classroom'].create({'name': 'PS Room', 'classroom_type': 'barre', 'capacity': 4})
        cls.private = env['fitness.class.type'].create({
            'name': 'PS Barre Privada', 'classroom_type': 'barre', 'session_type': 'private',
            'level': 'all', 'classroom_id': cls.room.id})
        cls.teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PS Teacher', 'login': 'ps.teacher@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('fitness_core.group_fitness_teacher').id])]})
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PS Manager', 'login': 'ps.manager@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('fitness_core.group_fitness_manager').id])]})

        def pack(name, session):
            return env['product.template'].create({
                'name': name, 'type': 'service', 'list_price': 30.0, 'sale_ok': True,
                'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 90,
                'fitness_class_type': 'barre', 'fitness_session_type': session})
        cls.p_private = pack('PS Private Pack', 'private')
        cls.p_group = pack('PS Group Pack', 'group')

    def _schedule(self):
        s = self.env['fitness.class.schedule'].create({
            'name': 'PS Privada', 'class_type_id': self.private.id, 'classroom_id': self.room.id,
            'weekday': 'tue', 'start_time': 12.0, 'duration': 1.0,
            'date_start': fields.Date.today() + timedelta(days=1), 'horizon_weeks': 3,
            'teacher_user_id': self.teacher.id})
        s.action_generate()
        return self.env['calendar.event'].search([('recurrence_id', '=', s.recurrence_id.id)], order='start')

    def _student(self, *packs):
        partner = self.env['res.partner'].create({'name': 'PS Student %s' % len(packs)})
        for p in packs:
            so = self.env['sale.order'].sudo().create({'partner_id': partner.id})
            self.env['sale.order.line'].sudo().create({
                'order_id': so.id, 'product_id': p.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 30.0})
            so.action_confirm()
        return partner

    def test_every_generated_class_is_private(self):
        events = self._schedule()
        self.assertTrue(events, 'fixture: nothing generated')
        self.assertEqual(set(events.mapped('session_type')), {'private'},
                         'a private schedule generated group classes')
        self.assertEqual(set(events.mapped('capacity')), {1})

    def test_add_a_student_takes_her_private_credit(self):
        event = self._schedule()[-1]
        both = self._student(self.p_group, self.p_private)
        self.env['fitness.add.student.wizard'].with_user(self.manager).create(
            {'event_id': event.id, 'student_id': both.id}).action_add()
        booking = self.env['fitness.booking'].sudo().search(
            [('calendar_event_id', '=', event.id), ('student_id', '=', both.id)])
        self.assertEqual(booking.package_order_line_id.product_id.product_tmpl_id, self.p_private,
                         'a group credit paid for a private class')
