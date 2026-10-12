# -*- coding: utf-8 -*-
"""The engine spends only what the shared spendable rule allows.

A cancelled order's credits were hidden from the student's balance and
still spent by _select_payment_source, which had its own domain with no
order-state filter. Reproduced on a built copy: order state=cancel,
balance 0, booking succeeded charged to that line. On production one
student held three such classes.

The engine now searches sale.order.line._fitness_spendable_domain. These
tests pin what that changes and, as much, what it must not: a live line,
a locked order and a never-expiring line all still pay.

Clock pinned, language explicit, every record built here.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

# A Wednesday, clear of month ends and of the 25 October clock change.
PINNED = datetime(2026, 11, 4, 8, 0, 0)


class SpendableFixture(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        self.class_type = self.env["fitness.class.type"].create({
            "name": "SP Reformer", "classroom_type": "reformer",
            "duration": 50, "level": "all", "session_type": "group",
        })
        self.pack5 = self._product("SP Reformer pack 5", 5)
        self.single = self._product("SP Reformer single", 1)
        self.student = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "SP Student",
                "login": "sp.student@example.invalid",
                "email": "sp.student@example.invalid",
                "lang": "en_US",
                "tz": "Europe/Madrid",
                "group_ids": [(6, 0, [
                    self.env.ref("base.group_portal").id,
                    self.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })
        self.partner = self.student.partner_id
        start = PINNED + timedelta(days=1, hours=2)
        self.event = self.env["calendar.event"].create({
            "name": "SP class",
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": self.class_type.id,
            "is_fitness_class": True,
        })

    def _product(self, name, count, validity=60):
        return self.env["product.template"].create({
            "name": name, "list_price": 10.0 * count, "type": "service",
            "fitness_is_package": True, "fitness_class_count": count,
            "fitness_validity_days": validity,
            "fitness_class_type": "reformer", "fitness_session_type": "group",
        })

    def _line(self, product, partner=None):
        order = self.env["sale.order"].sudo().create({
            "partner_id": (partner or self.partner).id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": product.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "fitness_class_type": product.fitness_class_type,
        })
        order.action_confirm()
        line = order.order_line[:1]
        self.assertGreater(line.fitness_remaining_classes, 0,
                           "fixture: confirming must mint credit")
        return line

    def _cancel(self, line):
        line.order_id._action_cancel()
        self.assertEqual(line.order_id.state, "cancel")
        self.assertGreater(line.fitness_remaining_classes, 0,
                           "fixture: cancelling leaves the credit on the "
                           "line, which is the shape of the defect")

    def _engine(self):
        return self.env["fitness.booking"].sudo()._select_payment_source(
            self.partner.id, self.event)


@tagged("post_install", "-at_install")
class TestEngineSpendsOnlySpendable(SpendableFixture):

    def test_a_live_line_still_pays(self):
        line = self._line(self.pack5)
        self.assertEqual(self._engine(),
                         {"package_order_line_id": line.id})

    def test_a_cancelled_order_never_pays(self):
        line = self._line(self.pack5)
        self._cancel(line)
        with self.assertRaises(UserError):
            self._engine()

    def test_a_booking_on_a_cancelled_order_is_refused(self):
        line = self._line(self.single)
        self._cancel(line)
        with self.assertRaises(UserError):
            self.env["fitness.booking"].sudo().create({
                "student_id": self.partner.id,
                "calendar_event_id": self.event.id,
            })
        self.assertEqual(line.fitness_remaining_classes, 1,
                         "nothing may be taken from the cancelled line")

    def test_nurias_case_spends_the_pack(self):
        # A cancelled single that expires sooner would win the
        # soonest-expiry sort if it were still a candidate.
        single = self._line(self.single)
        single.fitness_validity_end_date = date(2026, 11, 10)
        self._cancel(single)
        pack = self._line(self.pack5)
        self.assertGreater(pack.fitness_validity_end_date,
                           single.fitness_validity_end_date)
        self.assertEqual(self._engine(),
                         {"package_order_line_id": pack.id})

    def test_a_locked_order_still_pays(self):
        line = self._line(self.pack5)
        line.order_id.action_lock()
        self.assertTrue(line.order_id.locked)
        self.assertEqual(line.order_id.state, "sale",
                         "Odoo 19 keeps a locked order in state sale")
        self.assertEqual(self._engine(),
                         {"package_order_line_id": line.id})

    def test_an_expired_line_never_pays(self):
        line = self._line(self.pack5)
        line.fitness_validity_end_date = date(2026, 11, 3)
        with self.assertRaises(UserError):
            self._engine()

    def test_the_last_valid_day_still_pays(self):
        line = self._line(self.pack5)
        line.fitness_validity_end_date = date(2026, 11, 4)
        self.assertEqual(self._engine(),
                         {"package_order_line_id": line.id})

    def test_a_line_that_never_expires_still_pays(self):
        line = self._line(self.pack5)
        line.fitness_validity_end_date = False
        self.assertEqual(self._engine(),
                         {"package_order_line_id": line.id})

    def test_someone_elses_line_never_pays(self):
        other = self.env["res.partner"].create({"name": "SP Other"})
        self._line(self.pack5, partner=other)
        with self.assertRaises(UserError):
            self._engine()
