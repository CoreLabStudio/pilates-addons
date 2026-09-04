# -*- coding: utf-8 -*-
"""The two controls above the class list on /my/studio.

The date range and the room toggle both decide what a student sees, and both
fail quietly: a range that silently falls back shows the wrong week without
saying so, and a toggle that renders when only one room has classes hides
every class behind a tab with nothing in it.

So these test the decisions rather than the markup where they can. The range
is asserted against RANGE_CHOICES itself, not a copy of it here, because a
list that drifts from what the controller accepts is exactly the bug - a chip
offering a value the controller rejects renders fine and does nothing.

The client-side filtering is not tested here; it runs in the browser. What is
tested is the contract it depends on: the toggle carries data-discipline and
every class card carries data-ct. If either disappears the filter silently
stops matching, which is the failure that would otherwise reach a student.
"""
import re
from datetime import date, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_portal.controllers import portal as portal_ctrl

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@tagged("post_install", "-at_install")
class TestStudioControls(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "studio-controls-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Studio Controls Student",
            "login": "studio.controls@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        cls.teacher = cls.env["res.users"].create({
            "name": "Studio Controls Instructor",
            "login": "studio.controls.teacher@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Controls Room",
            "classroom_type": "reformer",
            "capacity": 6,
        })

        def class_type(name, discipline):
            return cls.env["fitness.class.type"].create({
                "name": name,
                "classroom_type": discipline,
                "duration": 45,
                "level": "all",
                "session_type": "group",
            })

        cls.ct_reformer = class_type("Controls Reformer", "reformer")
        cls.ct_barre = class_type("Controls Barre", "barre")

        # The class has to land inside the default booking window or the page
        # renders empty and the controls under test are never drawn. Walking
        # forward past applied closures used to find such a day; it stops
        # working the moment the studio closes the whole window, as it does
        # ahead of its 16 September opening - the walk then lands outside the
        # window and the toggle legitimately disappears.
        #
        # So the day is fixed at the offset these tests mean, and closures
        # standing on it are lifted for the test. The transaction rolls back,
        # so the studio's real closure calendar is untouched.
        cls.when = date.today() + timedelta(days=2)
        cls.env["fitness.closure.day"].sudo().search([
            ("state", "=", "applied"),
            ("date", ">=", date.today()),
            ("date", "<=", date.today() + timedelta(days=90)),
        ]).unlink()

        def schedule(ct, hour):
            s = cls.env["fitness.class.schedule"].create({
                "class_type_id": ct.id,
                "teacher_user_id": cls.teacher.id,
                "weekday": WEEKDAY_CODES[cls.when.weekday()],
                "start_time": hour,
                "duration": 1.0,
                "classroom_id": cls.room.id,
                "date_start": cls.when,
                "horizon_weeks": 6,
            })
            s.action_generate()
            return s

        cls.sched_reformer = schedule(cls.ct_reformer, 9.0)
        cls.sched_barre = schedule(cls.ct_barre, 18.0)

        # credit for both rooms, so both are actually offered to this student
        for ct, name in ((cls.ct_reformer, "Controls Reformer Pack"),
                         (cls.ct_barre, "Controls Barre Pack")):
            product = cls.env["product.product"].create({
                "name": name,
                "list_price": 100.0,
                "sale_ok": True,
                "type": "service",
                "fitness_is_package": True,
                "fitness_class_type": ct.classroom_type,
            })
            order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
            cls.env["sale.order.line"].create({
                "order_id": order.id,
                "product_id": product.id,
                "product_uom_qty": 1,
                "fitness_original_class_count": 10,
                "fitness_remaining_classes": 10,
                "fitness_validity_end_date": fields.Date.today() + timedelta(days=90),
            })

    RANGE_ROW = re.compile(r'id="mv-range-filters".*?</div>', re.S)
    CHIP = re.compile(r'href="/my/studio\?days=(\d+)"(.*?)>', re.S)

    def _chips(self, html):
        """(offered days, the one currently active).

        _available_values cannot be called directly - it reads request.env, so
        outside a request it raises before doing anything. Going through the
        page tests the same decision by the route a student actually takes.
        """
        row = self.RANGE_ROW.search(html)
        self.assertIsNotNone(row, "no date range row on the page")
        offered, active = [], None
        for days, attrs in self.CHIP.findall(row.group(0)):
            offered.append(int(days))
            if "font-weight:700" in attrs:
                active = int(days)
        return offered, active

    def _get(self, url="/my/studio"):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200, "did not load: %s" % res.text[:200])
        self.assertNotIn('name="password"', res.text,
                         "got the login page - the session was lost")
        return res.text

    # ── the date range ───────────────────────────────────────────────

    def test_range_is_today_week_month(self):
        """The three the studio asked for, and nothing else."""
        self.assertEqual(portal_ctrl.RANGE_CHOICES, (1, 7, 30))

    def test_every_chip_offers_a_range_the_controller_accepts(self):
        """A chip whose value is rejected renders fine and does nothing."""
        offered, _active = self._chips(self._get())
        self.assertEqual(offered, list(portal_ctrl.RANGE_CHOICES))

    def test_the_removed_range_falls_back_rather_than_breaking(self):
        """Links and bookmarks still hold days=14 from before this change."""
        _offered, active = self._chips(self._get("/my/studio?days=14"))
        self.assertEqual(active, portal_ctrl.DEFAULT_LOOK_AHEAD_DAYS)

    def test_a_month_is_accepted_and_widens_the_window(self):
        _o, active = self._chips(self._get("/my/studio?days=30"))
        self.assertEqual(active, 30)
        week = self._get("/my/studio?days=7").count('class="mv-class-card')
        month = self._get("/my/studio?days=30").count('class="mv-class-card')
        self.assertGreaterEqual(month, week)

    def test_nonsense_range_falls_back(self):
        for junk in ("0", "-5", "abc", "999"):
            _o, active = self._chips(self._get("/my/studio?days=%s" % junk))
            self.assertEqual(active, portal_ctrl.DEFAULT_LOOK_AHEAD_DAYS,
                             "days=%r should fall back" % junk)

    def test_the_page_renders_the_three_labels(self):
        html = self._get()
        self.assertIn("This month", html)
        self.assertNotIn("Next 14 days", html)

    # ── the room toggle ──────────────────────────────────────────────

    def test_toggle_offers_both_rooms_when_both_have_classes(self):
        tabs = portal_ctrl.FitnessStudentPortal._discipline_tabs(
            {"reformer", "barre"}, self.env._)
        self.assertEqual([t["key"] for t in tabs], ["reformer", "barre"])

    def test_no_toggle_when_only_one_room_has_classes(self):
        """A tab with nothing behind it is worse than no tab."""
        for types in ({"reformer"}, {"barre"}, {"any"}, {""}, set()):
            self.assertEqual(
                portal_ctrl.FitnessStudentPortal._discipline_tabs(types, self.env._), [],
                "a toggle was offered for %r" % (types,))

    def test_class_types_belonging_to_neither_room_do_not_make_a_tab(self):
        """'any' is not a room a student picks between."""
        tabs = portal_ctrl.FitnessStudentPortal._discipline_tabs(
            {"reformer", "any", ""}, self.env._)
        self.assertEqual(tabs, [])

    def test_toggle_renders_with_the_hook_the_filter_needs(self):
        """The browser filter matches data-discipline against data-ct.

        Either attribute going missing breaks filtering silently, so both are
        asserted here rather than left to a visual check.
        """
        html = self._get()
        self.assertIn('id="mv-studio-discipline"', html)
        self.assertIn('data-discipline="reformer"', html)
        self.assertIn('data-discipline="barre"', html)
        self.assertIn('data-ct="reformer"', html)
        self.assertIn('data-ct="barre"', html)

    def test_the_old_chip_row_is_gone(self):
        """Two controls answering the same question is the bug this replaced."""
        html = self._get()
        self.assertNotIn("mv-type-pill", html)
        self.assertNotIn('id="mv-type-filters"', html)

    def test_one_tab_starts_selected(self):
        """Nothing selected means the filter has no value to apply."""
        html = self._get()
        start = html.find('id="mv-studio-discipline"')
        self.assertNotEqual(start, -1)
        block = html[start:start + 900]
        self.assertIn("mv-active", block)
        self.assertEqual(block.count('aria-selected="true"'), 1)
