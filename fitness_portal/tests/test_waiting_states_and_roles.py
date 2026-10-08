# -*- coding: utf-8 -*-
"""Every state and every role that meets the three changed screens.

The fix turns on one question - has she asked, and is the studio still
holding it - so the risk is not that the waiting student is wrong. It is
that somebody else now gets her message: the student who never asked, the
one whose trial has been placed, the instructor, the manager, the visitor
who is not logged in at all.

Every request here is made as a real non-admin user over HTTP, with the
registry cache cleared between states, because _trial_awaiting_studio is
asked inside a request and reads records a cached environment would hold.

Redirects are followed and the language prefix is stripped before any URL
is compared: the portal serves /en/my/... and /es/my/... for the same page,
so a raw comparison against '/my/...' silently never matches.
"""
import re
from html import unescape
from urllib.parse import urlparse

from odoo.tests import HttpCase, tagged

WAITING = "Your trial request is with the studio"
NO_CREDIT = "You have no credit for these classes yet"
PICK_ONE = "One trial per student"
ASK_FOR_IT = "Request your free trial class"

SCREENS = ("/my/packages", "/my/timetable", "/my/studio")


def _strip_lang(path):
    """'/en/my/studio' -> '/my/studio'. The prefix is not part of the page."""
    return re.sub(r"^/(?:en|es|ca)(?:_[A-Z]{2})?(?=/)", "", path)


@tagged("post_install", "-at_install")
class TestWaitingStatesAndRoles(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        cls.barre = cls.env.ref("fitness_packages.product_barre_trial")
        cls.reformer = cls.env.ref("fitness_packages.product_reformer_trial")
        # The banner only exists while a trial is actually free, and free is
        # a promotion window - the same mechanism the studio uses.
        (cls.barre | cls.reformer).write({
            "fitness_promo_mode": "free",
            "fitness_promo_start": False,
            "fitness_promo_end": False,
        })
        cls.password = "states-roles-pw-1"
        cls.student_group = cls.env.ref("fitness_core.group_fitness_student")
        cls.portal_group = cls.env.ref("base.group_portal")

    # -- fixtures ----------------------------------------------------
    def _account(self, tag, groups=None):
        groups = groups or [self.portal_group, self.student_group]
        return self.env["res.users"].create({
            "name": "States %s" % tag,
            "login": "states.%s@example.invalid" % tag,
            "password": self.password,
            "lang": "en_US",
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [g.id for g in groups])],
        })

    def _request_for(self, user, status="pending"):
        return self.env["fitness.trial.request"].sudo().create({
            "name": user.name,
            "email": user.login,
            "partner_id": user.partner_id.id,
            "class_interest": "barre",
            "status": status,
        })

    def _spend_her_trial(self, user):
        """A confirmed zero-priced trial order is what 'used' means."""
        order = self.env["sale.order"].sudo().create({
            "partner_id": user.partner_id.id,
            "order_line": [(0, 0, {
                "product_id": self.barre.product_variant_ids[:1].id,
                "product_uom_qty": 1,
                "price_unit": 0.0,
            })],
        })
        order.action_confirm()
        return order

    def _as(self, user, url, expect=200):
        # _trial_awaiting_studio is asked inside the request, against records
        # this test has just written; a stale cache answers for the state
        # before them.
        self.env.flush_all()
        self.env.registry.clear_cache()
        self.authenticate(user.login, self.password)
        res = self.url_open(url, timeout=30, allow_redirects=True)
        self.assertEqual(res.status_code, expect, res.text[:200])
        return res

    def _html(self, user, url):
        res = self._as(user, url)
        self.assertNotIn('name="password"', res.text, "session was lost")
        return res.text

    @staticmethod
    def _landing(res):
        return _strip_lang(urlparse(res.url).path)

    # == 1. the student who is waiting ===============================
    def test_a_waiting_student_is_told_so_on_every_changed_screen(self):
        user = self._account("waiting")
        self._request_for(user)

        shop = self._html(user, "/my/packages")
        self.assertIn("Request sent", shop,
                      "the shop cards do not know about her request")
        self.assertNotIn(
            PICK_ONE, shop,
            "the shop still tells her to choose, next to a card that says "
            "the request has been sent")

        timetable = self._html(user, "/my/timetable")
        self.assertIn(WAITING, timetable)
        self.assertNotIn(
            NO_CREDIT, timetable,
            "she is told to go and buy something while the studio holds "
            "her free class")

        studio = self._html(user, "/my/studio")
        self.assertIn(WAITING, studio)
        self.assertNotIn(
            ASK_FOR_IT, studio,
            "the schedule still offers the form that would refuse her")

    def test_the_waiting_student_is_not_left_on_a_dead_end(self):
        """Every link the changed empty state offers must open for her."""
        user = self._account("deadend")
        self._request_for(user)
        html = self._html(user, "/my/studio")
        hrefs = set(re.findall(r'class="mv-empty-cta"[^>]*href="([^"]+)"', html))
        hrefs |= set(re.findall(r'href="([^"]+)"[^>]*class="mv-empty-cta"', html))
        self.assertTrue(
            hrefs,
            "the empty state offers no link at all, so she is told to wait "
            "with nowhere to go")
        for href in hrefs:
            res = self._as(user, href)
            self.assertNotIn(
                'name="password"', res.text,
                "the empty state links to %s, which bounces her to a login"
                % href)

    # == 2. the states that must NOT get her message =================
    def test_a_student_who_never_asked_is_still_told_how_to_get_credit(self):
        user = self._account("neverasked")
        timetable = self._html(user, "/my/timetable")
        self.assertIn(
            NO_CREDIT, timetable,
            "a student who has asked for nothing is no longer told how to "
            "get credit at all")
        self.assertNotIn(WAITING, timetable)
        self.assertIn(
            PICK_ONE, self._html(user, "/my/packages"),
            "the free trial is no longer offered to somebody who has not "
            "had one")

    def test_a_student_whose_trial_is_used_is_not_waiting(self):
        user = self._account("spent")
        self._request_for(user)
        self._spend_her_trial(user)

        for url in SCREENS:
            self.assertNotIn(
                WAITING, self._html(user, url),
                "%s tells a student whose trial has been placed that the "
                "studio is still holding her request" % url)

    def test_a_scheduled_request_is_finished_business(self):
        """Scheduled is closed: the studio has placed her."""
        user = self._account("scheduled")
        self._request_for(user, status="scheduled")
        for url in SCREENS:
            self.assertNotIn(
                WAITING, self._html(user, url),
                "%s still says the studio is holding a request it has "
                "already scheduled" % url)

    def test_a_contacted_request_is_still_open(self):
        """Contacted means the studio is working on it, not that it is done."""
        user = self._account("contacted")
        self._request_for(user, status="contacted")
        self.assertIn(
            WAITING, self._html(user, "/my/timetable"),
            "a request the studio has picked up but not yet placed reads as "
            "no request at all")

    # == 3. roles ====================================================
    def test_an_instructor_is_not_sent_to_the_student_screens(self):
        teacher = self._account("instructor", groups=[
            self.env.ref("base.group_user"),
            self.env.ref("fitness_core.group_fitness_teacher")])
        res = self._as(teacher, "/my/timetable")
        self.assertNotIn(
            WAITING, res.text,
            "an instructor is being told about a trial request of her own")

    def test_a_manager_is_not_shown_a_student_waiting_note(self):
        manager = self._account("manager", groups=[
            self.env.ref("base.group_user"),
            self.env.ref("fitness_core.group_fitness_manager")])
        res = self._as(manager, "/my/timetable")
        self.assertNotIn(WAITING, res.text)

    def test_a_visitor_who_is_not_logged_in_reaches_a_login(self):
        self.env.registry.clear_cache()
        res = self.url_open("/my/timetable", timeout=30, allow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(
            WAITING, res.text,
            "a public visitor is shown a note about somebody's trial request")
        self.assertIn(
            'name="password"', res.text,
            "the timetable served a public visitor instead of a login; "
            "landed on %s" % self._landing(res))

    # == 4. the student group is the gate ============================
    def test_a_portal_account_without_the_student_group_is_redirected(self):
        """The shop gate is the student group, teachers included."""
        outsider = self._account("outsider", groups=[self.portal_group])
        res = self._as(outsider, "/my/timetable")
        self.assertNotIn(WAITING, res.text)
        self.assertNotEqual(
            self._landing(res), "/my/timetable",
            "an account without the student group was served the timetable")


@tagged("post_install", "-at_install")
class TestWaitingNoteInEveryLanguage(HttpCase):
    """The note a waiting student reads, in the three languages we ship.

    The first version of this fix invented a new English sentence. It would
    have passed every behavioural test above and reached a Spanish student
    in English, because the shop, the timetable and the empty states are the
    screens most likely to be read by somebody who has just arrived.

    Both terms are reused from Home precisely so they are already in the
    catalogues - this is what proves it, in the language the student is
    actually reading.
    """

    longMessage = False

    # msgid -> what each catalogue must serve. Read from the .po files that
    # ship in this repo, not invented here.
    EXPECTED = {
        "es_ES": "Tu solicitud de clase de prueba está con el estudio",
        "ca_ES": "La teva sol·licitud de classe de prova és amb l'estudi",
        "en_US": "Your trial request is with the studio",
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        cls.password = "waiting-langs-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Langs Student",
            "login": "waiting.langs@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "tz": "Europe/Madrid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.env["fitness.trial.request"].sudo().create({
            "name": "Langs Student",
            "email": "waiting.langs@example.invalid",
            "partner_id": cls.user.partner_id.id,
            "class_interest": "barre",
            "status": "pending",
        })

    def _use(self, lang):
        # _activate_lang only flips the active flag; it does not import the
        # .po, so the page would render in English and the assertion would
        # fail for a reason that has nothing to do with the translation.
        self.env["res.lang"]._activate_and_install_lang(lang)
        self.user.lang = lang
        self.env.flush_all()
        self.env.registry.clear_cache()

    def _page(self, url):
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url, timeout=30, allow_redirects=True)
        self.assertEqual(res.status_code, 200, res.text[:200])
        # QWeb escapes the text it renders, so Catalan's apostrophe reaches
        # the page as l&#39;estudi. Comparing the raw body against the
        # catalogue would fail for Catalan alone, and only because of one
        # character - which reads exactly like a missing translation.
        return unescape(res.text)

    def test_the_timetable_note_is_translated(self):
        for lang, sentence in sorted(self.EXPECTED.items()):
            self._use(lang)
            self.assertIn(
                sentence, self._page("/my/timetable"),
                "the timetable's waiting note is not served in %s - a "
                "student reading the app in that language sees English"
                % lang)

    def test_the_schedule_note_is_translated(self):
        for lang, sentence in sorted(self.EXPECTED.items()):
            self._use(lang)
            self.assertIn(
                sentence, self._page("/my/studio"),
                "the schedule's waiting note is not served in %s" % lang)

    def test_the_timetable_cta_is_translated(self):
        """The link beside the note, which is the only thing she can press."""
        for lang, expected in (("es_ES", "Horario semanal"),
                               ("ca_ES", "Horari setmanal"),
                               ("en_US", "Weekly Timetable")):
            self._use(lang)
            self.assertIn(
                expected, self._page("/my/studio"),
                "the waiting state's link is not served in %s" % lang)
