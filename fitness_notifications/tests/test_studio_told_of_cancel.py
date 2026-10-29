# -*- coding: utf-8 -*-
"""When a student cancels, her teacher and the studio managers are told.

A cancellation reached the student alone: the teacher found out by opening
her roster, the studio by looking at the class. Now every cancel the
student makes herself tells:

  * the class's teacher, by app bell linked to her roster, in her language;
  * every studio manager, through Odoo - a note on the class record,
    delivered to their Odoo inbox, never by email whatever their
    preference: which class and when, who cancelled, how many are still
    booked, and "late" inside the cancellation window.

Group and private alike; no teacher, managers only. The studio cancelling
on her behalf tells nobody at the studio, and a booking tells no manager.
Clock pinned, window read from the setting.
"""
from datetime import datetime, timedelta

from odoo.tests import HttpCase, TransactionCase, common, tagged
from odoo.tools import html2plaintext

PINNED = datetime(2026, 11, 4, 8, 0, 0)

TITLE = {
    'en_US': ('Cancellation: ', 'Late cancellation: '),
    'es_ES': ('Cancelación: ', 'Cancelación tardía: '),
    'ca_ES': ('Cancel·lació: ', 'Cancel·lació tardana: '),
}
STILL = {
    'en_US': 'Still booked: %d.',
    'es_ES': 'Siguen reservadas: %d.',
    'ca_ES': 'Continuen reservades: %d.',
}


@tagged('post_install', '-at_install')
class TestStudioToldOfCancel(TransactionCase):

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
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.cancellation_window_hours', '6')
        self._seq = 0
        self.types = {s: self.env['fitness.class.type'].create({
            'name': 'ST %s' % s, 'classroom_type': 'reformer', 'duration': 50,
            'level': 'all', 'session_type': s}) for s in ('group', 'private')}
        self.packs = {s: self.env['product.template'].create({
            'name': 'ST pack %s' % s, 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'reformer',
            'fitness_session_type': s}) for s in ('group', 'private')}
        self.manager_es = self._user('st.mgr.es', 'es_ES', manager=True)
        self.manager_ca = self._user('st.mgr.ca', 'ca_ES', manager=True)
        # Asked to be emailed about everything: still inbox only.
        self.manager_es.notification_type = 'email'
        self.env.company.partner_id.lang = 'es_ES'                # the studio's language
        self.teacher = self._user('st.teacher', 'ca_ES', teacher=True)

    def _user(self, login, lang, manager=False, teacher=False):
        groups = ['fitness_core.group_fitness_manager', 'base.group_user'] if manager else (
            ['base.group_portal', 'fitness_core.group_fitness_teacher'] if teacher else
            ['base.group_portal', 'fitness_core.group_fitness_student'])
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'ST %s' % login, 'login': '%s@example.invalid' % login,
            'email': '%s@example.invalid' % login, 'lang': lang, 'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])]})

    def _class(self, session='group', hours_ahead=24, teacher=True):
        start = PINNED + timedelta(hours=hours_ahead)
        return self.env['calendar.event'].create({
            'name': 'ST Class %s' % session, 'start': start,
            'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[session].id, 'is_fitness_class': True,
            'session_type': session, 'capacity': 6,
            'user_id': self.teacher.id if teacher else False})

    def _book(self, event, session='group'):
        self._seq += 1
        student = self._user('st.student.%d' % self._seq, 'en_US')
        order = self.env['sale.order'].sudo().create({'partner_id': student.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.packs[session].product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.action_confirm()
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id, 'calendar_event_id': event.id,
            'package_order_line_id': order.order_line[:1].id})
        return student, booking

    def _bells(self, user):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id), ('notification_type', '=', 'student_cancelled')], order='id')

    def _inbox(self, user, event):
        return self.env['mail.notification'].sudo().search([
            ('res_partner_id', '=', user.partner_id.id),
            ('mail_message_id.model', '=', 'calendar.event'),
            ('mail_message_id.res_id', '=', event.id)])

    def _mails_to(self, *users):
        return self.env['mail.mail'].sudo().search([
            ('recipient_ids', 'in', [u.partner_id.id for u in users])])

    def _assert_teacher_bell(self, event, late, still):
        bell = self._bells(self.teacher)
        self.assertEqual(len(bell), 1, 'the teacher got %d app bells' % len(bell))
        self.assertTrue(bell.title.startswith(TITLE['ca_ES'][1 if late else 0]), bell.title)
        self.assertIn(STILL['ca_ES'] % still, bell.body)
        self.assertEqual(bell.action_url, '/my/instructor/classes/%d' % event.id)

    def _assert_managers_told(self, event, student, late, still):
        """One note on the class, in each manager's Odoo inbox; no email, no app bell."""
        for manager in (self.manager_es, self.manager_ca):
            notif = self._inbox(manager, event)
            self.assertEqual(len(notif), 1, '%s has %d inbox notices' % (manager.login, len(notif)))
            self.assertEqual(notif.notification_type, 'inbox')
            self.assertFalse(self._bells(manager), '%s still got the app bell' % manager.login)
        self.assertFalse(self._mails_to(self.manager_es, self.manager_ca),
                         'a manager was emailed about a cancellation')
        note = notif.mail_message_id
        self.assertEqual((note.model, note.res_id), ('calendar.event', event.id),
                         'the note is not on the class')
        text = note.body or ''
        self.assertIn(TITLE['es_ES'][1 if late else 0].strip(), text, text)
        self.assertIn(student.name, text)
        self.assertIn(STILL['es_ES'] % still, text)
        self.assertEqual('menos de 6 horas' in text, late, text)
        # Posted by the system, not in her name.
        self.assertEqual(note.author_id, self.env.ref('base.partner_root'),
                         'the note is posted as %s' % note.author_id.name)
        self.assertNotEqual(note.author_id, student.partner_id)

    def test_the_note_reads_as_one_line_in_es_ca_en(self):
        """Title and text on one line, so the inbox preview reads as a sentence."""
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                self.env.company.partner_id.lang = lang
                event = self._class('group')
                student, booking = self._book(event)
                booking.with_user(student).action_cancel()
                note = self._inbox(self.manager_ca, event).mail_message_id
                self.assertEqual((note.body or '').count('<p>'), 1, 'two paragraphs: %s' % note.body)
                line = html2plaintext(note.body or '').replace('*', '').strip()   # bold -> *x*
                self.assertNotIn('\n', line, 'not one line: %r' % line)
                self.assertTrue(line.startswith(TITLE[lang][0].strip()), '%s: %r' % (lang, line))
                self.assertIn(' – %s ' % student.name, line, '%s: %r' % (lang, line))

    # -- who is told --------------------------------------------------------

    def test_a_group_cancel_tells_the_teacher_by_app_and_the_managers_in_odoo(self):
        event = self._class('group')
        student, booking = self._book(event)
        self._book(event)                                    # one stays booked
        booking.with_user(student).action_cancel()
        self.assertEqual(booking.state, 'cancelled')
        self._assert_teacher_bell(event, False, 1)
        self.assertIn(student.name, self._bells(self.teacher).body)
        self._assert_managers_told(event, student, False, 1)

    def test_a_private_cancel_is_told_the_same_way(self):
        event = self._class('private')
        student, booking = self._book(event, 'private')
        booking.with_user(student).action_cancel()
        self._assert_teacher_bell(event, False, 0)
        self._assert_managers_told(event, student, False, 0)

    def test_no_teacher_still_tells_the_managers(self):
        event = self._class('group', teacher=False)
        student, booking = self._book(event)
        booking.with_user(student).action_cancel()
        self.assertFalse(self._bells(self.teacher))
        self._assert_managers_told(event, student, False, 0)

    # -- late or early ------------------------------------------------------

    def test_inside_the_window_it_says_late(self):
        event = self._class('group', hours_ahead=3)
        student, booking = self._book(event)
        booking.with_user(student).action_cancel()
        self._assert_teacher_bell(event, True, 0)
        self._assert_managers_told(event, student, True, 0)

    def test_late_follows_the_window_setting(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.cancellation_window_hours', '2')
        event = self._class('group', hours_ahead=3)
        student, booking = self._book(event)
        booking.with_user(student).action_cancel()
        self._assert_managers_told(event, student, False, 0)

    # -- who is not told ----------------------------------------------------

    def test_the_studio_cancelling_tells_nobody_at_the_studio(self):
        event = self._class('group')
        student, booking = self._book(event)
        booking.with_user(self.manager_es).action_cancel()
        self.assertEqual(booking.state, 'cancelled')
        self.assertFalse(self._bells(self.teacher))
        for manager in (self.manager_es, self.manager_ca):
            self.assertFalse(self._inbox(manager, event),
                             "%s was told of the studio's own cancel" % manager.login)

    def test_a_booking_tells_no_manager(self):
        event = self._class('group')
        self._book(event)
        for manager in (self.manager_es, self.manager_ca):
            self.assertFalse(self._inbox(manager, event),
                             '%s got an inbox notice for a booking' % manager.login)
            self.assertFalse(self.env['fitness.notification'].sudo().search([('user_id', '=', manager.id)]),
                             '%s got an app bell for a booking' % manager.login)

    # -- language -----------------------------------------------------------

    def test_a_teacher_whose_language_is_not_installed_gets_the_studios(self):
        event = self._class('group')
        student, booking = self._book(event)
        # Imported or deactivated later: a language nothing can render in.
        self.env.cr.execute("UPDATE res_partner SET lang = 'de_DE' WHERE id = %s",
                            [self.teacher.partner_id.id])
        self.env.invalidate_all()
        booking.with_user(student).action_cancel()
        bell = self._bells(self.teacher)
        self.assertEqual(len(bell), 1)
        self.assertTrue(bell.title.startswith(TITLE['es_ES'][0]),
                        'not in the studio language: %s' % bell.title)


@tagged('post_install', '-at_install')
class TestClassNoticeOpensSchedule(HttpCase):
    """Clicking the notice in the Odoo inbox opens the class in CoreLab -> Schedule."""

    def test_the_notice_opens_the_class_in_corelab_schedule(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TOUR Manager', 'login': 'tour.mgr@example.invalid', 'password': 'tour.mgr@example.invalid',
            'email': 'tour.mgr@example.invalid', 'lang': 'en_US',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('fitness_core.group_fitness_manager').id])]})
        student = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'TOUR Student', 'login': 'tour.student@example.invalid',
            'email': 'tour.student@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        ctype = self.env['fitness.class.type'].create({
            'name': 'TOUR Type', 'classroom_type': 'reformer', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        pack = self.env['product.template'].create({
            'name': 'TOUR pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'reformer', 'fitness_session_type': 'group'})
        order = self.env['sale.order'].sudo().create({'partner_id': student.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'reformer'})
        order.action_confirm()
        start = datetime.now().replace(microsecond=0) + timedelta(days=2)
        event = self.env['calendar.event'].create({
            'name': 'TOUR Class', 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': ctype.id, 'is_fitness_class': True, 'capacity': 6})
        booking = self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id, 'calendar_event_id': event.id,
            'package_order_line_id': order.order_line[:1].id})
        booking.with_user(student).action_cancel()
        self.start_tour('/odoo', 'fitness_class_notice_opens_schedule', login=manager.login)
