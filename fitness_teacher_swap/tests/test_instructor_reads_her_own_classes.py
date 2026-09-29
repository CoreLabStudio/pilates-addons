# -*- coding: utf-8 -*-
"""The instructor portal, over HTTP, for the three people who can ask.

These pass on a restore of production and failed on a fresh database,
and neither result was wrong: production carried a record rule somebody
had made by hand in Settings and no module created. It is
fitness_core.rule_fitness_teacher_calendar_event now, so this holds on
any database, and these tests are what says so.

The class is built the way the timetable builds one - through
calendar.event.create with is_fitness_class set and nothing else - which
means it has NO attendees, because fitness_core clears them. Odoo's own
portal rule grants a portal user the events she is attending, so it
grants an instructor nothing at all. Only the rule above reaches her.
"""

import re

from datetime import timedelta
from urllib.parse import urlparse

from odoo import fields
from odoo.tests import HttpCase, tagged

CSRF = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')


@tagged("post_install", "-at_install")
class TestInstructorReadsHerOwnClasses(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        portal = cls.env.ref("base.group_portal").id
        teacher = cls.env.ref("fitness_core.group_fitness_teacher").id
        student = cls.env.ref("fitness_core.group_fitness_student").id

        cls.pw = "own-classes-pw-1"
        cls.hers = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Own Classes Teacher", "lang": "en_US",
                "login": "own.teacher@example.invalid", "password": cls.pw,
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.other = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Other Teacher", "lang": "en_US",
                "login": "own.other@example.invalid", "password": cls.pw,
                "group_ids": [(6, 0, [portal, teacher])]})
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Own Classes Student", "lang": "en_US",
                "login": "own.student@example.invalid", "password": cls.pw,
                "group_ids": [(6, 0, [portal, student])]})

        cls.room = cls.env["fitness.classroom"].create({
            "name": "Own Classes Room", "classroom_type": "barre",
            "capacity": 8})
        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Own Classes Barre", "classroom_type": "barre",
            "session_type": "group", "level": "all",
            "classroom_id": cls.room.id})
        cls.pack = cls.env["product.template"].create({
            "name": "Own Classes Pack", "type": "service",
            "list_price": 100.0, "sale_ok": True, "fitness_is_package": True,
            "fitness_class_count": 20, "fitness_validity_days": 90,
            "fitness_class_type": "barre", "fitness_session_type": "group"})

    def setUp(self):
        super().setUp()
        start = fields.Datetime.now() - timedelta(minutes=30)
        self.event = self.env["calendar.event"].sudo().with_context(
            no_mail_to_attendees=True, mail_create_nolog=True).create({
                "name": "Own Classes Session",
                "start": start, "stop": start + timedelta(minutes=55),
                "allday": False, "is_fitness_class": True,
                "class_type_id": self.class_type.id,
                "classroom_id": self.room.id,
                "capacity": 8, "user_id": self.hers.id})
        self.assertFalse(
            self.event.partner_ids,
            "fixture drifted: a real fitness class has no attendees, and a "
            "test that gives it one is testing Odoo's rule, not ours")

        order = self.env["sale.order"].sudo().create(
            {"partner_id": self.student.partner_id.id})
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.pack.product_variant_ids[:1].id,
            "product_uom_qty": 1, "price_unit": 100.0})
        order.action_confirm()
        self.booking = self.env["fitness.booking"].sudo().with_context(
            _fitness_clase_fija_placement=True).create({
                "student_id": self.student.partner_id.id,
                "calendar_event_id": self.event.id,
                "package_order_line_id": order.order_line[:1].id})
        self.roster_url = "/my/instructor/classes/%d" % self.event.id

    def _token(self):
        """From a page this session is allowed to open."""
        for url in ("/my/instructor/classes", "/my/account", "/my"):
            r = self.url_open(url)
            if r.status_code == 200:
                found = CSRF.search(r.text)
                if found:
                    return found.group(1)
        return ""

    def _try_to_mark(self):
        return self.url_open(
            self.roster_url + "/mark", allow_redirects=False,
            data={"csrf_token": self._token(),
                  "booking_id": self.booking.id, "action": "attended"})

    # -- the instructor whose class it is --------------------------------

    def test_she_sees_her_class_and_its_roster(self):
        self.authenticate("own.teacher@example.invalid", self.pw)

        dash = self.url_open("/my/instructor")
        self.assertEqual(
            dash.status_code, 200,
            "the instructor dashboard did not open. Without the record rule "
            "on calendar.event this is where it stops.")

        listing = self.url_open("/my/instructor/classes?filter=today")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(
            "Own Classes Session", listing.text,
            "her own class is missing from her class list")

        roster = self.url_open(self.roster_url)
        self.assertEqual(
            roster.status_code, 200,
            "the roster did not open for the instructor teaching the class")
        self.assertIn(
            "Own Classes Student", roster.text,
            "the roster opened without the student who is booked into it")

    def test_she_can_mark_attendance_from_it(self):
        self.authenticate("own.teacher@example.invalid", self.pw)
        self.url_open(self.roster_url)

        self._try_to_mark()
        self.booking.invalidate_recordset()
        self.assertEqual(
            self.booking.state, "attended",
            "the instructor could not mark attendance on her own class")

    # -- another instructor ----------------------------------------------

    def test_another_instructor_gets_nothing(self):
        self.authenticate("own.other@example.invalid", self.pw)

        listing = self.url_open("/my/instructor/classes?filter=today")
        self.assertEqual(
            listing.status_code, 200,
            "she is an instructor, so her own list must still open")
        self.assertNotIn(
            "Own Classes Session", listing.text,
            "somebody else's class is on her list")

        roster = self.url_open(self.roster_url)
        self.assertNotEqual(
            roster.status_code, 200,
            "she opened the roster of a class she does not teach")
        self.assertNotIn("Own Classes Student", roster.text)

    def test_another_instructor_cannot_mark_it(self):
        self.authenticate("own.other@example.invalid", self.pw)
        self._try_to_mark()
        self.booking.invalidate_recordset()
        self.assertEqual(
            self.booking.state, "booked",
            "an instructor who does not teach this class marked somebody "
            "present in it")

    # -- a student --------------------------------------------------------

    def test_a_student_is_sent_back_to_her_own_portal(self):
        """Where she LANDS, not the first hop.

        On a database with the website module every portal URL is
        redirected to a language-prefixed one first - /my/instructor
        becomes /en/my/instructor before any controller runs. Asserting
        on the first Location therefore passes on a fresh install and
        fails on a restore of production for a reason that has nothing
        to do with permissions. Follow the chain and look at the end.

        The end is matched with endswith rather than by stripping a
        language prefix off the front. "/my" is itself two lowercase
        letters after a slash, so a regex for a language code eats the
        very path it is there to reveal - which is how this test failed
        the first time it was written.
        """
        self.authenticate("own.student@example.invalid", self.pw)

        for url in ("/my/instructor", "/my/instructor/classes",
                    self.roster_url):
            page = self.url_open(url)
            self.assertEqual(
                page.status_code, 200,
                "%s ended on %s" % (url, page.status_code))
            path = urlparse(page.url).path
            self.assertTrue(
                path == "/my" or path.endswith("/my"),
                "%s left a student on %s, not on her own portal"
                % (url, path))
            self.assertNotIn(
                "instructor", path,
                "%s left a student on an instructor page (%s)" % (url, path))
            # Not her name: she IS the student, so her name is all over her
            # own portal home and asserting it away fails on a page that is
            # rightfully hers. The attendance form is the thing only a
            # roster renders.
            self.assertNotIn(
                "/mark", page.text,
                "%s gave a student the attendance controls" % url)

    def test_a_student_cannot_mark_herself_present(self):
        """She holds write on her own booking - that is how cancelling
        works - so nothing but this stops her."""
        self.authenticate("own.student@example.invalid", self.pw)
        self._try_to_mark()
        self.booking.invalidate_recordset()
        self.assertEqual(
            self.booking.state, "booked",
            "a student marked herself present over HTTP")
