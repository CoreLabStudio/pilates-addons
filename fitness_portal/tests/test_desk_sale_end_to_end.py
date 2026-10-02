# -*- coding: utf-8 -*-
"""A desk sale, all the way through: invoice, email, notification.

The wizard's other tests stop at the order total. These carry on past it,
because every step after the order has failed at least once on this
system and each failure was invisible from the one before:

  * a cash sale produced no invoice at all, because Odoo only invoices
    from a completed payment transaction and cash has none;
  * then it produced an invoice nobody was sent, because the mail comes
    from send_invoice_cron, which also searches transactions;
  * and the registration fee arrived on the order after the sale, so the
    invoice and the cash in the drawer disagreed.

So these assert on records that exist afterwards - mail.mail rows,
fitness.notification rows, account.move lines - rather than on the
wizard returning without raising. "It did not raise" was true during
every one of the faults above.

The student with no email address is tested alongside, not as an edge
case. She is a supported state here (RUNBOOK-students-without-email.md),
and the branch that handles her is the one that decides whether the
invoice is marked sent when nothing was sent.
"""

from odoo.tests import TransactionCase, tagged

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
STUDENT_GROUP = 'fitness_core.group_fitness_student'
MATRICULA = 'fitness_subscriptions.product_matricula'


@tagged("post_install", "-at_install")
class TestDeskSaleEndToEnd(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matricula = cls.env.ref(MATRICULA).sudo()
        cls.fee = cls.matricula.fitness_effective_price()

        cls.manager = cls.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Desk E2E Manager',
                'login': 'desk.e2e.mgr@example.invalid',
                'group_ids': [(6, 0, [
                    cls.env.ref('base.group_user').id,
                    cls.env.ref(MANAGER_GROUP).id])]})

        cls.plan = cls.env['sale.subscription.plan'].sudo().create({
            'name': 'Desk E2E Mensual',
            'billing_period_value': 1, 'billing_period_unit': 'month'})

        cls.membership = cls.env['product.template'].sudo().create({
            'name': 'Desk E2E Membership', 'type': 'service',
            'list_price': 130.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True,
            'recurring_invoice': True,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
            'taxes_id': [(6, 0, cls.matricula.taxes_id.ids)]})
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'Desk E2E Pack', 'type': 'service',
            'list_price': 75.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
            'taxes_id': [(6, 0, cls.matricula.taxes_id.ids)]})

    # -- fixtures ---------------------------------------------------------

    def _student(self, tag, email='desk.e2e.%s@example.invalid'):
        """A student with a portal account, because the in-app notification
        is created for a res.users and a partner alone would get none."""
        user = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Desk E2E %s' % tag,
                'login': 'desk.e2e.%s' % tag,
                'email': (email % tag) if '%s' in email else email or False,
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref(STUDENT_GROUP).id])]})
        return user.partner_id

    def _student_without_email(self, tag):
        partner = self._student(tag)
        # Cleared afterwards: res.users wants a login, and the login is not
        # what the invoice is mailed to - partner.email is.
        partner.sudo().write({'email': False})
        return partner

    def _sell(self, partner, product, plan=None):
        wiz = self.env['fitness.desk.sale.wizard'].with_user(
            self.manager).create({
                'partner_id': partner.id,
                'product_id': product.id,
                'plan_id': plan.id if plan else False,
                'payment_method': 'cash'})
        wiz._onchange_product_id()
        collected = wiz.amount_paid
        wiz.action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', partner.id)], order='id desc', limit=1)
        return wiz, order, collected

    def _invoices(self, order):
        return order.sudo().invoice_ids

    def _mails_to(self, partner):
        return self.env['mail.mail'].sudo().search(
            ['|', ('recipient_ids', 'in', partner.ids),
             ('email_to', 'ilike', partner.email or '@@never@@')])

    def _notifications(self, partner, kind='invoice_issued'):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', 'in', partner.user_ids.ids),
            ('notification_type', '=', kind)])

    # -- the invoice -------------------------------------------------------

    def test_a_cash_sale_produces_a_posted_invoice(self):
        partner = self._student('inv')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        inv = self._invoices(order)
        self.assertTrue(
            inv, "the desk sale created no invoice at all - cash would be "
                 "the only paying route on this system with none")
        self.assertEqual(
            inv.state, 'posted',
            "the invoice exists but is still a draft, so it carries no "
            "number and is not in the ledger")

    def test_the_fee_is_its_own_line_on_the_invoice(self):
        partner = self._student('lines')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        inv = self._invoices(order)
        products = inv.invoice_line_ids.mapped('product_id.product_tmpl_id')
        self.assertIn(
            self.matricula, products,
            "the registration fee is not a line on the invoice, so the "
            "student cannot see what she was charged it for")
        self.assertIn(
            self.membership, products,
            "the membership itself is not on the invoice")
        self.assertEqual(
            len(inv.invoice_line_ids), 2,
            "expected the membership and the fee as two lines, got %d"
            % len(inv.invoice_line_ids))

    def test_the_invoice_totals_what_was_collected(self):
        partner = self._student('total')
        _wiz, order, collected = self._sell(
            partner, self.membership, self.plan)

        inv = self._invoices(order)
        self.assertAlmostEqual(
            inv.amount_total, collected, places=2,
            msg="she handed over %.2f and the invoice says %.2f"
                % (collected, inv.amount_total))

    def test_a_package_is_invoiced_the_same_way(self):
        """Not only memberships. A pack is a cash sale too."""
        partner = self._student('pack')
        _wiz, order, collected = self._sell(partner, self.pack)

        inv = self._invoices(order)
        self.assertTrue(inv, "a package sold at the desk produced no invoice")
        self.assertEqual(inv.state, 'posted', "the pack invoice is a draft")
        self.assertAlmostEqual(
            inv.amount_total, collected, places=2,
            msg="the pack invoice says %.2f against %.2f collected"
                % (inv.amount_total, collected))

    # -- the email ---------------------------------------------------------

    def test_she_is_actually_sent_the_invoice(self):
        """A mail.mail row, not a code path that looks like it sends one."""
        partner = self._student('mail')
        before = self._mails_to(partner).ids
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        new = self._mails_to(partner).filtered(lambda m: m.id not in before)
        self.assertTrue(
            new,
            "no mail was created for %s. The invoice is posted and correct "
            "and she was never sent it - which is what happened to every "
            "cash buyer before this path existed." % partner.email)

    def test_the_invoice_is_marked_sent(self):
        partner = self._student('sent')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        self.assertTrue(
            self._invoices(order).is_move_sent,
            "the invoice was mailed but not marked sent, so the next run "
            "would send it again")

    # -- the in-app notification -------------------------------------------

    def test_the_bell_tells_her_too(self):
        partner = self._student('bell')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        notes = self._notifications(partner)
        self.assertTrue(
            notes,
            "no in-app notification was created. Email is the one channel "
            "that can fail silently; the bell is the one she sees.")
        self.assertEqual(
            len(notes), 1,
            "she was told %d times about one invoice" % len(notes))

    # -- the student with no email address ---------------------------------

    def test_a_student_without_an_email_is_still_invoiced(self):
        partner = self._student_without_email('noemail')
        _wiz, order, collected = self._sell(
            partner, self.membership, self.plan)

        inv = self._invoices(order)
        self.assertTrue(
            inv, "a student with no email address got no invoice; having no "
                 "address is a supported state, not a reason to skip the "
                 "accounting")
        self.assertEqual(inv.state, 'posted', "her invoice is a draft")
        self.assertAlmostEqual(
            inv.amount_total, collected, places=2,
            msg="her invoice says %.2f against %.2f collected"
                % (inv.amount_total, collected))

    def test_a_student_without_an_email_still_gets_the_bell(self):
        partner = self._student_without_email('noemail2')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        self.assertTrue(
            self._notifications(partner),
            "she has no email address, so the in-app notification is the "
            "ONLY way she learns the invoice exists - and there is none")

    def test_her_invoice_is_not_marked_sent_when_nothing_was_sent(self):
        """Otherwise she never gets it, even after giving us an address.

        is_move_sent is what every later send checks. Marking it on an
        invoice that was never mailed means adding her email address
        afterwards fixes nothing.
        """
        partner = self._student_without_email('noemail3')
        _wiz, order, _paid = self._sell(partner, self.membership, self.plan)

        self.assertFalse(
            self._invoices(order).is_move_sent,
            "the invoice claims to have been sent to a student with no "
            "address, so it will never be sent again")

    def test_selling_to_her_does_not_raise(self):
        """The money is in the till before the wizard runs.

        A mail problem must not undo the sale: the order, the invoice and
        the cash entry all stand or the drawer disagrees with the books.
        """
        partner = self._student_without_email('noemail4')
        try:
            _wiz, order, _paid = self._sell(
                partner, self.membership, self.plan)
        except Exception as exc:                       # noqa: BLE001
            self.fail(
                "selling to a student with no email address raised %s: %s"
                % (type(exc).__name__, exc))
        self.assertTrue(order, "no order was created")
