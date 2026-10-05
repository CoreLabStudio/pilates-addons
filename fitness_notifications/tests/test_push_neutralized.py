# -*- coding: utf-8 -*-
"""Push on a copy of production: who it may still reach, and who it may not.

odoo.sh builds staging from a copy of production. Odoo's neutralization
clears its OWN push - the mail.web_push_* keys and mail_push_device - and
nothing of ours, so a copy arrives holding real students' endpoints. The
push service routes by endpoint and does not know which database asked,
which is how a "test" on staging rings a paying customer's phone.

Every case here is paired: the thing that must be suppressed, and the
thing that must still happen. A guard that only ever says no is
indistinguishable from push being broken.

No real push service is reached. web_push.send is replaced with a
recorder, so these prove what the server decided to send, not what any
phone received.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC, PARAM_TEST_USERS)

NEUTRALIZED = 'database.is_neutralized'


@tagged("post_install", "-at_install")
class TestPushOnACopyOfProduction(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.Sub = self.env['fitness.push.subscription']
        self.Param = self.env['ir.config_parameter'].sudo()
        # A keypair, so nothing is skipped for the wrong reason: without one
        # _notify_user returns early and every assertion below would pass
        # while proving nothing.
        self.Param.set_param(PARAM_PUBLIC, 'pub-for-test')
        self.Param.set_param(PARAM_PRIVATE, 'priv-for-test')

        portal = self.env.ref('base.group_portal')
        self.alice = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Alice Copy', 'login': 'alice.copy@example.invalid',
                'email': 'alice.copy@example.invalid',
                'group_ids': [(6, 0, [portal.id])]})
        self.bob = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Bob Copy', 'login': 'bob.copy@example.invalid',
                'email': 'bob.copy@example.invalid',
                'group_ids': [(6, 0, [portal.id])]})
        for user in (self.alice, self.bob):
            self.Sub._register_device(
                user.id, 'https://push.example.invalid/%s' % user.id,
                'pub', 'auth')

        self.sent = []
        self._real_send = web_push.send

        def recorder(endpoint, *args, **kwargs):
            self.sent.append(endpoint)
            return 201, ''

        web_push.send = recorder
        self.addCleanup(self._restore)
        # The parameter rows roll back with the transaction; the ormcache in
        # front of get_param does not. Without this, a test here that marks
        # the database neutralized leaves that answer cached, and the next
        # test in the run - one of the ordinary push tests, which knows
        # nothing about any of this - finds its push silently suppressed and
        # fails for a reason that is not in its own file. It cost three
        # green tests on the restore shape before it was caught.
        self.addCleanup(self.env.registry.clear_cache)

    def _restore(self):
        web_push.send = self._real_send

    def _neutralize(self, value='true'):
        self._set(NEUTRALIZED, value)

    def _set(self, key, value):
        """Write a parameter and make the running process believe it.

        get_param is ormcached, and that cache does NOT roll back with the
        transaction. A sibling test that deletes this row leaves the cache
        holding its absence while the rollback puts the row back, so the
        next test reads something that is no longer true. Clearing after
        each write is what keeps these independent of the order they run in.

        It is also why the runbook says a parameter changed from a shell
        needs the server restarted or the registry signalled before the
        running site sees it.
        """
        self.Param.set_param(key, value)
        self.env.registry.clear_cache()

    # ── not neutralized: nothing changes ─────────────────────────────────
    def test_production_sends_exactly_as_before(self):
        """The guard must be invisible where it does not apply."""
        self._set(NEUTRALIZED, 'False')
        sent = self.Sub._notify_user(self.alice.id, 'Title', 'Body')
        self.assertEqual(sent, 1, "a push did not leave an ordinary database")
        self.assertEqual(len(self.sent), 1)

    def test_an_absent_flag_is_not_neutralized(self):
        """A database that never ran neutralize.sql has no parameter at all."""
        param = self.Param.search([('key', '=', NEUTRALIZED)])
        param.unlink()
        self.env.registry.clear_cache()
        self.assertFalse(self.Sub._is_neutralized())
        self.assertEqual(self.Sub._notify_user(self.alice.id, 'T'), 1)

    # ── neutralized, empty list ──────────────────────────────────────────
    def test_a_copy_with_an_empty_list_sends_nothing(self):
        self._neutralize()
        self._set(PARAM_TEST_USERS, '')
        self.assertEqual(self.Sub._notify_user(self.alice.id, 'Title'), 0,
                         "a push left a copy of production")
        self.assertFalse(self.sent, "web_push.send was reached anyway")

    def test_the_bell_still_works_on_a_copy(self):
        """Only the push is gated. The in-app notification is the record the
        student would otherwise lose, and neutralization is not a reason to
        stop writing it."""
        self._neutralize()
        self._set(PARAM_TEST_USERS, '')
        before = self.env['fitness.notification'].sudo().search_count(
            [('user_id', '=', self.alice.id)])
        self.env['fitness.notification']._create_for_user(
            self.alice.id, 'booking_cancelled', 'Class cancelled', 'Body')
        after = self.env['fitness.notification'].sudo().search_count(
            [('user_id', '=', self.alice.id)])
        self.assertEqual(after, before + 1,
                         "the in-app notification was lost along with the push")
        self.assertFalse(self.sent, "the push went out from a copy anyway")

    # ── neutralized, an id listed ────────────────────────────────────────
    def test_a_listed_id_is_pushed_and_nobody_else_is(self):
        self._neutralize()
        self._set(PARAM_TEST_USERS, str(self.alice.id))
        self.assertEqual(self.Sub._notify_user(self.alice.id, 'Title'), 1,
                         "the tester on the list got nothing")
        self.assertEqual(self.Sub._notify_user(self.bob.id, 'Title'), 0,
                         "somebody not on the list was pushed to")
        self.assertEqual(len(self.sent), 1)
        self.assertIn(str(self.alice.id), self.sent[0])

    # ── the list is parsed forgivingly, and fails closed ─────────────────
    def test_spaces_and_a_trailing_comma_are_tolerated(self):
        self._neutralize()
        self.Param.set_param(
            PARAM_TEST_USERS, '  %s , %s ,  ' % (self.alice.id, self.bob.id))
        self.assertEqual(self.Sub._push_test_user_ids(),
                         {self.alice.id, self.bob.id})
        self.assertEqual(self.Sub._notify_user(self.alice.id, 'T'), 1)
        self.assertEqual(self.Sub._notify_user(self.bob.id, 'T'), 1)

    def test_garbage_in_the_list_suppresses_everything(self):
        """Fail closed. A typo must not be the reason a real phone rings."""
        self._neutralize()
        self._set(PARAM_TEST_USERS,
                             '%s, alice@example.invalid' % self.alice.id)
        self.assertIsNone(self.Sub._push_test_user_ids())
        self.assertEqual(self.Sub._notify_user(self.alice.id, 'T'), 0,
                         "an unreadable list still let a push out")
        self.assertFalse(self.sent)

    def test_a_truthy_flag_is_read_in_every_spelling_odoo_uses(self):
        for raw, expected in (('true', True), ('True', True), ('1', True),
                              ('t', True), ('False', False), ('0', False),
                              ('', False)):
            self._set(NEUTRALIZED, raw)
            self.assertEqual(
                self.Sub._is_neutralized(), expected,
                "database.is_neutralized=%r was read as %r"
                % (raw, not expected))

    # ── what the log says, and what it must never say ────────────────────
    def test_the_log_names_the_id_and_the_setting_but_no_endpoint(self):
        self._neutralize()
        self._set(PARAM_TEST_USERS, '')
        # A handler of our own rather than assertLogs: the test runner also
        # manages handlers and propagation on odoo.* loggers, and assertLogs
        # reported "no logs" for a call that demonstrably logs. Attaching
        # directly to the module's logger answers the question being asked.
        import logging
        records = []

        class Catch(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger(
            'odoo.addons.fitness_notifications.models.push_subscription')
        handler = Catch()
        previous = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            self.Sub._notify_user(self.alice.id, 'Title')
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

        self.assertTrue(records, "the suppression was not logged at all")
        blob = '\n'.join(r.getMessage() for r in records)
        self.assertIn(str(self.alice.id), blob,
                      "the log does not say who was suppressed")
        self.assertIn(PARAM_TEST_USERS, blob,
                      "the log does not say how to allow it")
        self.assertNotIn('push.example.invalid', blob,
                         "the log leaked an endpoint, which is a capability")
        self.assertFalse(
            [r for r in records if r.levelno >= logging.ERROR],
            "suppression logged at ERROR, which odoo.sh grades a build on")

    # ── the one dispatch path, guarded once ──────────────────────────────
    def test_every_notification_type_goes_through_the_same_gate(self):
        """All twenty-five call sites funnel through _create_for_user, which
        is why the guard sits in _notify_user and not in any of them."""
        self._neutralize()
        self._set(PARAM_TEST_USERS, '')
        for notif_type in ('booking_confirmed', 'booking_cancelled',
                           'class_rescheduled', 'teacher_swap',
                           'class_reminder'):
            self.env['fitness.notification']._create_for_user(
                self.alice.id, notif_type, 'Title', 'Body')
        self.assertFalse(
            self.sent,
            "a notification type reached the push service from a copy")

        self._set(PARAM_TEST_USERS, str(self.alice.id))
        self.env['fitness.notification']._create_for_user(
            self.alice.id, 'booking_cancelled', 'Title', 'Body')
        self.assertEqual(len(self.sent), 1,
                         "the same path did not send once the id was listed")
