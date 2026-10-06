# -*- coding: utf-8 -*-
"""What the shop says when she comes back from paying.

Every state a provider can leave her in, and the promise each one makes.

The states matter here more than usual. Production carries S00389: an open
order with TWO draft transactions and Stripe saying the money was taken,
and S00414, which sat with a done transaction against an unconfirmed order
until somebody settled it by hand. So "draft" is not nothing-happened, and
"done" is not necessarily credited - the page has to be careful in both
directions.
"""
import io
import os
import re

from odoo.tests import HttpCase, TransactionCase, tagged

ASK = 'id="mv-notif-booked"'
# The three payment flashes, by the markup the server controls. NOT by
# their words: the portal renders in the student's own language, so an
# English phrase passes on a fresh database and fails on the production
# restore, where the company default is Spanish. Pinning the student to
# en_US instead only moved the problem - the website module then rewrites
# /my/... to /en/my/..., and that redirect took one request fifty-five
# minutes to serve. The wording of each flash is checked separately,
# in all three languages, by TestPaymentWording below.
PAID = 'id="mv-pay-done"'
PAYING = 'id="mv-pay-pending"'
FAILED = 'id="mv-pay-failed"'



@tagged("post_install", "-at_install")
class TestPaymentReturnStates(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Pay Student', 'login': 'pay.student',
                'email': 'pay.student@example.invalid',
                'password': 'pay-pass-9134',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        # Every payment.method ships archived and every provider ships
        # disabled, so search([]) returns nothing and these tests SKIPPED -
        # which reads as a pass and proves nothing. One is activated here
        # instead. Nothing contacts a provider: the transactions are driven
        # by hand, and state is what is under test.
        self.provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'none')], limit=1)
        if not self.provider:
            self.provider = self.env['payment.provider'].sudo().search(
                [], limit=1)
        self.method = self.env['payment.method'].sudo().with_context(
            active_test=False).search([], limit=1)
        if not self.provider or not self.method:
            self.skipTest("this database has no payment provider at all")
        # Order matters: Odoo refuses to activate a payment method until an
        # ENABLED provider supports it ("this payment method needs a partner
        # in crime"). So the provider is enabled and linked first.
        self.provider.sudo().write({
            'state': 'test',
            'payment_method_ids': [(4, self.method.id)]})
        self.method.sudo().write({'active': True})
        self.env.registry.clear_cache()

    def _order(self, product):
        return self.env['sale.order'].sudo().create({
            'partner_id': self.student.partner_id.id,
            'order_line': [(0, 0, {
                'product_id': product.product_variant_ids[:1].id,
                'product_uom_qty': 1})]})

    def _tx(self, state, order=None, ref=None):
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'reference': ref or ('PAY-%s' % state),
            'amount': 25.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.student.partner_id.id,
            'sale_order_ids': [(6, 0, order.ids)] if order else False,
        })
        if state == 'authorized':
            # Odoo refuses the authorized state unless the provider offers
            # manual capture, and the first provider on these databases is
            # SEPA Direct Debit, which does not. The field is computed and
            # unstored, so assigning it sets it for this test only - the
            # same thing Odoo's own payment tests do.
            self.provider.sudo().support_manual_capture = 'full_only'
        tx.sudo().write({'state': state})
        return tx

    def _page(self, path='/my/packages?from_payment=1'):
        self.authenticate('pay.student', 'pay-pass-9134')
        return self.url_open(path).text

    # ── in progress ──────────────────────────────────────────────────────
    def test_draft_is_in_progress_not_a_failure(self):
        """S00389's shape. Stripe may already hold her money."""
        self._tx('draft')
        body = self._page()
        self.assertIn(PAYING, body,
                      "a draft transaction was not reported as in progress")
        self.assertNotIn(FAILED, body,
                         "a draft transaction was reported as a failure")
        self.assertIn(ASK, body, "the in-progress state lost the ask")

    def test_pending_is_in_progress(self):
        self._tx('pending')
        body = self._page()
        self.assertIn(PAYING, body)
        self.assertIn(ASK, body)

    def test_authorized_with_an_unconfirmed_order_is_in_progress(self):
        """Stripe's manual-capture state: reserved, not taken. Nothing is in
        her account until the studio captures it."""
        order = self._order(self._any_package())
        self._tx('authorized', order=order)
        body = self._page()
        self.assertIn(PAYING, body,
                      "authorized was reported as paid")
        self.assertIn(ASK, body)

    def test_done_against_an_unconfirmed_order_is_in_progress(self):
        """S00414's shape: the money arrived, the order never confirmed, so
        there is no credit. Saying "payment received" here is a promise the
        account cannot keep."""
        order = self._order(self._any_package())
        self.assertEqual(order.state, 'draft')
        self._tx('done', order=order)
        body = self._page()
        self.assertIn(PAYING, body,
                      "done against a draft order was reported as paid")

    # ── finished ─────────────────────────────────────────────────────────
    def test_done_with_a_confirmed_order_is_paid(self):
        order = self._order(self._any_package())
        order.action_confirm()
        self._tx('done', order=order)
        body = self._page()
        self.assertIn(PAID, body,
                      "a confirmed purchase was not reported as paid")
        self.assertIn(ASK, body)

    # ── refused ──────────────────────────────────────────────────────────
    def test_cancel_and_error_are_failures(self):
        for state in ('cancel', 'error'):
            self._tx(state, ref='PAY-FAIL-%s' % state)
            body = self._page()
            self.assertIn(FAILED, body,
                          "%s was not reported as a failure" % state)
            self.assertNotIn(ASK, body,
                             "the ask appeared after a %s" % state)

    # ── stale ────────────────────────────────────────────────────────────
    def test_a_transaction_older_than_thirty_minutes_shows_nothing(self):
        from datetime import timedelta
        from odoo import fields
        tx = self._tx('done')
        # Straight to the column. create_date is readonly and the ORM did
        # not take it, so the transaction stayed inside the thirty-minute
        # window and this test failed while the code was right.
        self.env.cr.execute(
            "UPDATE payment_transaction SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(minutes=45), tx.id))
        tx.invalidate_recordset(['create_date'])
        body = self._page()
        for marker in (PAID, PAYING, FAILED):
            self.assertNotIn(marker, body,
                             "an old transaction is still being reported")
        self.assertNotIn(ASK, body)

    # ── helpers ──────────────────────────────────────────────────────────
    def _any_package(self):
        prod = self.env['product.template'].sudo().search(
            [('fitness_is_package', '=', True)], limit=1)
        if not prod:
            self.skipTest("no package product on this database")
        return prod


@tagged("post_install", "-at_install")
class TestPaymentWording(TransactionCase):
    """The six words of the three payment flashes, in all three languages.

    Away from HTTP on purpose. Over a request the portal renders in the
    student's own language, so an English assertion says nothing on the
    production restore and everything on a fresh database - which is how
    ten of these passed on one shape and failed on the other. The flash
    MARKUP is asserted over HTTP above; the WORDS are asserted here.

    Both catalogues are read from the shipped .po files, so this says the
    same thing on a fresh database (where es and ca are not installed) as
    on the restore. Where a language IS installed, the running translation
    is checked against the catalogue - which catches a .po that was never
    loaded as well as one that was never written.
    """

    #: head and body of each flash, exactly as the controller spells them
    FLASHES = {
        'done': ('Payment received.',
                 'Your classes are ready to book.'),
        'pending': ('Payment in progress.',
                    'Your bank has not confirmed it yet. We will tell you '
                    'as soon as it goes through - you do not need to pay '
                    'again.'),
        'failed': ('That payment was not completed.',
                   'You can try again, or pay at the studio. If you see a '
                   'charge in your bank, write to us and we will sort it '
                   'out.'),
    }
    CATALOGUES = {'es_ES': 'es_ES.po', 'ca_ES': 'ca_ES.po'}
    RETIRED = 'Nothing has been charged'
    PROMISE = 'If you see a charge in'

    def _module_dir(self):
        from odoo.addons import fitness_portal
        return os.path.dirname(fitness_portal.__file__)

    def _controller_source(self):
        path = os.path.join(self._module_dir(), 'controllers', 'portal.py')
        source = io.open(path, encoding='utf-8').read()
        # Join Python's implicit concatenation. The longer labels are
        # written across several lines, so the sentence a student reads is
        # never contiguous in the file - and the translator's msgid is the
        # joined one.
        return re.sub(r"'\s*\n\s*'", '', source)

    @staticmethod
    def _unquote(chunk):
        chunk = chunk.strip()
        if chunk.startswith('"') and chunk.endswith('"'):
            chunk = chunk[1:-1]
        return chunk.replace('\\"', '"').replace('\\n', '\n')

    def _catalogue(self, filename):
        """{msgid: msgstr} from a .po, joining the continuation lines."""
        path = os.path.join(self._module_dir(), 'i18n', filename)
        entries, key, msgid, msgstr = {}, None, [], []

        def flush():
            if key is not None:
                entries[''.join(msgid)] = ''.join(msgstr)

        for raw in io.open(path, encoding='utf-8'):
            line = raw.strip()
            if line.startswith('msgid '):
                flush()
                key, msgid, msgstr = 'id', [self._unquote(line[6:])], []
            elif line.startswith('msgstr '):
                key, msgstr = 'str', [self._unquote(line[7:])]
            elif line.startswith('"') and key == 'id':
                msgid.append(self._unquote(line))
            elif line.startswith('"') and key == 'str':
                msgstr.append(self._unquote(line))
            elif not line:
                flush()
                key, msgid, msgstr = None, [], []
        flush()
        return entries

    # -- the English the controller actually ships -----------------------
    def test_english_is_the_wording_the_controller_ships(self):
        """en_US needs no catalogue - the source string IS the English."""
        source = self._controller_source()
        for state, (flash_head, flash_body) in self.FLASHES.items():
            self.assertIn(flash_head, source,
                          "the %s flash head is not in the controller"
                          % state)
            self.assertIn(flash_body, source,
                          "the %s flash body is not in the controller"
                          % state)

    def test_the_retired_promise_is_gone(self):
        """It could be false at the moment she reads it.

        Production carries S00389: an open order on two draft transactions
        with Stripe saying the money was taken. Telling that student
        nothing had been charged would have been a lie on her screen.
        """
        self.assertNotIn(self.RETIRED, self._controller_source(),
                         "the controller still promises nothing was charged")

    def test_she_is_told_what_to_do_about_a_charge(self):
        self.assertIn(self.PROMISE, self._controller_source(),
                      "the failure does not say what to do if her bank "
                      "shows a charge")

    # -- Spanish and Catalan ---------------------------------------------
    def test_every_flash_is_translated_in_spanish_and_catalan(self):
        for lang, filename in sorted(self.CATALOGUES.items()):
            catalogue = self._catalogue(filename)
            for state, strings in sorted(self.FLASHES.items()):
                for english in strings:
                    self.assertIn(
                        english, catalogue,
                        "%s has no entry for the %s flash: %r"
                        % (filename, state, english[:40]))
                    self.assertTrue(
                        catalogue[english].strip(),
                        "%s leaves the %s flash untranslated: %r"
                        % (filename, state, english[:40]))
                    self.assertNotEqual(
                        catalogue[english].strip(), english,
                        "%s copies the English for the %s flash: %r"
                        % (filename, state, english[:40]))

    def test_an_installed_language_really_serves_its_catalogue(self):
        """A written .po that was never loaded reads as English on screen."""
        installed = self.env['res.lang'].sudo().search(
            [('code', 'in', list(self.CATALOGUES))]).mapped('code')
        if not installed:
            # Fresh databases carry en_US alone. The catalogues themselves
            # are checked above, so this is not a silent pass for the
            # words - only for the loading of them, and there is nothing
            # here to load.
            self.skipTest("neither es_ES nor ca_ES is installed here")
        for lang in sorted(installed):
            catalogue = self._catalogue(self.CATALOGUES[lang])
            translate = self.env(
                context=dict(self.env.context, lang=lang))._
            for state, strings in sorted(self.FLASHES.items()):
                for english in strings:
                    self.assertEqual(
                        translate(english), catalogue[english].strip(),
                        "%s serves something other than its catalogue for "
                        "the %s flash" % (lang, state))
