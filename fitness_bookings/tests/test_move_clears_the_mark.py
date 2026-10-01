# -*- coding: utf-8 -*-
"""Moving somebody forward takes the old class's mark off them.

Agostina marked Marta a no-show for 29 September 2026. Yoly then moved
her to the class on 2 October. The move worked and the seat moved with
it, but the no-show stayed on the booking: Marta stood recorded as
having missed a class that had not happened yet, three days before it
ran, and nothing in the interface would take it back.

The mark belongs to the class the student was pulled out of. It does
not travel with her to a class that has not happened.

Only forward, and only while the class is still to come. A mark on a
class that has already run is a record of what happened in the room, and
a move - however it is made - must not quietly rewrite it.

Each case is pinned from both sides: the state that must appear, and
the state that must not survive. A test that only checks the new value
passes just as happily when nothing was ever wrong.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoveClearsTheMark(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Mark Room", "classroom_type": "barre", "capacity": 10,
        })
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Mark Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id,
        })
        cls.pack = cls.env["product.template"].create({
            "name": "Mark Pack", "type": "service",
            "list_price": 100.0, "sale_ok": True,
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })

    # -- fixtures ----------------------------------------------------------

    def _event(self, days=3, hour=9, name=None):
        """A class, by default still to come. days<0 puts it behind us.

        The class a booking is CREATED on must be in the future.
        _validate_new_booking refuses outright - "Cannot book a class that
        has already started or passed" - so a fixture that marks somebody
        absent cannot do it on a class in the past; it marks a future one,
        which a manager is allowed to do.

        The first version of this used days=0, hour=9 to get something
        that read as markable. That is the clock, not a constant: it
        passed before 09:00 and errored every test in the file after it.
        Nothing here depends on the time of day any more.
        """
        start = (fields.Datetime.now() + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        return self.env["calendar.event"].sudo().create({
            "name": name or "Mark class %+d day %02d:00" % (days, hour),
            "start": start,
            "stop": start + timedelta(minutes=55),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True, "capacity": 10,
        })

    def _student(self, tag):
        user = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Mark %s" % tag,
                "login": "mark.%s@example.invalid" % tag,
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        return user.partner_id

    def _booking(self, partner, event):
        order = self.env["sale.order"].sudo().create(
            {"partner_id": partner.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0,
        })
        order.action_confirm()
        return self.env["fitness.booking"].sudo().create({
            "student_id": partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": order.order_line[:1].id,
        })

    def _move(self, booking, target, reason=None):
        """Through the wizard - the route Yoly actually used."""
        self.env["fitness.booking.reassign.wizard"].sudo().create({
            "booking_id": booking.id,
            "target_event_id": target.id,
            "reason": reason or False,
        }).action_move_student()
        self.env.invalidate_all()

    def _notices(self, partner):
        return self.env["fitness.notification"].sudo().search_count([
            ("user_id", "in", partner.user_ids.ids),
            ("notification_type", "=", "class_rescheduled"),
        ])

    # -- 1. Marta, end to end ----------------------------------------------

    def test_a_no_show_moved_forward_is_booked_again(self):
        partner = self._student("marta")
        origin, target = self._event(days=1, hour=9), self._event(days=3)
        booking = self._booking(partner, origin)
        booking.action_mark_no_show()
        self.assertEqual(booking.state, "no_show", "fixture wrong")

        self._move(booking, target)

        self.assertEqual(
            booking.state, "booked",
            "Marta was moved to a class three days away and is still "
            "carrying the no-show from the class she was taken out of. "
            "She is recorded as having missed a class that has not run.")

    def test_a_no_show_moved_forward_does_not_survive_the_move(self):
        """The other half: not merely booked, but no longer a no-show."""
        partner = self._student("marta2")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_no_show()

        self._move(booking, self._event(days=4))

        self.assertNotEqual(
            booking.state, "no_show",
            "the no-show followed her into the new class")

    # -- 2. attended -------------------------------------------------------

    def test_attended_moved_forward_is_booked_again(self):
        partner = self._student("attended")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_attended()
        self.assertEqual(booking.state, "attended", "fixture wrong")

        self._move(booking, self._event(days=5))

        self.assertEqual(
            booking.state, "booked",
            "she is recorded as having attended a class that has not "
            "happened yet")

    def test_attended_is_not_left_on_a_class_she_has_not_had(self):
        partner = self._student("attended2")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_attended()

        self._move(booking, self._event(days=5))

        self.assertNotEqual(booking.state, "attended", "the mark travelled")

    # -- 3. the mark itself, not just the state ----------------------------

    def test_who_marked_her_is_cleared_too(self):
        """A booking still reading "Marked by Agostina" is still marked.

        Resetting the state and leaving the stamp behind would show a
        booked class with an attendance record attached to it, which is
        what a teacher reads as already dealt with.
        """
        partner = self._student("stamp")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_no_show()
        self.assertTrue(booking.marked_by_id, "fixture wrong")
        self.assertTrue(booking.marked_date, "fixture wrong")

        self._move(booking, self._event(days=3))

        self.assertFalse(
            booking.marked_by_id,
            "the booking is booked again but still says who marked her")
        self.assertFalse(
            booking.marked_date,
            "the booking is booked again but still says when")

    def test_an_unmarked_booking_gains_no_mark_from_being_moved(self):
        partner = self._student("plain")
        booking = self._booking(partner, self._event(days=2))

        self._move(booking, self._event(days=6))

        self.assertEqual(
            booking.state, "booked", "an ordinary move changed her state")
        self.assertFalse(
            booking.marked_by_id,
            "moving an unmarked booking invented an attendance record")

    # -- 4. backwards: a class that has already run ------------------------

    def test_a_mark_on_a_class_that_already_ran_is_left_alone(self):
        """Written straight onto the field, because the wizard cannot.

        _validate_move refuses a target that has started, so this is the
        booking form's own route - typing a different class into
        calendar_event_id. It must not rewrite history either.
        """
        partner = self._student("past")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_attended()
        gone = self._event(days=-7, hour=10)

        booking.write({"calendar_event_id": gone.id})

        self.assertEqual(
            booking.state, "attended",
            "moving her between two classes that have already run erased "
            "the record of her turning up to one of them")
        self.assertTrue(
            booking.marked_by_id,
            "the attendance stamp on a past class was cleared")

    def test_the_wizard_refuses_a_class_that_has_already_started(self):
        """The guard this behaviour leans on, pinned where it lives."""
        partner = self._student("past2")
        booking = self._booking(partner, self._event(days=2))

        with self.assertRaises(UserError):
            self._move(booking, self._event(days=-7, hour=10))

    # -- 5. a cancelled booking is not revived -----------------------------

    def test_a_cancelled_booking_is_not_booked_again_by_a_move(self):
        partner = self._student("cancelled")
        booking = self._booking(partner, self._event(days=2))
        booking.write({"state": "cancelled"})

        booking.write({"calendar_event_id": self._event(days=6).id})

        self.assertEqual(
            booking.state, "cancelled",
            "a cancelled booking was quietly booked again by being moved; "
            "she would hold a class she had given up")

    def test_a_state_named_in_the_same_write_wins(self):
        """Cancel-and-move says cancelled and means it."""
        partner = self._student("both")
        booking = self._booking(partner, self._event(days=1, hour=9))
        booking.action_mark_no_show()

        booking.write({
            "calendar_event_id": self._event(days=6).id,
            "state": "cancelled",
        })

        self.assertEqual(
            booking.state, "cancelled",
            "the reset overrode a state the caller had asked for")

    # -- 6. the seats, on a combined write ---------------------------------

    def test_the_seat_comes_back_with_her(self):
        """A no-show holds no seat; booked again, she does.

        The move and the reset happen in one write, so both counters have
        to be right afterwards - the class she left and the class she
        joined, in opposite directions.
        """
        partner = self._student("seats")
        origin, target = self._event(days=1, hour=9), self._event(days=3)
        booking = self._booking(partner, origin)
        booking.action_mark_no_show()
        origin.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 0, "fixture wrong")

        self._move(booking, target)
        origin.invalidate_recordset()
        target.invalidate_recordset()

        self.assertEqual(
            target.booked_seats, 1,
            "she is booked into the new class and it still reads empty; "
            "the roster and the counter disagree")
        self.assertEqual(
            origin.booked_seats, 0,
            "the class she left gained a seat she never held")

    def test_an_ordinary_move_still_moves_one_seat(self):
        """The negative: the reset must not double-count anybody."""
        partner = self._student("seats2")
        origin, target = self._event(days=2), self._event(days=6)
        booking = self._booking(partner, origin)
        origin.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 1, "fixture wrong")

        self._move(booking, target)
        origin.invalidate_recordset()
        target.invalidate_recordset()

        self.assertEqual(origin.booked_seats, 0, "the seat stayed behind")
        self.assertEqual(target.booked_seats, 1, "the seat arrived twice")

    # -- 7. several at once, mixed states ----------------------------------

    def test_a_mixed_batch_each_lands_on_its_own_state(self):
        """A roster moved wholesale: one marked, one not.

        Odoo writes one set of values to every record in the set, so the
        reset has to split the batch. Getting this wrong books the
        unmarked one twice or leaves the marked one marked.
        """
        marked = self._booking(self._student("batch_a"),
                               self._event(days=1, hour=9))
        plain = self._booking(self._student("batch_b"),
                              self._event(days=1, hour=9))
        marked.action_mark_no_show()
        target = self._event(days=4)

        (marked | plain).write({"calendar_event_id": target.id})
        target.invalidate_recordset()

        self.assertEqual(
            marked.state, "booked", "the marked booking kept its no-show")
        self.assertEqual(
            plain.state, "booked", "the unmarked booking changed state")
        self.assertEqual(
            target.booked_seats, 2,
            "two students were moved in and the class counts %d"
            % target.booked_seats)

    def test_a_mixed_batch_tells_each_student_once(self):
        """Splitting the write must not write anybody twice.

        A record written twice is notified twice, and the student reads
        two messages about one move.
        """
        a, b = self._student("told_a"), self._student("told_b")
        marked = self._booking(a, self._event(days=1, hour=9))
        plain = self._booking(b, self._event(days=1, hour=9))
        marked.action_mark_no_show()

        (marked | plain).write(
            {"calendar_event_id": self._event(days=4).id})

        self.assertEqual(
            self._notices(a), 1,
            "the student whose mark was reset was told %d times about one "
            "move" % self._notices(a))
        self.assertEqual(
            self._notices(b), 1,
            "the student moved alongside her was told %d times"
            % self._notices(b))
