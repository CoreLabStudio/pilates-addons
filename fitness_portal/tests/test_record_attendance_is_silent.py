# -*- coding: utf-8 -*-
"""Recording an attendance tells nobody. Proved by counting, not by a flag.

She was there. Emailing her hours later to say she has been booked onto
a class she already took is noise, and telling the instructor is worse -
it reads as a new booking appearing on a class that is over.

This asserts silence the only way worth trusting: every channel counted
before and after, for the student AND the instructor, with the real push
function patched so a call would be caught rather than assumed absent.
A single flag assertion would have passed on the day a booking
confirmation leaked to a real student, because the flag was right and
the call site was not.

The whole path is covered in one go - creating the booking, marking it
attended, spending the credit, and the chatter note - and the attended
mark is also checked on its own, because it is a separate notification
path from create().
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 11, 4, 18, 0, 0)       # Wednesday, 19:00 Madrid

MANAGER = "fitness_core.group_fitness_manager"
TEACHER = "fitness_core.group_fitness_teacher"
STUDENT = "fitness_core.group_fitness_student"


@tagged("post_install", "-at_install")
class TestRecordAttendanceIsSilent(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.record_attendance_days", "14")
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "RA Barre", "classroom_type": "barre", "duration": 50,
            "level": "all", "session_type": "group"})
        cls.pack = cls.env["product.template"].create({
            "name": "RA Barre pack 5", "list_price": 100.0,
            "type": "service", "fitness_is_package": True,
            "fitness_class_count": 5, "fitness_validity_days": 120,
            "fitness_class_type": "barre", "fitness_session_type": "group"})

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        # A keypair and devices, so a push that would leave is counted
        # rather than skipped for want of somewhere to send it.
        Param = self.env["ir.config_parameter"].sudo()
        Param.set_param(PARAM_PUBLIC, "pub-for-test")
        Param.set_param(PARAM_PRIVATE, "priv-for-test")
        Param.set_param("database.is_neutralized", "False")
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

    # -- people ------------------------------------------------------
    def _user(self, tag, groups, portal=False):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "RA %s" % tag,
                "login": "ra.%s@example.invalid" % tag,
                "email": "ra.%s@example.invalid" % tag,
                "lang": "en_US", "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [self.env.ref(g).id for g in groups])]})
        self.env["fitness.push.subscription"]._register_device(
            user.id, "https://push.example.invalid/ra.%s" % tag,
            "pub", "auth")
        return user

    def _manager(self):
        return self._user("manager", ["base.group_user", MANAGER])

    def _teacher(self):
        return self._user("teacher", ["base.group_user", TEACHER])

    def _student(self):
        return self._user("student", ["base.group_portal", STUDENT])

    def _past_class(self, teacher, hours_ago=20):
        """A class that has happened, taught by someone."""
        start = fields.Datetime.now() + timedelta(hours=30)
        event = self.env["calendar.event"].sudo().create({
            "name": "RA past class", "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id, "is_fitness_class": True,
            "capacity": 6, "session_type": "group", "user_id": teacher.id})
        past = fields.Datetime.now() - timedelta(hours=hours_ago)
        event.sudo().write({"start": past,
                            "stop": past + timedelta(minutes=50)})
        return event

    def _pack_for(self, student):
        order = self.env["sale.order"].sudo().create({
            "partner_id": student.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": self.pack.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 100.0,
                "fitness_class_type": "barre"})]})
        order.action_confirm()
        return order.order_line[:1]

    # -- the counting ------------------------------------------------
    def _counts(self, *partners):
        """Every channel anybody could be reached on, as plain numbers."""
        ids = [p.id for p in partners]
        return {
            "mail.mail": self.env["mail.mail"].sudo().search_count([]),
            "mail.message": self.env["mail.message"].sudo().search_count(
                [("message_type", "!=", "notification")]),
            "mail.notification": self.env["mail.notification"].sudo(
                ).search_count([("res_partner_id", "in", ids)]),
            "fitness.notification": self.env["fitness.notification"].sudo(
                ).search_count(
                    [("user_id", "in",
                      [u.id for p in partners for u in p.user_ids])]),
        }

    def _record(self, manager, event, student, pay_with="existing"):
        wizard = self.env["fitness.record.attendance.wizard"].with_user(
            manager).create({
                "calendar_event_id": event.id,
                "student_id": student.partner_id.id,
                "pay_with": pay_with,
                "reason": "She walked in and took the class."})
        return wizard.action_record()

    # == the whole path, counted =====================================
    def test_nothing_is_sent_to_anybody_end_to_end(self):
        manager, teacher, student = (
            self._manager(), self._teacher(), self._student())
        event = self._past_class(teacher)
        line = self._pack_for(student)
        spent_before = line.fitness_remaining_classes

        before = self._counts(student.partner_id, teacher.partner_id)
        self.env.flush_all()

        sent = []
        with patch.object(web_push, "send",
                          lambda *a, **k: sent.append(a) or (200, "")):
            self._record(manager, event, student)
            self.env.flush_all()

        after = self._counts(student.partner_id, teacher.partner_id)

        self.assertEqual(
            sent, [],
            "a web push was actually sent - %d call(s). The guard was "
            "trusted and the call site was not." % len(sent))
        for channel in sorted(before):
            self.assertEqual(
                after[channel], before[channel],
                "%s went from %d to %d. Somebody was told about a class "
                "that had already happened."
                % (channel, before[channel], after[channel]))

        # and it actually did the work it was meant to
        line.invalidate_recordset()
        self.assertEqual(
            line.fitness_remaining_classes, spent_before - 1,
            "the credit was not spent, so nothing was recorded at all")
        booking = self.env["fitness.booking"].sudo().search(
            [("calendar_event_id", "=", event.id),
             ("student_id", "=", student.partner_id.id)])
        self.assertEqual(booking.state, "attended")

    def test_the_attended_mark_on_its_own_sends_nothing(self):
        """A separate notification path from create(), so counted alone."""
        manager, teacher, student = (
            self._manager(), self._teacher(), self._student())
        event = self._past_class(teacher)
        self._pack_for(student)
        self._record(manager, event, student)
        self.env.flush_all()

        booking = self.env["fitness.booking"].sudo().search(
            [("calendar_event_id", "=", event.id),
             ("student_id", "=", student.partner_id.id)])
        booking.sudo().write({"state": "booked"})
        self.env.flush_all()

        before = self._counts(student.partner_id, teacher.partner_id)
        sent = []
        with patch.object(web_push, "send",
                          lambda *a, **k: sent.append(a) or (200, "")):
            booking.with_context(
                skip_fitness_notification=True).sudo().write(
                    {"state": "attended"})
            self.env.flush_all()
        after = self._counts(student.partner_id, teacher.partner_id)

        self.assertEqual(sent, [], "marking attended sent a push")
        for channel in sorted(before):
            self.assertEqual(
                after[channel], before[channel],
                "marking attended moved %s from %d to %d"
                % (channel, before[channel], after[channel]))

    def test_the_chatter_note_is_written_without_notifying_her(self):
        """The note has to exist - it is the only record of why."""
        manager, teacher, student = (
            self._manager(), self._teacher(), self._student())
        event = self._past_class(teacher)
        self._pack_for(student)

        before = self._counts(student.partner_id, teacher.partner_id)
        self._record(manager, event, student)
        self.env.flush_all()
        after = self._counts(student.partner_id, teacher.partner_id)

        booking = self.env["fitness.booking"].sudo().search(
            [("calendar_event_id", "=", event.id),
             ("student_id", "=", student.partner_id.id)])
        bodies = " ".join(booking.message_ids.mapped("body") or [])
        self.assertIn(
            "walked in", bodies,
            "the reason was not written to the chatter, so nothing records "
            "why this booking exists")
        self.assertEqual(
            after["mail.notification"], before["mail.notification"],
            "the chatter note notified her")

    # == the bite: take the suppression away and the counts move =====
    def test_without_the_suppression_the_counts_would_move(self):
        """Proves the counting above can fail.

        The same booking, created the same way, WITHOUT
        skip_fitness_notification. If this does not move a counter, the
        tests above are measuring nothing.
        """
        manager, teacher, student = (
            self._manager(), self._teacher(), self._student())
        event = self._past_class(teacher)
        line = self._pack_for(student)

        self.env.flush_all()
        before = self._counts(student.partner_id, teacher.partner_id)

        self.env["fitness.booking"].sudo().with_context(
            fitness_record_past_attendance=True,
        ).create({
            "student_id": student.partner_id.id,
            "calendar_event_id": event.id,
            "package_order_line_id": line.id,
            "manager_override_timewindow": True,
        })
        self.env.flush_all()
        after = self._counts(student.partner_id, teacher.partner_id)

        moved = [c for c in before if after[c] != before[c]]
        self.assertTrue(
            moved,
            "creating a booking WITHOUT the suppression notified nobody "
            "either, so the silence tests above prove nothing: %s -> %s"
            % (before, after))
