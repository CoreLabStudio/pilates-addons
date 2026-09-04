# -*- coding: utf-8 -*-
"""My Schedule must not invite a student to book with no credit left.

The empty-state case was fixed once already: a student with no bookings and
nothing left to spend used to be shown "Browse & book classes". This is the
case that fix missed - the student *does* have a booking, and that very booking
is what consumed the last credit. The "Browse & book more classes" link under
the list was rendered unconditionally, so it still pointed a student with a
zero balance at a shop page that could sell them nothing.

Both tests assert the booked class name appears before asserting anything about
the link. Without that, an empty page passes the zero-credit assertion for the
wrong reason - the link is equally absent when My Schedule rendered its empty
state, or when the request never arrived at all.
"""
import re
from datetime import timedelta


def _text(html):
    """Visible text of a response, so a failure names its own cause."""
    html = re.sub(r'(?s)<(script|style).*?</>', ' ', html)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()

from odoo import fields
from odoo.tests import HttpCase, tagged

BOOK_MORE = "book more classes"
PURCHASE_PROMPT = "Time to move!"


@tagged("post_install", "-at_install")
class TestScheduleBookMoreLink(HttpCase):

    # a failed assertIn on a full page otherwise dumps the entire HTML
    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "sched-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Schedule Test Student",
            "login": "schedule.student@example.invalid",
            "password": cls.password,
            # assertions below are on the English source strings
            "lang": "en_US",
            # Odoo 19 renamed res.users.groups_id to group_ids. /my/studio
            # redirects anyone outside the student group, so portal alone
            # would render an unrelated page that passes for the wrong reason.
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id

        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Schedule Test Reformer",
            "classroom_type": "reformer",
            "duration": 45,
            # level and session_type are NOT NULL; max_capacity is computed
            "level": "all",
            "session_type": "group",
        })
        cls.product = cls.env["product.product"].create({
            "name": "Schedule Test Pack",
            "list_price": 50.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
        })

        # a class inside both the 7-day booking window and the 28-day
        # look-ahead the schedule renders
        start = fields.Datetime.now() + timedelta(days=2)
        cls.event = cls.env["calendar.event"].create({
            "name": "Schedule Test Class",
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": cls.class_type.id,
            # the students' calendar.event record rule is
            # [('is_fitness_class','=',True)] - without this the page 403s
            "is_fitness_class": True,
        })

        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.line = cls.env["sale.order.line"].create({
            "order_id": cls.order.id,
            "product_id": cls.product.id,
            "product_uom_qty": 1,
            "fitness_original_class_count": 1,
            "fitness_remaining_classes": 1,
            "fitness_validity_end_date": fields.Date.today() + timedelta(days=60),
        })

        # the booking is created while a credit still exists, which is the real
        # sequence; the controller debits the package afterwards
        cls.booking = cls.env["fitness.booking"].create({
            "student_id": cls.partner.id,
            "calendar_event_id": cls.event.id,
            "state": "booked",
            "package_order_line_id": cls.line.id,
        })

    def _schedule_html(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/studio?view=schedule")
        self.assertEqual(res.status_code, 200,
                         "My Schedule did not load: %s" % _text(res.text)[:700])
        return res.text

    def test_last_credit_spent_shows_purchase_prompt(self):
        """One booking, and it consumed the only credit -> offer the shop."""
        self.line.fitness_remaining_classes = 0
        html = self._schedule_html()
        self.assertIn(self.event.name, html,
                      "the booking itself did not render - the rest of this "
                      "test would pass for the wrong reason")
        self.assertNotIn(BOOK_MORE, html,
                         "offered 'book more classes' to a student with no credit")
        self.assertIn(PURCHASE_PROMPT, html,
                      "no purchase prompt shown in place of the dead-end link")

    def test_credit_remaining_still_shows_browse_link(self):
        """Booked 1 of 5 -> the link must survive; don't hide it for everyone."""
        self.line.fitness_remaining_classes = 4
        html = self._schedule_html()
        self.assertIn(self.event.name, html,
                      "the booking itself did not render - the rest of this "
                      "test would pass for the wrong reason")
        self.assertIn(BOOK_MORE, html,
                      "hid 'book more classes' from a student who still has credit")
        self.assertNotIn(PURCHASE_PROMPT, html,
                         "purchase prompt shown to a student who can still book")
