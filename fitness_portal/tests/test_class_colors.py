# -*- coding: utf-8 -*-
"""Discipline colour coding on the timetable.

Reformer reads blue and Barre brown, so the two rooms are tellable apart in
the list itself rather than only by which tab is selected. The list uses one
flat colour per discipline; the three-shade breakdown in class_colors is
mapped and tested here but deliberately not rendered anywhere yet - it is for
the calendar view, where different class types share a row and the shade is
the only thing separating them.

Two things are worth testing and they fail differently. The mapping is pure
logic and is tested directly against every intensity value the field allows,
because a missing case there silently lands a class on the default tier and
nothing looks broken. The rendering is tested through the real page, because a
correct mapping that never reaches the markup is the same bug to a student.

The contrast of each shade against the text colour it carries is asserted in
the stylesheet's own comments and measured in the browser; it is not something
this suite can see, so it is deliberately not claimed here.
"""
from datetime import date, timedelta

from odoo.tests import HttpCase, tagged

from odoo.addons.fitness_core import class_colors

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class _FakeType(object):
    """Just the two fields tier_for reads, so the mapping can be exercised
    without creating twenty class types."""

    def __init__(self, name, intensity=False):
        self.name = name
        self.intensity = intensity


@tagged("post_install", "-at_install")
class TestClassColorMapping(HttpCase):
    """The mapping itself."""

    longMessage = False

    def test_every_intensity_value_maps(self):
        """No intensity the field allows may fall through to the default.

        A value missing from INTENSITY_TIER would quietly colour that class
        like a moderate one, which is exactly the confusion the coding exists
        to remove, so read the allowed values off the field rather than
        repeating them here.
        """
        field = self.env["fitness.class.type"]._fields["intensity"]
        allowed = [code for code, _label in field.selection]
        self.assertTrue(allowed, "intensity has no selection values")
        for code in allowed:
            self.assertIn(
                code, class_colors.INTENSITY_TIER,
                "intensity %r is not mapped to a tier" % code)
            self.assertIn(
                class_colors.INTENSITY_TIER[code],
                (class_colors.LIGHT, class_colors.MID, class_colors.DEEP))

    def test_intensity_wins_over_the_name_table(self):
        """The studio's own data leads; the name table is only a fallback."""
        # burnbarre is DEEP in the name table
        ct = _FakeType("Burn Barre", "low")
        self.assertEqual(class_colors.tier_for(ct), class_colors.LIGHT)

    def test_name_fallback_when_no_intensity(self):
        """Nine of twenty class types have no intensity recorded."""
        self.assertEqual(
            class_colors.tier_for(_FakeType("Reformer Tone")),
            class_colors.LIGHT)
        self.assertEqual(
            class_colors.tier_for(_FakeType("Barre Pump it")),
            class_colors.DEEP)

    def test_mojibake_duplicate_folds_onto_the_real_name(self):
        """Odoo holds three "Quick & Dirty" records, two with a mangled dash.

        They are the same class to a student, so they must not colour
        differently. Normalising away punctuation is what makes that true.
        """
        good = u"Quick & Dirty – Lunch Class"
        mangled = u"Quick & Dirty â€“ Lunch Class"
        self.assertEqual(
            class_colors.normalize(good), class_colors.normalize(mangled))
        self.assertEqual(
            class_colors.tier_for(_FakeType(good)),
            class_colors.tier_for(_FakeType(mangled)))

    def test_unknown_class_type_gets_a_usable_tier(self):
        """A class added in Odoo tomorrow must still render, not blow up."""
        tier = class_colors.tier_for(_FakeType("Something Brand New"))
        self.assertEqual(tier, class_colors.DEFAULT_TIER)
        self.assertEqual(
            class_colors.css_class("reformer", tier), "mv-shade-reformer-mid")

    def test_solid_class_is_one_colour_per_discipline(self):
        """What the timetable actually renders."""
        self.assertEqual(class_colors.solid_class("reformer"), "mv-solid-reformer")
        self.assertEqual(class_colors.solid_class("barre"), "mv-solid-barre")

    def test_solid_class_survives_a_discipline_it_does_not_know(self):
        """The template interpolates this straight into an attribute."""
        for junk in ("", "pilates", None):
            self.assertIn(class_colors.solid_class(junk),
                          ("mv-solid-reformer", "mv-solid-barre"))

    def test_css_class_never_emits_a_class_the_stylesheet_lacks(self):
        """The template interpolates this straight into an attribute."""
        valid = {
            "mv-shade-%s-%s" % (d, t)
            for d in ("reformer", "barre")
            for t in (class_colors.LIGHT, class_colors.MID, class_colors.DEEP)
        }
        for discipline in ("reformer", "barre", "", "pilates", None):
            for tier in (class_colors.LIGHT, class_colors.MID,
                         class_colors.DEEP, "", "vivid", None):
                self.assertIn(class_colors.css_class(discipline, tier), valid)


@tagged("post_install", "-at_install")
class TestTimetableShadesRender(HttpCase):
    """The mapping reaching the page."""

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "shade-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Shade Test Student",
            "login": "shade.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.teacher = cls.env["res.users"].create({
            "name": "Shade Test Instructor",
            "login": "shade.instructor@example.invalid",
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        cls.room = cls.env["fitness.classroom"].create({
            "name": "Shade Studio",
            "classroom_type": "reformer",
            "capacity": 6,
        })

        def class_type(name, discipline, intensity):
            return cls.env["fitness.class.type"].create({
                "name": name,
                "classroom_type": discipline,
                "duration": 45,
                "level": "all",
                "session_type": "group",
                "intensity": intensity,
            })

        # one of each tier, so the assertions below distinguish "the shade is
        # applied" from "one shade is applied to everything"
        cls.ct_easy = class_type("Shade Reformer Easy", "reformer", "low")
        cls.ct_hard = class_type("Shade Reformer Hard", "reformer", "very_high")
        cls.ct_barre = class_type("Shade Barre Mid", "barre", "moderate")

        closed = set(cls.env["fitness.closure.day"].sudo().search(
            [("state", "=", "applied")]).mapped("date"))

        def pick(min_offset):
            d = date.today() + timedelta(days=min_offset)
            while d in closed:
                d += timedelta(days=1)
            return d

        cls.when = pick(2)

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

        schedule(cls.ct_easy, 9.0)
        schedule(cls.ct_hard, 10.0)
        schedule(cls.ct_barre, 18.0)

    def _page(self):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open("/my/timetable")
        self.assertEqual(res.status_code, 200,
                         "did not load: %s" % res.text[:200])
        self.assertNotIn('name="password"', res.text,
                         "got the login page - the session was lost")
        # the fixtures must actually be on the page, or every assertion below
        # passes for the wrong reason
        self.assertIn("Shade Reformer Easy", res.text)
        return res.text

    def test_reformer_and_barre_rows_carry_different_colours(self):
        html = self._page()
        self.assertIn("mv-solid-reformer", html)
        self.assertIn("mv-solid-barre", html)

    def test_colour_sits_on_the_time_element(self):
        """The class must land on the element the stylesheet styles."""
        html = self._page()
        self.assertIn('class="mv-tt-time mv-solid-reformer"', html)

    def test_the_three_shade_system_stays_off_the_list(self):
        """The tiers are for the calendar, not for a column of times.

        The fixtures span low, moderate and very_high on purpose, so if the
        list ever went back to per-class-type shading this would catch it
        rather than it shipping unnoticed.
        """
        html = self._page()
        self.assertNotIn("mv-shade-", html)

    def test_no_row_is_left_unshaded(self):
        """An unshaded row reads as a rendering bug, not as a neutral class."""
        html = self._page()
        marker = 'class="mv-tt-time'
        idx, unshaded = 0, 0
        while True:
            idx = html.find(marker, idx)
            if idx == -1:
                break
            end = html.index('"', idx + len(marker))
            if "mv-solid-" not in html[idx:end + 1]:
                unshaded += 1
            idx = end
        self.assertEqual(unshaded, 0, "%d timetable rows have no colour" % unshaded)
