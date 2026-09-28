# -*- coding: utf-8 -*-
"""The studio's reason for moving somebody, written down.

Until now the reason existed only as a context value, and only long
enough to compose the in-app notification body. That notification is
guarded by

    user = booking.student_id.user_ids[:1]
    if not user:
        continue

so a student with no account never received one, and the reason was
discarded with it. The email never carried it for anybody.

Laura, 29 September 2026: moved from the 9am Barre class to the 10am one,
emailed correctly in Catalan, and nothing anywhere recorded why. She has
no account, so there was no notification for the reason to live in.

These pin the note on the booking's own chatter - the studio talking to
itself, for whoever asks next week. Both halves matter:

  * a reason given is recorded verbatim;
  * no reason given is recorded AS none, because a chatter that stays
    silent half the time cannot be read as a record at all - a missing
    note would be indistinguishable from a move nobody made.

And both are checked for a student with an account and for one without,
since the account is exactly what used to decide whether anything was
kept.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoveReasonRecorded(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Move Reason Room", "classroom_type": "barre",
            "capacity": 10,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Move Reason Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Move Reason Pack", "type": "service",
            "list_price": 100.0, "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

    # ── fixtures ────────────────────────────────────────────────────────────

    def _event(self, days=3, hour=9, name=None):
        start = (fields.Datetime.now() + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": name or "Move Reason class %02d:00" % hour,
            "start": start,
            "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True, "capacity": 10,
        })

    def _student(self, tag, with_account):
        """A student, with or without a login.

        The account is the whole point of the pair: it used to decide
        whether the reason survived.
        """
        if with_account:
            user = self.env["res.users"].with_context(
                no_reset_password=True).create({
                    "name": "Move Reason %s" % tag,
                    "login": "move.reason.%s@example.invalid" % tag,
                    "group_ids": [(6, 0, [
                        self.env.ref("base.group_portal").id,
                        self.env.ref(
                            "fitness_core.group_fitness_student").id,
                    ])],
                })
            return user.partner_id
        return self.env["res.partner"].create(
            {"name": "Move Reason %s" % tag, "email": False})

    def _booking(self, partner, event):
        order = self.env["sale.order"].sudo().create(
            {"partner_id": partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0,
        })
        order.action_confirm()
        line = order.order_line[:1]
        return self.env["fitness.booking"].sudo().create({
            "student_id": partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": line.id,
        })

    def _move(self, booking, target, reason=None):
        wizard = self.env["fitness.booking.reassign.wizard"].sudo().create({
            "booking_id": booking.id,
            "target_event_id": target.id,
            "reason": reason or False,
        })
        wizard.action_move_student()
        self.env.invalidate_all()
        return wizard

    def _notes(self, booking):
        return [
            (m.body or "") for m in booking.sudo().message_ids
            if m.subtype_id.name == "Note" or "Moved from" in (m.body or "")
        ]

    # ── a reason given, both kinds of student ───────────────────────────────

    def test_a_reason_is_recorded_for_a_student_with_an_account(self):
        partner = self._student("hasacct", with_account=True)
        origin, target = self._event(hour=9), self._event(hour=11)
        booking = self._booking(partner, origin)

        self._move(booking, target, reason="Nine o'clock was overbooked")

        joined = " ".join(self._notes(booking))
        self.assertIn(
            "Nine o'clock was overbooked", joined,
            "the studio's reason was not written to the booking")
        self.assertIn(
            target.name, joined,
            "the note does not say where she was moved to")

    def test_a_reason_is_recorded_for_a_student_with_no_account(self):
        """Laura's shape. This is the case that used to lose it entirely."""
        partner = self._student("noacct", with_account=False)
        self.assertFalse(
            partner.user_ids,
            "fixture wrong: she is supposed to have no account")
        origin, target = self._event(hour=9), self._event(hour=11)
        booking = self._booking(partner, origin)

        self._move(booking, target, reason="Teacher off sick")

        joined = " ".join(self._notes(booking))
        self.assertIn(
            "Teacher off sick", joined,
            "with no account there is no notification, and the reason was "
            "lost again - which is the whole bug")

    # ── no reason given, both kinds of student ──────────────────────────────

    def test_no_reason_is_recorded_as_none_with_an_account(self):
        partner = self._student("hasacct2", with_account=True)
        origin, target = self._event(hour=9), self._event(hour=11)
        booking = self._booking(partner, origin)

        self._move(booking, target, reason=None)

        joined = " ".join(self._notes(booking))
        self.assertIn(
            "No reason given", joined,
            "a move with no reason left no trace, so it cannot be told "
            "apart from a move nobody made")
        self.assertIn(target.name, joined)

    def test_no_reason_is_recorded_as_none_with_no_account(self):
        partner = self._student("noacct2", with_account=False)
        origin, target = self._event(hour=9), self._event(hour=11)
        booking = self._booking(partner, origin)

        self._move(booking, target, reason="   ")

        joined = " ".join(self._notes(booking))
        self.assertIn(
            "No reason given", joined,
            "whitespace was treated as a reason, so the note says nothing "
            "while looking as though it says something")

    # ── it is the studio's note, not hers ───────────────────────────────────

    def test_the_note_is_internal_and_the_move_still_happens(self):
        partner = self._student("internal", with_account=True)
        origin, target = self._event(hour=9), self._event(hour=11)
        booking = self._booking(partner, origin)

        self._move(booking, target, reason="Room swap")

        self.assertEqual(
            booking.calendar_event_id, target,
            "the note was written but the move did not happen")
        moved_notes = [
            m for m in booking.sudo().message_ids
            if "Moved from" in (m.body or "")
        ]
        self.assertTrue(moved_notes, "no note was posted at all")
        self.assertEqual(
            moved_notes[0].subtype_id,
            self.env.ref("mail.mt_note"),
            "the reason was posted as a public message - it is the studio's "
            "own record, and she has already been emailed")
