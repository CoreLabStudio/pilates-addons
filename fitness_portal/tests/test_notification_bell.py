# -*- coding: utf-8 -*-
"""The bell: a real count, read state she chose, and a change she can see.

Three faults, each pinned on its own so a fix to one cannot be mistaken
for a fix to another.

  1. The bell fetched the unread count and threw the number away, showing
     an 8px dot whether one notification was waiting or fifteen.

  2. /my/notifications marked EVERY notification read the moment it
     loaded. Below 600px the bell does not open a dropdown - it navigates
     there - so on a phone, tapping the bell to see what had arrived
     cleared the lot. The same student on a desktop had them marked one
     at a time as she clicked them.

  3. Every notification was the same grey card with the same dot. An
     invoice, a studio survey and "the studio moved your class to Friday"
     were indistinguishable, so the one she had to act on looked exactly
     like the one she could read next week.

The read-state tests go through the real HTTP routes rather than calling
the model, because what was wrong was what a request did, not what the
model allowed.
"""

import re

from odoo.tests import HttpCase, tagged

STUDENT_GROUP = 'fitness_core.group_fitness_student'


@tagged("post_install", "-at_install")
class TestNotificationBell(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "bell-test-pw-1"
        cls.user = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Bell Student",
                "login": "bell.student@example.invalid",
                "password": cls.password,
                "lang": "en_US",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref(STUDENT_GROUP).id])],
            })

    # -- fixtures ---------------------------------------------------------

    def _notify(self, kind='booking_confirmed', title='Something happened'):
        return self.env['fitness.notification'].sudo().create({
            'user_id': self.user.id,
            'notification_type': kind,
            'title': title,
            'body': 'Body text',
        })

    def _login(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)

    def _count(self):
        self._login()
        res = self.url_open("/my/notifications/count")
        self.assertEqual(res.status_code, 200)
        return res.json()['count']

    def _archive(self):
        self._login()
        res = self.url_open("/my/notifications")
        self.assertEqual(res.status_code, 200, res.text[:300])
        return res.text

    def _unread(self):
        return self.env['fitness.notification'].sudo().search_count(
            [('user_id', '=', self.user.id), ('is_read', '=', False)])

    # -- 1. a real count ---------------------------------------------------

    def test_the_count_is_the_actual_number(self):
        for i in range(5):
            self._notify(title='Notice %d' % i)

        self.assertEqual(
            self._count(), 5,
            "the bell is told %d unread when she has 5" % self._count())

    def test_the_count_is_zero_when_nothing_is_waiting(self):
        self.assertEqual(
            self._count(), 0,
            "the bell reports unread notifications that do not exist")

    def test_the_header_carries_a_count_element_not_a_bare_dot(self):
        """The markup has to be able to hold a number at all.

        Asserted on the class rather than on rendered digits, because the
        digits are written by the browser from the count route above.
        """
        self._notify()
        html = self._archive()
        self.assertIn(
            "mv-bell-count", html,
            "the bell badge is still the dot element, which has no room "
            "for a number")

    # -- 2. read state is hers to choose -----------------------------------

    def test_opening_the_archive_does_not_mark_anything_read(self):
        """The phone fault, stated plainly."""
        for i in range(3):
            self._notify(title='Notice %d' % i)

        self._archive()

        self.assertEqual(
            self._unread(), 3,
            "opening the list marked %d of her 3 notifications read. On a "
            "phone the bell navigates straight here, so tapping it to look "
            "would clear everything she had not read."
            % (3 - self._unread()))

    def test_one_notification_can_be_marked_read_on_its_own(self):
        a = self._notify(title='First')
        b = self._notify(title='Second')

        self._login()
        res = self.url_open(
            "/my/notifications/mark_read", data={'notif_id': a.id})
        self.assertEqual(res.status_code, 200)

        a.invalidate_recordset()
        b.invalidate_recordset()
        self.assertTrue(a.is_read, "the one she opened is still unread")
        self.assertFalse(
            b.is_read, "marking one read marked another read as well")

    def test_mark_all_read_still_clears_everything(self):
        """Clearing the lot stays available - as something she asks for.

        Posted with the token out of the page, which is what the browser
        does: the read-all route does not set csrf=False, so a bare POST
        is refused. Finding the form at all is half the test - it only
        renders while something is unread.
        """
        for i in range(4):
            self._notify(title='Notice %d' % i)

        html = self._archive()
        token = re.search(
            r'action="/my/notifications/read-all".*?'
            r'name="csrf_token"[^>]*value="([^"]+)"', html, re.S)
        self.assertTrue(
            token,
            "the Mark all read form is not on the page, so she has no way "
            "to clear them now that opening the list no longer does it")

        res = self.url_open(
            "/my/notifications/read-all",
            data={'csrf_token': token.group(1)}, allow_redirects=False)
        self.assertIn(
            res.status_code, (200, 302, 303),
            "Mark all read answered %s" % res.status_code)

        self.assertEqual(
            self._unread(), 0,
            "Mark all read left %d unread" % self._unread())

    def test_the_archive_still_shows_which_were_new_on_this_visit(self):
        """Not marking them read must not stop the page marking them NEW."""
        self._notify(title='Fresh notice')
        html = self._archive()
        self.assertIn(
            "mv-notif-card--unread", html,
            "nothing on the page distinguishes what she has not read")

    # -- 3. a schedule change looks like one -------------------------------

    def test_a_rescheduled_class_is_flagged_on_the_record(self):
        self.assertTrue(
            self._notify('class_rescheduled').is_schedule_change,
            "a moved class is not counted as changing her schedule")

    def test_a_cancelled_booking_and_a_swapped_teacher_are_too(self):
        self.assertTrue(
            self._notify('booking_cancelled').is_schedule_change,
            "a cancelled booking is not counted as a schedule change")
        self.assertTrue(
            self._notify('teacher_swap').is_schedule_change,
            "an instructor change is not counted as a schedule change")

    def test_an_invoice_is_not_a_schedule_change(self):
        """The negative. Without it everything could be flagged and pass."""
        self.assertFalse(
            self._notify('invoice_issued').is_schedule_change,
            "an invoice is being marked as a change to her schedule")
        self.assertFalse(
            self._notify('booking_confirmed').is_schedule_change,
            "a booking confirmation is a confirmation, not a change")

    def test_the_archive_marks_a_schedule_change_differently(self):
        self._notify('class_rescheduled', title='Your class has changed')
        html = self._archive()
        self.assertIn(
            "mv-notif-card--schedule", html,
            "a moved class renders as an ordinary card, so it looks like "
            "an invoice")

    def test_the_archive_does_not_mark_an_invoice_that_way(self):
        self._notify('invoice_issued', title='Your invoice')
        html = self._archive()
        self.assertNotIn(
            "mv-notif-card--schedule", html,
            "an invoice is being shown as a schedule change")

    def test_the_dropdown_payload_says_which_ones_changed_her_schedule(self):
        """The panel is built by the browser from this JSON.

        The field was already being sent and thrown away; the test is
        here so it cannot quietly stop being sent.
        """
        self._notify('class_rescheduled', title='Moved')
        self._notify('invoice_issued', title='Invoiced')

        self._login()
        rows = self.url_open("/my/notifications/data").json()['notifications']
        by_title = {r['title']: r for r in rows}

        self.assertTrue(
            by_title['Moved']['is_schedule_change'],
            "the panel is not told the class moved")
        self.assertFalse(
            by_title['Invoiced']['is_schedule_change'],
            "the panel is told an invoice changed her schedule")
