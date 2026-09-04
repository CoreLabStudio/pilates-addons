# -*- coding: utf-8 -*-
"""The install-app button and the service worker behind it.

Chrome and Edge refuse to fire beforeinstallprompt unless a service worker
with a fetch handler is registered, so the button could never have appeared on
Android or desktop without /my/sw.js. That route is the load-bearing part of
this feature and is what these tests mostly cover; the visibility logic itself
is browser-side and is exercised separately in the browser.

Everything ships hidden on purpose - the server cannot know whether the
student already installed the app, so revealing is the browser's job. That
makes "is it hidden in the markup" the correct assertion here, not a bug.
"""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestInstallApp(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = "install-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Install Test Student",
            "login": "install.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })

    def _get(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200, "%s did not load" % url)
        self.assertNotIn('name="password"', res.text, "got the login page, not %s" % url)
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

    # ── the service worker ───────────────────────────────────────────────

    def test_service_worker_is_served(self):
        res = self.url_open("/my/sw.js")
        self.assertEqual(res.status_code, 200, "no service worker at /my/sw.js")
        self.assertIn("javascript", res.headers.get("Content-Type", ""),
                      "service worker not served as javascript")

    def test_service_worker_has_a_fetch_handler(self):
        """Without one the browser will not consider the portal installable."""
        body = self.url_open("/my/sw.js").text
        self.assertIn("'fetch'", body, "no fetch handler - install prompt cannot fire")

    def test_service_worker_does_not_cache(self):
        """A cached class list or credit balance is worse than no offline mode."""
        body = self.url_open("/my/sw.js").text
        self.assertNotIn("caches.open", body, "the worker caches responses")
        self.assertNotIn("respondWith", body, "the worker intercepts responses")

    def test_service_worker_scope_is_allowed(self):
        res = self.url_open("/my/sw.js")
        self.assertEqual(res.headers.get("Service-Worker-Allowed"), "/my/",
                         "worker cannot claim the portal scope")

    # ── the markup the browser reveals ───────────────────────────────────

    def test_home_carries_the_prompt_hidden(self):
        html = self._get("/my/home")
        self.assertIn('id="mv-install-card"', html, "no install prompt on Home")
        card = html[html.index('id="mv-install-card"'):]
        self.assertIn("hidden", card[:120],
                      "the prompt ships visible - it would flash for someone "
                      "who already installed the app")

    def test_home_carries_the_ios_sheet(self):
        html = self._get("/my/home")
        self.assertIn('id="mv-ios-sheet"', html, "no iOS instructions on Home")
        self.assertIn("Add to Home Screen", html, "iOS steps missing")

    def test_profile_hub_has_a_persistent_row(self):
        """The Home prompt can be dismissed; this row is how you get back."""
        html = self._get("/my")
        self.assertIn('id="mv-install-row"', html, "no install row on the profile hub")
        self.assertIn("My CoreLab Studio", html, "row is not in the studio section")

    def test_profile_hub_carries_the_ios_sheet(self):
        """The row offers the same button, so it needs the same instructions."""
        html = self._get("/my")
        self.assertIn('id="mv-ios-sheet"', html,
                      "the profile row could open a sheet that is not on the page")

    def test_triggers_are_marked_for_the_script(self):
        for url in ("/my/home", "/my"):
            self.assertIn("data-install-trigger", self._get(url),
                          "%s has no element the install script will bind to" % url)

    # ── localization ─────────────────────────────────────────────────────

    def test_prompt_is_translated(self):
        expected = {
            "es_ES": ("Instala CoreLab", "Ahora no"),
            "ca_ES": ("Instal·la CoreLab", "Ara no"),
        }
        for lang, (title, dismiss) in expected.items():
            self._use_lang(lang)
            html = self._get("/my/home")
            self.assertIn(title, html, "%s install title not translated" % lang)
            self.assertIn(dismiss, html, "%s dismiss label not translated" % lang)
        self.user.lang = "en_US"

    def test_ios_steps_are_translated(self):
        # fragments without apostrophes on purpose: QWeb escapes them, so
        # "d'inici" is served as "d&#39;inici" and a literal match fails for
        # a reason that has nothing to do with the translation
        expected = {
            "es_ES": "Añadir a pantalla de inicio",
            "ca_ES": "Afegeix a la pantalla",
        }
        for lang, step in expected.items():
            self._use_lang(lang)
            html = self._get("/my/home")
            self.assertIn(step, html, "%s iOS steps not translated" % lang)
        self.user.lang = "en_US"

    # ── the timing bug ───────────────────────────────────────────────────

    def test_install_event_is_captured_in_the_head(self):
        """beforeinstallprompt must be caught before the lazy bundle loads.

        Chrome fires it around page load and never fires it again, while
        corelab.js arrives in Odoo's lazy asset bundle - measured at roughly a
        second after the load event. Listening only from there missed the
        event every time, so the install button never appeared on Android or
        desktop and was reachable on iOS alone.

        The listener therefore lives inline in <head>. If it ever moves back
        into the bundle this fails, which is the point.
        """
        for url in ("/my/home", "/my"):
            html = self._get(url)
            head = html[:html.index("</head>")]
            self.assertIn("beforeinstallprompt", head,
                          "%s does not capture the install event in <head>; it "
                          "will be missed before corelab.js loads" % url)
            self.assertIn("mvInstallEvent", head,
                          "%s captures the event but does not stash it" % url)

    def test_profile_row_is_not_gated_on_the_prompt(self):
        """The row is the persistent way in, so it ships ready to reveal.

        It used to be revealed only when a prompt had been offered, which on
        any browser that never offers one left no way to install at all.
        """
        html = self._get("/my")
        self.assertIn('id="mv-install-row"', html)
        self.assertIn("data-install-trigger", html)

    def test_sheet_carries_both_step_sets(self):
        """iOS gets Safari's Share menu; everything else gets its own menu."""
        html = self._get("/my/home")
        self.assertIn('data-steps="ios"', html, "no iOS steps")
        self.assertIn('data-steps="other"', html,
                      "no instructions for a browser that offers no prompt")
        self.assertIn("Add to Home Screen", html)
        self.assertIn("Install app", html)
