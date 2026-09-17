# -*- coding: utf-8 -*-
"""A notification must be written in the language of the person reading it.

Not the language of whoever triggered it. The studio cancels a class in
Spanish; a Catalan student must be told in Catalan, and an English-speaking
one in English - in the bell and, because push carries the same text, on the
phone.

These were real failures: the class-cancellation notification was built from
English f-strings, so every student was told in English whatever their
account said.
"""
import pytz
from datetime import datetime, timedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNotificationLanguage(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = pytz.timezone("Europe/Madrid")
        cls.Notif = cls.env["fitness.notification"]

        # A build database ships with English only. Skipping there would mean
        # this never runs on the branch that builds from scratch - which is the
        # one place the language bug could reappear unnoticed - so install the
        # languages instead of stepping around them.
        for code in ("es_ES", "ca_ES"):
            cls.env["res.lang"]._activate_and_install_lang(code)
        langs = cls.env["res.lang"].with_context(active_test=False).search([])
        cls.have = {l.code for l in langs if l.active}

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Lang Room", "classroom_type": "reformer", "capacity": 6})
        cls.ct = cls.env["fitness.class.type"].create({
            "name": "Lang Reformer", "classroom_type": "reformer", "duration": 50,
            "level": "all", "session_type": "group", "intensity": "moderate"})

    def _student(self, login, lang):
        partner = self.env["res.partner"].create({"name": login, "email": login})
        return self.env["res.users"].create({
            "name": login, "login": login, "partner_id": partner.id, "lang": lang})

    def _entitled_booking(self, user, event):
        """A booking the studio would actually allow.

        Bookings need something to pay with - the engine refuses otherwise -
        so the fixture buys a pack the way a student does.
        """
        tmpl = self.env["product.template"].create({
            "name": "Lang Pack", "list_price": 100.0, "type": "service",
            "fitness_is_package": True, "fitness_class_count": 10,
            "fitness_validity_days": 90, "fitness_class_type": "reformer",
            "fitness_session_type": "group",
        })
        order = self.env["sale.order"].create({"partner_id": user.partner_id.id})
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": tmpl.product_variant_ids[:1].id,
            "product_uom_qty": 1,
            "price_unit": tmpl.list_price,
            "fitness_class_type": "reformer",
        })
        order.action_confirm()
        return self.env["fitness.booking"].create({
            "student_id": user.partner_id.id,
            "calendar_event_id": event.id,
            "package_order_line_id": order.order_line[:1].id,
            "manager_override_timewindow": True,
        })

    def test_cancelling_a_class_speaks_each_student_s_language(self):
        """The brief's own example, and the bug that was actually there."""
        if "ca_ES" not in self.have:
            self.skipTest("Catalan is not installed on this database")

        es_user = self._student("lang.es@example.invalid", "es_ES")
        ca_user = self._student("lang.ca@example.invalid", "ca_ES")

        start = datetime.now() + timedelta(days=3)
        event = self.env["calendar.event"].create({
            "name": "Reformer Sculpt",
            "class_type_id": self.ct.id,
            "classroom_id": self.room.id,
            "start": start,
            "stop": start + timedelta(minutes=50),
            "capacity": 6,
            "is_fitness_class": True,
        })
        for user in (es_user, ca_user):
            self._entitled_booking(user, event)

        # The studio cancels, working in Spanish - the failing condition.
        event.with_context(lang="es_ES").sudo().action_cancel_class()

        es_notif = self.Notif.search(
            [("user_id", "=", es_user.id), ("notification_type", "=", "booking_cancelled")],
            limit=1)
        ca_notif = self.Notif.search(
            [("user_id", "=", ca_user.id), ("notification_type", "=", "booking_cancelled")],
            limit=1)
        self.assertTrue(es_notif and ca_notif, "both students must be told")

        self.assertNotEqual(
            es_notif.title, ca_notif.title,
            "both students got the same title (%r) - the notification is being "
            "written in the canceller's language, not the reader's" % es_notif.title)
        self.assertNotIn(
            "Class cancelled", es_notif.title,
            "the Spanish student was told in English: %r" % es_notif.title)
        self.assertNotIn(
            "Class cancelled", ca_notif.title,
            "the Catalan student was told in English: %r" % ca_notif.title)

    def test_the_text_does_not_follow_the_acting_user(self):
        """Same recipient, two different acting languages, same output."""
        if "ca_ES" not in self.have:
            self.skipTest("Catalan is not installed on this database")
        reader = self._student("lang.reader@example.invalid", "ca_ES")

        titles = set()
        for acting in ("es_ES", "en_US"):
            start = datetime.now() + timedelta(days=4)
            event = self.env["calendar.event"].create({
                "name": "Reformer FlowLab",
                "class_type_id": self.ct.id,
                "classroom_id": self.room.id,
                "start": start,
                "stop": start + timedelta(minutes=50),
                "capacity": 6,
                "is_fitness_class": True,
            })
            self._entitled_booking(reader, event)
            event.with_context(lang=acting).sudo().action_cancel_class()
            notif = self.Notif.search(
                [("user_id", "=", reader.id)], order="id desc", limit=1)
            titles.add(notif.title)

        self.assertEqual(
            len(titles), 1,
            "the same student was told two different things depending on who "
            "cancelled: %r" % titles)
