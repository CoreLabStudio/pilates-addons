# -*- coding: utf-8 -*-
"""The full weekly timetable page.

/my/studio hides every class a student has no credit for, which left someone
deciding whether to buy anything unable to see what the studio even runs. This
page answers that instead, so its defining behaviour is that a slot appears
whether or not the student can book it - and that tapping it goes somewhere
useful, or explains itself in place when there is nowhere useful to go.

Rows come from fitness.class.schedule rather than a second hand-maintained
copy, so these tests build real schedules and let action_generate() produce the
occurrences, the same path the studio's own admin uses.

Both disciplines are rendered into the page and the toggle swaps which pane is
visible, so "barre is not showing" is a question about the hidden attribute,
not about whether the markup is present.

Every test asserts the page arrived and that a known class name rendered before
asserting anything about links: an empty or redirected page satisfies "the shop
link is absent" for entirely the wrong reason.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_bookings.models.fitness_booking import BOOKING_WINDOW_DAYS

SHOP_REFORMER = "/my/packages?tab=classes&amp;discipline=reformer"
SHOP_BARRE = "/my/packages?tab=classes&amp;discipline=barre"

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@tagged("post_install", "-at_install")
class TestTimetablePage(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "timetable-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Timetable Test Student",
            "login": "timetable.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            # the page renders times in the student's own timezone
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id
        cls.teacher = cls.env["res.users"].create({
            "name": "Timetable Test Instructor",
            "login": "timetable.instructor@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })

        # a real room, so the class page has a Room to label - without one the
        # row is correctly omitted and the label test fails for the wrong reason
        cls.room = cls.env["fitness.classroom"].create({
            "name": "TT Studio B",
            "classroom_type": "reformer",
            "capacity": 6,
        })

        def class_type(name, discipline, desc=""):
            return cls.env["fitness.class.type"].create({
                "name": name,
                "classroom_type": discipline,
                "description": desc,
                "duration": 45,
                "level": "all",
                "session_type": "group",
            })

        cls.ct_reformer = class_type(
            "TT Reformer Flow", "reformer",
            "Long controlled sets on spring resistance.")
        cls.ct_barre = class_type("TT Barre Groove", "barre")
        cls.ct_later = class_type("TT Reformer Horizon", "reformer")

        # Applied closure days cancel occurrences in place, which would move a
        # fixture's first class to the following week and silently change what
        # these tests are exercising. Dodging them by walking forward worked
        # until the studio closed every day up to its 16 September opening:
        # there is then no open day left inside the seven-day booking window,
        # and "pick the next open day" walks straight out of the window the
        # fixture exists to sit inside.
        #
        # So the days are chosen first - the offsets are what these tests mean
        # - and any closure standing on them is lifted for the duration of the
        # test instead. The transaction is rolled back, so the studio's real
        # closure calendar is untouched.
        cls.date_soon = date.today() + timedelta(days=2)
        cls.date_later = date.today() + timedelta(days=BOOKING_WINDOW_DAYS + 3)
        assert (cls.date_soon - date.today()).days <= BOOKING_WINDOW_DAYS
        assert (cls.date_later - date.today()).days > BOOKING_WINDOW_DAYS

        # The schedules below run weekly, so a closure on any later occurrence
        # would cancel it too; clear the whole span the fixtures cover.
        cls.env["fitness.closure.day"].sudo().search([
            ("state", "=", "applied"),
            ("date", ">=", date.today()),
            ("date", "<=", date.today() + timedelta(days=90)),
        ]).unlink()

        def schedule(ct, when, hour):
            s = cls.env["fitness.class.schedule"].create({
                "class_type_id": ct.id,
                "teacher_user_id": cls.teacher.id,
                "weekday": WEEKDAY_CODES[when.weekday()],
                "start_time": hour,
                "duration": 1.0,
                "classroom_id": cls.room.id,
                "date_start": when,
                "horizon_weeks": 6,
            })
            s.action_generate()
            return s

        cls.sched_reformer = schedule(cls.ct_reformer, cls.date_soon, 9.0)
        cls.sched_barre = schedule(cls.ct_barre, cls.date_soon, 18.0)
        cls.sched_later = schedule(cls.ct_later, cls.date_later, 11.0)

        cls.product = cls.env["product.product"].create({
            "name": "TT Reformer Pack",
            "list_price": 100.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
        })
        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.line = cls.env["sale.order.line"].create({
            "order_id": cls.order.id,
            "product_id": cls.product.id,
            "product_uom_qty": 1,
            "fitness_original_class_count": 10,
            "fitness_remaining_classes": 0,   # tests opt in by raising this
            "fitness_validity_end_date": fields.Date.today() + timedelta(days=90),
        })

    def _get(self, url="/my/timetable"):
        """Fetch the page as the student, proving the session actually held.

        A lost session renders the login form, which is itself a 200, so
        checking the status code alone reports "loaded" for a page that never
        ran the controller.
        """
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200, "did not load: %s" % res.text[:200])
        self.assertNotIn('name="password"', res.text,
                         "got the login page, not %s - the session was lost" % url)
        return res.text


    def _use_lang(self, lang):
        """Switch the student's language, activating it if the database lacks it.

        A build database ships with English only, so assuming es_ES/ca_ES were
        installed made these tests pass locally and fail on odoo.sh for a
        reason that had nothing to do with the translations themselves.
        """
        # _activate_lang only flips the active flag - it does not import the
        # .po files, so on a database that never had the language the page
        # would still render in English and the assertion would fail for the
        # wrong reason. _activate_and_install_lang loads the translations too.
        self.env['res.lang']._activate_and_install_lang(lang)
        self.user.lang = lang

    @staticmethod
    def _pane_is_hidden(html, discipline):
        """Whether one discipline's pane is the hidden one."""
        marker = '<div class="mv-tt-pane" data-discipline="%s"' % discipline
        idx = html.find(marker)
        assert idx != -1, "no pane found for %s" % discipline
        # the hidden attribute, when present, sits in this same opening tag
        tag_end = html.index('>', idx)
        return 'hidden' in html[idx:tag_end]

    # ── both disciplines present, one visible ────────────────────────────

    def test_both_disciplines_are_rendered(self):
        """The toggle swaps panes, so both must be in the page."""
        html = self._get()
        self.assertIn(self.ct_reformer.name, html, "reformer classes missing")
        self.assertIn(self.ct_barre.name, html, "barre classes missing")

    def test_reformer_pane_is_the_one_shown_by_default(self):
        html = self._get()
        self.assertFalse(self._pane_is_hidden(html, "reformer"),
                         "the reformer pane was hidden on load")
        self.assertTrue(self._pane_is_hidden(html, "barre"),
                        "the barre pane was visible alongside reformer")

    def test_discipline_param_opens_on_that_pane(self):
        """A shared link still lands on the right discipline."""
        html = self._get("/my/timetable?discipline=barre")
        self.assertFalse(self._pane_is_hidden(html, "barre"),
                         "the barre pane was hidden despite ?discipline=barre")
        self.assertTrue(self._pane_is_hidden(html, "reformer"),
                        "the reformer pane stayed visible")

    def test_unknown_discipline_falls_back_to_reformer(self):
        html = self._get("/my/timetable?discipline=nonsense")
        self.assertFalse(self._pane_is_hidden(html, "reformer"))

    def test_toggle_does_not_navigate(self):
        """The reported up-and-down jump was a full page load on every tap.

        Both panes ship with the page and the toggle swaps a hidden attribute,
        so there is nothing to reload and nothing for the browser to restore a
        scroll position against. A link here would bring the jump straight back.
        """
        html = self._get()
        start = html.index('id="mv-tt-toggle"')
        toggle = html[start:html.index('</div>', start)]
        self.assertNotIn('href', toggle,
                         "the discipline toggle navigates instead of swapping panes")
        self.assertIn('data-discipline="reformer"', toggle)
        self.assertIn('data-discipline="barre"', toggle)

    # ── layout ───────────────────────────────────────────────────────────

    def test_laid_out_as_day_cards_showing_the_class_name_only(self):
        """A row is the time and the class name, and nothing else.

        It used to carry the description and an instructor/room line as well.
        That gave every row a different height, turned the timetable into a
        wall of small grey text, and repeated in full what the page the row
        already links to says anyway. So the list names the class and the
        detail page carries the rest - which is what the next test checks, so
        that "removed from the list" can never quietly become "lost".
        """
        self.line.fitness_remaining_classes = 5
        html = self._get()
        self.assertIn("mv-tt-grid", html, "no day grid")
        self.assertIn("mv-tt-day-head", html, "day cards have no header")
        self.assertIn(self.ct_reformer.name, html, "class name missing from the list")
        # Stop at the calendar: it renders the same classes a second time.
        grid = html[html.index('mv-tt-grid'):html.index('id="mv-cal"')]
        self.assertNotIn("mv-tt-desc", grid, "description is back on the list rows")
        self.assertNotIn("mv-tt-meta", grid, "instructor/room line is back on the rows")
        self.assertNotIn("Long controlled sets on spring resistance.", grid,
                         "the description text is still rendered inline")
        self.assertNotIn(self.teacher.name, grid,
                         "the instructor name is still rendered inline")

    def test_what_the_list_drops_is_on_the_detail_page(self):
        """The other half of the rule above.

        Taking the description and the instructor off the row is only correct
        while the page it links to still has them; without this test the two
        changes could drift apart and the information would simply be gone.
        """
        self.line.fitness_remaining_classes = 5
        event = self.env["calendar.event"].search(
            [("class_type_id", "=", self.ct_reformer.id)], order="start", limit=1)
        self.assertTrue(event, "no class to open")
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/classes/%d" % event.id)
        self.assertEqual(res.status_code, 200)
        detail = res.text
        self.assertIn("Long controlled sets on spring resistance.", detail,
                      "description missing from the detail page")
        self.assertIn(self.teacher.name, detail,
                      "instructor missing from the detail page")
        self.assertIn(self.room.name, detail, "room missing from the detail page")

    def test_slot_shown_even_with_no_credit(self):
        self.line.fitness_remaining_classes = 0
        html = self._get()
        self.assertIn(self.ct_reformer.name, html,
                      "a student with no credit could not see what the studio runs")

    # ── the grid is uniform; states live on the detail page ──────────────

    def test_every_grid_row_is_tappable(self):
        """No dead rows: a student must always be able to find out more.

        The grid used to decide bookability itself and render the classes it
        refused as plain divs, so a student could see a class and have no way
        to reach an explanation of why they could not have it.
        """
        self.line.fitness_remaining_classes = 0      # the worst case
        html = self._get()
        # Stop at the calendar, not the bottom nav: the same classes are
        # rendered a second time below as calendar cells, and counting those
        # would measure the list against both copies of itself.
        grid = html[html.index('mv-tt-grid'):html.index('id="mv-cal"')]
        self.assertNotIn('mv-tt-row-static', grid, "grid still has non-tappable rows")
        # count the href rather than a whole opening tag: QWeb decides
        # attribute order, so matching "<a href=..." is brittle
        rows = grid.count('mv-tt-row')
        links = grid.count('href="/my/classes/')
        self.assertTrue(rows > 0, "no rows rendered at all")
        self.assertEqual(rows, links,
                         "%d rows but %d links to a class page" % (rows, links))

    def test_grid_carries_no_booking_window_notice(self):
        """That explanation belongs on the detail page now."""
        self.line.fitness_remaining_classes = 5
        html = self._get()
        # Stop at the calendar, not the bottom nav: the same classes are
        # rendered a second time below as calendar cells, and counting those
        # would measure the list against both copies of itself.
        grid = html[html.index('mv-tt-grid'):html.index('id="mv-cal"')]
        self.assertNotIn('Booking opens', grid,
                         "the window notice is still being rendered in the grid")

    # ── the three detail-page states ─────────────────────────────────────

    def _detail(self, event):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/classes/%d" % event.id)
        self.assertEqual(res.status_code, 200, "class detail did not load")
        self.assertNotIn('name="password"', res.text, "got the login page")
        return res.text

    def test_detail_state_1_eligible_shows_reserve(self):
        """Credit, and inside the window."""
        self.line.fitness_remaining_classes = 5
        html = self._detail(self._next_event(self.sched_reformer))
        self.assertIn("Reserve My Spot", html, "no Reserve button for an eligible student")
        self.assertNotIn("Booking opens", html, "warned about a class that is bookable now")
        self.assertNotIn("Explore memberships", html, "offered the shop to a student with credit")

    def test_detail_state_2_outside_window_shows_the_date(self):
        """Credit, but too early - the fix for the Reserve button that could
        only bounce off the model's ValidationError."""
        self.line.fitness_remaining_classes = 5
        html = self._detail(self._next_event(self.sched_later))
        self.assertIn("Booking opens", html, "no booking-window message")
        self.assertNotIn("Reserve My Spot", html,
                         "offered Reserve for a class outside the booking window")

    def test_detail_state_2_names_the_right_date(self):
        """class date minus BOOKING_WINDOW_DAYS, not the class's own date."""
        self.line.fitness_remaining_classes = 5
        ev = self._next_event(self.sched_later)
        opens = (ev.start - timedelta(days=BOOKING_WINDOW_DAYS)).date()
        html = self._detail(ev)
        self.assertIn(opens.strftime("%d").lstrip("0"), html)
        self.assertNotIn("Reserve My Spot", html)

    def test_detail_state_3_no_credit_shows_the_shop(self):
        self.line.fitness_remaining_classes = 0
        html = self._detail(self._next_event(self.sched_reformer))
        self.assertIn("Explore memberships", html, "no purchase prompt")
        self.assertIn("/my/packages?tab=classes&amp;discipline=reformer", html,
                      "purchase prompt did not pre-filter the shop")
        self.assertNotIn("Reserve My Spot", html,
                         "offered Reserve to a student with no credit")

    def test_detail_state_3_follows_the_classs_own_discipline(self):
        """Reformer credit must not make a barre class look bookable."""
        self.line.fitness_remaining_classes = 5      # reformer only
        html = self._detail(self._next_event(self.sched_barre))
        self.assertIn("/my/packages?tab=classes&amp;discipline=barre", html,
                      "barre class did not offer barre in the shop link")
        self.assertNotIn("Reserve My Spot", html)

    def test_detail_labels_are_present_and_translated(self):
        """Part B: the facts are labelled, not run together as prose."""
        self.line.fitness_remaining_classes = 5
        ev = self._next_event(self.sched_reformer)
        html = self._detail(ev)
        for label in ("Description", "Duration", "Instructor", "Room"):
            self.assertIn(label, html, "%s label missing from the class page" % label)
        self.assertIn("mv-detail-facts", html, "labelled facts block missing")

        for lang, expected in (("es_ES", ("Descripci", "Duraci", "Sala")),
                               ("ca_ES", ("Descripci", "Durada", "Sala"))):
            self._use_lang(lang)
            html = self._detail(ev)
            for term in expected:
                self.assertIn(term, html, "%s: %r missing" % (lang, term))
        self._use_lang("en_US")

    def test_duration_is_shown(self):
        """Read off the event, so a one-off change to a class is reflected."""
        self.line.fitness_remaining_classes = 5
        html = self._detail(self._next_event(self.sched_reformer))
        # the fixture schedules a one-hour class
        self.assertIn("1 h", html, "duration not rendered")

    # ── data source and timezone ─────────────────────────────────────────

    def test_time_is_rendered_in_the_students_timezone(self):
        self.line.fitness_remaining_classes = 5
        html = self._get()
        event = self._next_event(self.sched_reformer)
        self.assertNotEqual(event.start.strftime("%H:%M"), "09:00",
                            "fixture is not exercising a timezone conversion")
        self.assertIn(">09:00<", html,
                      "expected the studio's 09:00 Madrid class to read 09:00 "
                      "for a Madrid student, not its stored UTC time")

    def test_rows_come_from_the_recurring_schedule(self):
        """Archiving the schedule must empty the page - proving the source."""
        self.line.fitness_remaining_classes = 5
        self.assertIn(self.ct_reformer.name, self._get())
        self.sched_reformer.active = False
        self.assertNotIn(self.ct_reformer.name, self._get(),
                         "page still showed a class whose schedule was archived, "
                         "so it is not reading fitness.class.schedule")

    def test_cancelled_occurrence_is_skipped(self):
        """A closed day must not be the class the page offers to book."""
        self.line.fitness_remaining_classes = 5
        first = self._next_event(self.sched_reformer)
        self.assertIn("/my/classes/%d" % first.id, self._get())

        first.sudo().class_state = "cancelled"
        following = self._next_event(self.sched_reformer)
        self.assertNotEqual(following.id, first.id, "fixture has only one occurrence")
        self.assertNotIn("/my/classes/%d" % first.id, self._get(),
                         "still offered a cancelled class")

    # ── localization ─────────────────────────────────────────────────────

    def test_page_is_translated(self):
        """ES and CA, on the rendered page rather than in the catalogue.

        A .po entry can parse, load, and still never be used: a code: term is
        only picked up when the entry carries the odoo-python marker, which
        "Full" was missing here. Asserting on the served HTML is the only
        check that would have caught that.
        """
        expected = {
            "es_ES": ("Horario completo", "Todas nuestras clases, semana a semana"),
            "ca_ES": ("Horari complet", "Totes les nostres classes, setmana a setmana"),
        }
        for lang, (title, subtitle) in expected.items():
            self._use_lang(lang)
            html = self._get()
            self.assertIn(title, html, "%s title not translated" % lang)
            self.assertIn(subtitle, html, "%s subtitle not translated" % lang)
            self.assertNotIn("Every class we run", html,
                             "%s page still showed the English subtitle" % lang)
        self.user.lang = "en_US"

    def test_full_flag_is_translated(self):
        """`Full` had a code reference but no odoo-python marker."""
        self._use_lang("es_ES")
        try:
            self.assertEqual(
                self.env["base"].with_context(lang="es_ES").env._("Full"),
                "Completa",
                "the Full badge fell back to English",
            )
        finally:
            self.user.lang = "en_US"

    # ── entry points ─────────────────────────────────────────────────────

    def test_linked_from_home(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/home")
        self.assertEqual(res.status_code, 200)
        self.assertIn("/my/timetable", res.text, "no timetable link on Home")

    def test_linked_from_profile_hub(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my")
        self.assertEqual(res.status_code, 200)
        self.assertIn("My CoreLab Studio", res.text, "profile hub section missing")
        self.assertIn("/my/timetable", res.text, "no timetable link on the profile hub")

    # ── helper ───────────────────────────────────────────────────────────

    def _next_event(self, sched):
        """Next occurrence a student could actually book.

        Excluding cancelled classes is not incidental: the studio's closure
        days cancel occurrences in place, and the first run of this suite hit
        exactly that - the fixture's first class was a closure day, so the page
        correctly linked to the week after while this helper still pointed at
        the cancelled one.
        """
        return self.env["calendar.event"].sudo().search([
            ("recurrence_id", "=", sched.recurrence_id.id),
            ("class_state", "!=", "cancelled"),
            ("start", ">", fields.Datetime.now()),
        ], order="start asc", limit=1)
