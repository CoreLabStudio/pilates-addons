# -*- coding: utf-8 -*-
"""Moving a student to another class must not go looking for a credit.

The wizard used to cancel the booking and create a new one. The new booking
then ran the ordinary payment-source check, found nothing - the credit had
just been handed back, and for a trial had never been a spendable pool line -
and refused with "No active subscription or package covers this class type",
on a booking that was already paid for. Being a manager did not help, because
that is a payment rule and not a permission.

A move now keeps the booking row and its credit line and only changes which
class it points at. These tests pin both halves: that the move works and
spends nothing, and that every rule which still matters is enforced, since
fitness.booking has no write() override to enforce them.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReassignWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")
        cls.manager = cls.env.ref("base.user_admin")

        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Move Test Student",
                "login": "move.test@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.student.partner_id

        cls.barre_type = cls._class_type("barre", "Barre Move Test")
        cls.reformer_type = cls._class_type("reformer", "Reformer Move Test")

        # Two barre classes to move between, and a reformer class the barre
        # credit must not be able to reach.
        cls.origin = cls._event(cls.barre_type, days=2)
        cls.target = cls._event(cls.barre_type, days=3)
        cls.other_discipline = cls._event(cls.reformer_type, days=3)

        cls.pack = cls._package("Barre Pack Move Test", 10, "barre")
        cls.order = cls._confirmed_order(cls.pack)
        cls.line = cls.order.order_line[:1]
        cls.booking = cls._book(cls.origin, cls.line)

    # ── fixtures ─────────────────────────────────────────────────────────────
    @classmethod
    def _class_type(cls, room, name):
        return cls.env["fitness.class.type"].create({
            "name": name, "classroom_type": room, "duration": 45,
            "level": "all", "session_type": "group",
        })

    @classmethod
    def _event(cls, class_type, days, capacity=10):
        start = fields.Datetime.now() + timedelta(days=days)
        return cls.env["calendar.event"].create({
            "name": "%s +%sd" % (class_type.name, days),
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": class_type.id,
            "is_fitness_class": True,
            "capacity": capacity,
        })

    @classmethod
    def _package(cls, name, count, class_type):
        return cls.env["product.template"].create({
            "name": name, "list_price": 100.0, "type": "service",
            "fitness_is_package": True,
            "fitness_class_count": count,
            "fitness_validity_days": 90,
            "fitness_class_type": class_type,
            "fitness_session_type": "group",
        })

    @classmethod
    def _confirmed_order(cls, tmpl):
        order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": tmpl.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": tmpl.list_price,
            "fitness_class_type": tmpl.fitness_class_type,
        })
        order.action_confirm()
        return order

    @classmethod
    def _book(cls, event, line):
        return cls.env["fitness.booking"].create({
            "student_id": cls.partner.id,
            "calendar_event_id": event.id,
            "package_order_line_id": line.id,
            "manager_override_timewindow": True,
        })

    def _wizard(self, booking=None, target=None):
        return self.env["fitness.booking.reassign.wizard"].with_user(
            self.manager).create({
                "booking_id": (booking or self.booking).id,
                "target_event_id": target.id if target else False,
            })

    def _occupy(self, event, suffix):
        """Fill a seat with a different student who has their own credit.

        They need a pack of their own: a booking with no credit is refused by
        the payment-source check, which is a rule under test elsewhere and
        merely scenery here.
        """
        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Occupant %s" % suffix,
            "login": "occupant%s@example.invalid" % suffix,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_portal").id,
                self.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        order = self.env["sale.order"].create({"partner_id": other.partner_id.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": self.pack.list_price,
            "fitness_class_type": self.pack.fitness_class_type,
        })
        order.action_confirm()
        return self.env["fitness.booking"].create({
            "student_id": other.partner_id.id,
            "calendar_event_id": event.id,
            "package_order_line_id": order.order_line[:1].id,
            "manager_override_timewindow": True,
        })

    # ── the move itself ──────────────────────────────────────────────────────
    def test_a_move_changes_the_class_and_nothing_else(self):
        before = self.line.fitness_remaining_classes
        self._wizard(target=self.target).action_move_student()
        self.assertEqual(self.booking.calendar_event_id, self.target)
        self.assertEqual(self.booking.state, "booked")
        self.assertEqual(
            self.booking.package_order_line_id, self.line,
            "the move must keep the credit line it was already paid from")
        self.assertEqual(
            self.line.fitness_remaining_classes, before,
            "a move is not a sale: no credit returned, none spent")

    def test_a_move_does_not_cancel_the_booking(self):
        self._wizard(target=self.target).action_move_student()
        self.assertNotEqual(self.booking.state, "cancelled")

    def test_seat_counts_follow_the_student(self):
        self._wizard(target=self.target).action_move_student()
        self.origin.invalidate_recordset()
        self.target.invalidate_recordset()
        self.assertEqual(self.origin.booked_seats, 0)
        self.assertEqual(self.target.booked_seats, 1)

    # ── the rules a plain write() would have skipped ─────────────────────────
    def test_it_refuses_a_class_the_credit_does_not_cover(self):
        with self.assertRaises(UserError):
            self._wizard(target=self.other_discipline).action_move_student()
        self.assertEqual(self.booking.calendar_event_id, self.origin)

    def test_it_refuses_a_full_class(self):
        full = self._event(self.barre_type, days=4, capacity=1)
        self._occupy(full, "a")
        with self.assertRaises(UserError):
            self._wizard(target=full).action_move_student()
        self.assertEqual(self.booking.calendar_event_id, self.origin)

    def test_it_refuses_a_class_that_has_started(self):
        past = self._event(self.barre_type, days=2)
        past.start = fields.Datetime.now() - timedelta(hours=1)
        with self.assertRaises(UserError):
            self._wizard(target=past).action_move_student()

    def test_it_refuses_a_cancelled_class(self):
        dead = self._event(self.barre_type, days=4)
        dead.class_state = "cancelled"
        with self.assertRaises(UserError):
            self._wizard(target=dead).action_move_student()

    def test_it_refuses_moving_into_the_same_class(self):
        with self.assertRaises(UserError):
            self._wizard(target=self.origin).action_move_student()

    def test_it_refuses_when_already_booked_into_the_target(self):
        second = self._book(self.target, self.line)
        self.assertTrue(second)
        with self.assertRaises(UserError):
            self._wizard(target=self.target).action_move_student()

    def test_it_refuses_an_overlapping_booking(self):
        clash = self._event(self.barre_type, days=3)
        clash.start = self.target.start
        clash.stop = self.target.stop
        self._book(clash, self.line)
        with self.assertRaises(UserError):
            self._wizard(target=self.target).action_move_student()

    def test_it_refuses_an_already_cancelled_booking(self):
        self.booking.with_context(
            _admin_cancel_direct=True, admin_force_refund=True).action_cancel()
        with self.assertRaises(UserError):
            self._wizard(target=self.target).action_move_student()

    def test_it_refuses_with_no_target_chosen(self):
        with self.assertRaises(UserError):
            self._wizard().action_move_student()

    # ── the dropdown only offers what will work ──────────────────────────────
    def test_the_dropdown_excludes_classes_the_credit_cannot_cover(self):
        wiz = self._wizard()
        offered = wiz.available_event_ids
        self.assertIn(self.target, offered)
        self.assertNotIn(
            self.other_discipline, offered,
            "a reformer class must not be offered to a barre credit")
        self.assertNotIn(self.origin, offered,
                         "the class they are already in is not a move")

    def test_the_dropdown_excludes_full_classes(self):
        full = self._event(self.barre_type, days=4, capacity=1)
        self._occupy(full, "b")
        self.assertNotIn(full, self._wizard().available_event_ids)

    # ── the student has to hear about it ─────────────────────────────────────
    def test_a_move_tells_the_student(self):
        """Being moved happens *to* a student; silence means a wasted trip.

        The bell and the mail both go out, and the bell names the class so the
        notification is useful on its own rather than only as a prompt to go
        and look.
        """
        Notif = self.env['fitness.notification']
        user = self.student
        before = Notif.search_count([('user_id', '=', user.id)])
        mails_before = self.env['mail.mail'].search_count([])

        self._wizard(target=self.target).action_move_student()

        self.assertEqual(
            Notif.search_count([('user_id', '=', user.id)]), before + 1,
            "a move must ring the student's bell")
        latest = Notif.search([('user_id', '=', user.id)], order='id desc', limit=1)
        self.assertEqual(latest.notification_type, 'class_rescheduled')
        self.assertIn(self.target.name, latest.body or '',
                      "the notification should say which class they are in now")
        self.assertTrue(latest.action_url, "it should open somewhere useful")
        self.assertGreater(
            self.env['mail.mail'].search_count([]), mails_before,
            "a move must queue the email as well as the bell")

    def test_the_move_email_has_a_recipient(self):
        """An email with no recipient is not an email.

        The template addresses the student with partner_to, which leaves
        email_to empty and fills recipient_ids instead - so the check that
        matters is the one on recipient_ids.
        """
        self._wizard(target=self.target).action_move_student()
        mail = self.env['mail.mail'].search([], order='id desc', limit=1)
        self.assertIn(self.partner, mail.recipient_ids)

    # ── what the button hands back to the web client ─────────────────────────
    #
    # These exist because the move passed every model-level test and still
    # failed in the real UI. Both methods returned
    # {'type': 'ir.actions.act_window_closed'} - with a 'd' - which is not an
    # action type Odoo knows. Calling the method directly never notices;
    # /web/dataset/call_button validates what a button returns, raised on it,
    # and the raise rolled the transaction back, so a move that had just
    # succeeded was undone and the desk saw an error.
    #
    # A test that calls the method cannot exercise call_button, but it can
    # refuse to let the method return something a button could not accept.
    VALID_CLOSE = 'ir.actions.act_window_close'

    def test_move_returns_an_action_the_client_accepts(self):
        res = self._wizard(target=self.target).action_move_student()
        self.assertIsInstance(res, dict)
        self.assertEqual(
            res.get('type'), self.VALID_CLOSE,
            "a button's return value is validated by call_button; an unknown "
            "action type rolls back the work the button just did")

    def test_cancel_only_returns_an_action_the_client_accepts(self):
        res = self._wizard().action_cancel_only()
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get('type'), self.VALID_CLOSE)

    # ── the trial, which is the case that actually failed ────────────────────
    def test_a_trial_booking_can_be_moved(self):
        """The reported bug, on the real trial product.

        A trial was the worst case for cancel-then-rebook: cancelling it
        releases the claim and leaves no spendable pool line at all, so the
        replacement booking had nothing to pay with and the desk was told the
        student had no package - about a trial the student was sitting on.
        """
        trial_tmpl = self.env.ref(
            "fitness_packages.product_barre_trial", raise_if_not_found=False)
        if not trial_tmpl:
            self.skipTest("trial product not present in this database")

        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": trial_tmpl.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": 0.0,
            "fitness_class_type": trial_tmpl.fitness_class_type,
        })
        order.action_confirm()
        trial_line = order.order_line[:1]

        # Days nothing else in this class occupies: the student already holds
        # the +2d booking from setUpClass, and an overlap is a different rule.
        origin = self._event(self.barre_type, days=6)
        target = self._event(self.barre_type, days=7)
        booking = self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": origin.id,
            "package_order_line_id": trial_line.id,
            "manager_override_timewindow": True,
        })
        remaining = trial_line.fitness_remaining_classes

        self._wizard(booking=booking, target=target).action_move_student()

        self.assertEqual(booking.calendar_event_id, target)
        self.assertNotEqual(booking.state, "cancelled")
        self.assertEqual(
            booking.package_order_line_id, trial_line,
            "the trial claim must stay on the booking that holds it")
        self.assertEqual(
            trial_line.fitness_remaining_classes, remaining,
            "moving a trial must not hand the trial back")
        self.assertEqual(
            order.state, "sale",
            "the trial order must stay confirmed through a move")

    # ── cancel-only is untouched ─────────────────────────────────────────────
    def test_cancel_only_still_cancels_and_returns_the_credit(self):
        before = self.line.fitness_remaining_classes
        wiz = self._wizard()
        wiz.restore_credit = True
        wiz.action_cancel_only()
        self.assertEqual(self.booking.state, "cancelled")
        self.assertEqual(self.line.fitness_remaining_classes, before + 1)


@tagged("post_install", "-at_install")
class TestDirectMoveKeepsSeatsHonest(TransactionCase):
    """Moving a booking by editing the field, not through the wizard.

    The third route. Deleting a booking recounted, and the wizard recounted,
    but typing a new class straight into calendar_event_id did neither - so
    the class being left kept the seat and the class being joined never
    gained it. Found on production: one edit left Barre Groove reading 1 with
    nobody on it and Barre Harmony reading 1 with two students on it.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Drift room", "classroom_type": "barre", "capacity": 8})
        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Drift Barre", "classroom_type": "barre", "duration": 45,
            "level": "all", "session_type": "group",
            "classroom_id": cls.room.id})
        cls.student = cls.env["res.users"].create({
            "name": "Drift Student",
            "login": "drift.student@example.invalid",
            "email": "drift.student@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id])]})
        pack = cls.env["product.template"].create({
            "name": "Drift pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group"})
        order = cls.env["sale.order"].create(
            {"partner_id": cls.student.partner_id.id})
        cls.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0,
            "fitness_class_type": "barre"})
        order.action_confirm()
        cls.line = order.order_line[:1]

    def _class(self, name, days=4):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": name, "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id, "is_fitness_class": True})

    def _book(self, event):
        return self.env["fitness.booking"].create({
            "student_id": self.student.partner_id.id,
            "calendar_event_id": event.id,
            "package_order_line_id": self.line.id,
            "manager_override_timewindow": True})

    def test_a_direct_edit_moves_the_seat_with_the_student(self):
        origin, target = self._class("Left behind"), self._class("Joined")
        booking = self._book(origin)
        origin.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 1, "fixture is wrong")

        booking.write({"calendar_event_id": target.id})

        origin.invalidate_recordset(); target.invalidate_recordset()
        self.assertEqual(
            origin.booked_seats, 0,
            "the class she left kept her seat - it shows fuller than it is")
        self.assertEqual(
            target.booked_seats, 1,
            "the class she joined never gained the seat - it shows a free "
            "place that is already taken")

    def test_the_wizard_still_recounts_both(self):
        """It delegates to write() now; the outcome must not have changed."""
        origin, target = self._class("Wizard from"), self._class("Wizard to")
        booking = self._book(origin)

        self.env["fitness.booking.reassign.wizard"].create({
            "booking_id": booking.id, "target_event_id": target.id,
        }).action_move_student()

        origin.invalidate_recordset(); target.invalidate_recordset()
        self.assertEqual(origin.booked_seats, 0)
        self.assertEqual(target.booked_seats, 1)

    def test_the_student_is_told_once_not_twice(self):
        """The wizard used to notify and now the write does. Doing both would
        send two messages about one move."""
        origin, target = self._class("Told from"), self._class("Told to")
        booking = self._book(origin)
        before = len(booking.message_ids)

        self.env["fitness.booking.reassign.wizard"].create({
            "booking_id": booking.id, "target_event_id": target.id,
        }).action_move_student()

        booking.invalidate_recordset()
        moved = [m for m in booking.message_ids
                 if "cambiado" in (m.subject or "").lower()
                 or "moved" in (m.subject or "").lower()
                 or "canviat" in (m.subject or "").lower()]
        self.assertLessEqual(
            len(moved), 1,
            "the student was told twice about a single move")
        self.assertGreater(len(booking.message_ids), before,
                           "nothing at all was posted about the move")

    def test_writing_something_else_does_not_recount(self):
        """Only a change of class touches the counters."""
        event = self._class("Untouched")
        booking = self._book(event)
        event.invalidate_recordset()

        booking.write({"manager_override_timewindow": True})

        event.invalidate_recordset()
        self.assertEqual(event.booked_seats, 1)

    def test_rewriting_the_same_class_is_not_a_move(self):
        """A no-op write must not tell anybody they have been moved."""
        event = self._class("Same class")
        booking = self._book(event)
        before = len(booking.message_ids)

        booking.write({"calendar_event_id": event.id})

        booking.invalidate_recordset(); event.invalidate_recordset()
        self.assertEqual(event.booked_seats, 1)
        self.assertEqual(len(booking.message_ids), before,
                         "a write that moved nothing announced a move")


@tagged("post_install", "-at_install")
class TestAManagerWhoIsNotAnAdministratorCanMove(TransactionCase):
    """The move as the studio's own staff actually run it.

    Every other test here runs as base.user_admin, who can read anything. A
    fitness manager cannot: group_fitness_manager grants nothing on
    sale.order.line, so reading the credit behind the booking raised

        AccessError: You are not allowed to access 'Sales Order Line'

    and the move failed for every manager except the owner, whose account
    happens to be an administrator. It therefore worked in her hands and
    nowhere else, which is the shape of the "no roster" report: somebody
    tried to move a student, it failed, and the class looked wrong after.
    """

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("fitness.opening_date", "")

        cls.manager = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Desk Manager",
                "login": "desk.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_user").id,
                    cls.env.ref("fitness_core.group_fitness_manager").id,
                ])],
            })
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Moved By Manager",
                "login": "moved.by.manager@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        cls.partner = cls.student.partner_id

        cls.ctype = cls.env["fitness.class.type"].create({
            "name": "Manager Move Barre", "classroom_type": "barre",
            "duration": 45, "level": "all", "session_type": "group",
        })
        cls.origin = cls._mkevent(cls, "Origin", 4)
        cls.target = cls._mkevent(cls, "Target", 5)

        cls.pack = cls.env["product.template"].create({
            "name": "Manager Move Pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "barre",
            "fitness_session_type": "group",
        })
        order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": cls.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0,
            "fitness_class_type": "barre",
        })
        order.action_confirm()
        cls.booking = cls.env["fitness.booking"].create({
            "student_id": cls.partner.id,
            "calendar_event_id": cls.origin.id,
            "package_order_line_id": order.order_line[:1].id,
            "manager_override_timewindow": True,
        })

    def _mkevent(self, label, days):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env["calendar.event"].create({
            "name": "Manager Move %s" % label,
            "start": start, "stop": start + timedelta(minutes=45),
            "class_type_id": self.ctype.id,
            "is_fitness_class": True, "capacity": 10,
        })

    def test_the_fixture_manager_really_cannot_read_a_credit_line(self):
        """Without this the rest proves nothing: if the fixture happened to
        grant sales rights, the move would pass for the wrong reason."""
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env["sale.order.line"].with_user(
                self.manager).check_access("read")

    def test_a_manager_can_move_a_student(self):
        """The failure the studio hit. Cache invalidated first, because the
        fixture was built by admin and a cached value would answer the read
        without ever consulting the manager's rights - the exact way six
        renewal tests once passed while the feature was broken."""
        self.env.invalidate_all()
        wizard = self.env["fitness.booking.reassign.wizard"].with_user(
            self.manager).create({
                "booking_id": self.booking.id,
                "target_event_id": self.target.id,
            })
        wizard.action_move_student()

        self.assertEqual(self.booking.calendar_event_id, self.target,
                         "the manager's move did not take effect")

    def test_the_roster_moves_with_the_student(self):
        """The complaint in its own terms: the student leaves one roster and
        appears on the other, and is still booked."""
        self.env.invalidate_all()
        self.env["fitness.booking.reassign.wizard"].with_user(
            self.manager).create({
                "booking_id": self.booking.id,
                "target_event_id": self.target.id,
            }).action_move_student()

        self.assertIn(self.booking, self.target.booking_ids,
                      "missing from the new class roster")
        self.assertNotIn(self.booking, self.origin.booking_ids,
                         "still on the old class roster")
        self.assertEqual(self.booking.state, "booked",
                         "the booking is no longer booked, which is what "
                         "would empty a roster")

    def test_the_credit_rules_still_bite_for_a_manager(self):
        """sudo is for reading the pool, not for waiving the rule it feeds.
        A Barre credit must still refuse a Reformer class, whoever asks."""
        reformer = self.env["fitness.class.type"].create({
            "name": "Manager Move Reformer", "classroom_type": "reformer",
            "duration": 45, "level": "all", "session_type": "group",
        })
        start = fields.Datetime.now() + timedelta(days=6)
        other = self.env["calendar.event"].create({
            "name": "Manager Move Reformer Class",
            "start": start, "stop": start + timedelta(minutes=45),
            "class_type_id": reformer.id,
            "is_fitness_class": True, "capacity": 10,
        })
        self.env.invalidate_all()
        wizard = self.env["fitness.booking.reassign.wizard"].with_user(
            self.manager).create({
                "booking_id": self.booking.id,
                "target_event_id": other.id,
            })
        with self.assertRaises(UserError):
            wizard.action_move_student()
