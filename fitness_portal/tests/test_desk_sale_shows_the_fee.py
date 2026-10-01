# -*- coding: utf-8 -*-
"""What the desk asks for is what the order comes to.

Yoleyva sold a membership at the desk for 145.00 and the order came to
177.23. She reported the numbers as being off, and they were: the
registration fee was appended to the order AFTER the sale, and the form
never showed it. The manager was told one figure, the invoice said
another, and the cash in the drawer matched neither. Eva Morales's
afternoon - three orders, three invoices, 468.00 recorded against 169.00
taken - started here.

"Cash taken" now means the whole sale. The fee is a line on the form
when it applies, it is counted into the default, and it comes off the
top when the order is built, so the membership takes the remainder and
the total is exactly what was collected.

These assert on the ORDER TOTAL against the figure typed in, because
that is the thing that was wrong. A test that checked the fee line
alone would have passed throughout.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
MATRICULA = 'fitness_subscriptions.product_matricula'


@tagged("post_install", "-at_install")
class TestDeskSaleShowsTheFee(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matricula = cls.env.ref(MATRICULA).sudo()
        cls.fee = cls.matricula.fitness_effective_price()

        cls.manager = cls.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Desk Fee Manager',
                'login': 'desk.fee.mgr@example.invalid',
                'group_ids': [(6, 0, [
                    cls.env.ref('base.group_user').id,
                    cls.env.ref(MANAGER_GROUP).id])]})
        cls.student = cls.env['res.partner'].sudo().create(
            {'name': 'Desk Fee Student'})
        cls.returning = cls.env['res.partner'].sudo().create(
            {'name': 'Desk Fee Returning Student'})

        Plan = cls.env['sale.subscription.plan'].sudo()
        cls.monthly = Plan.create({
            'name': 'Desk Fee Mensual',
            'billing_period_value': 1, 'billing_period_unit': 'month'})
        cls.quarterly = Plan.create({
            'name': 'Desk Fee Trimestral',
            'billing_period_value': 3, 'billing_period_unit': 'month'})

        cls.membership = cls.env['product.template'].sudo().create({
            'name': 'Desk Fee Membership', 'type': 'service',
            'list_price': 130.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True,
            # Without this, confirming an order that carries a plan raises
            # "Please add a recurring product in the subscription or remove
            # the recurring plan" - sale_subscription requires at least one
            # line whose product is recurring. Every real membership on this
            # database sets it; a fixture that does not is testing a product
            # the studio could never sell.
            'recurring_invoice': True,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
            'taxes_id': [(6, 0, cls.matricula.taxes_id.ids)]})
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'Desk Fee Pack', 'type': 'service',
            'list_price': 75.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60,
            'fitness_class_type': 'reformer',
            'fitness_session_type': 'group',
            'taxes_id': [(6, 0, cls.matricula.taxes_id.ids)]})

        # A confirmed membership, so she counts as a returning student and
        # the fee is waived for her.
        #
        # The plan goes on at CREATE and the line is added afterwards. Two
        # reasons, both learned here: a recurring product with no plan is
        # refused outright ("add a recurring plan or remove the recurring
        # product"), and writing plan_id alongside order_line discards an
        # explicit price_unit - that is how a quarterly membership came to
        # bill one month's money on production.
        prior = cls.env['sale.order'].sudo().create({
            'partner_id': cls.returning.id,
            'plan_id': cls.monthly.id})
        cls.env['sale.order.line'].sudo().create({
            'order_id': prior.id,
            'product_id': cls.membership.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 130.0})
        prior.action_confirm()

    def _wizard(self, partner, product, plan=None):
        wiz = self.env['fitness.desk.sale.wizard'].with_user(
            self.manager).create({
                'partner_id': partner.id,
                'product_id': product.id,
                'plan_id': plan.id if plan else False,
                'payment_method': 'cash'})
        # The form fills the amount through onchange; do the same.
        wiz._onchange_product_id()
        return wiz

    # -- a first membership: the fee is shown and counted ----------------

    def test_the_form_shows_the_fee_as_its_own_line(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        self.assertAlmostEqual(
            wiz.matricula_fee, self.fee, places=2,
            msg="the registration fee is not on the form, so the manager "
                "cannot see what she is collecting")
        self.assertAlmostEqual(
            wiz.membership_price, 130.0, places=2,
            msg="the membership price is wrong on the form")

    def test_the_default_is_membership_plus_fee(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        self.assertAlmostEqual(
            wiz.normal_price, 130.0 + self.fee, places=2,
            msg="the total to collect is %.2f; it should be the membership "
                "and the fee together" % wiz.normal_price)
        self.assertAlmostEqual(
            wiz.amount_paid, wiz.normal_price, places=2,
            msg="Cash taken did not default to the whole sale")

    def test_the_order_totals_exactly_what_she_collects(self):
        """The fault, stated as a test."""
        wiz = self._wizard(self.student, self.membership, self.monthly)
        asked = wiz.amount_paid
        wiz.action_create_sale()

        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        self.assertAlmostEqual(
            order.amount_total, asked, places=2,
            msg="she was told to collect %.2f and the order came to %.2f. "
                "That difference is the registration fee, added after the "
                "sale and never shown." % (asked, order.amount_total))

    def test_the_fee_is_on_the_order_once(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        fee_lines = order.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == self.matricula)
        self.assertEqual(len(fee_lines), 1)
        self.assertAlmostEqual(
            fee_lines.price_total, self.fee, places=2,
            msg="the fee on the order is %.2f, not the %.2f the studio "
                "charges" % (fee_lines.price_total, self.fee))

    # -- no fee due: nothing changes -------------------------------------

    def test_a_returning_student_sees_no_fee_line(self):
        wiz = self._wizard(self.returning, self.membership, self.monthly)
        self.assertAlmostEqual(
            wiz.matricula_fee, 0.0, places=2,
            msg="a second membership was shown a registration fee")
        self.assertAlmostEqual(
            wiz.normal_price, 130.0, places=2,
            msg="her total should be the membership alone")

    def test_a_quarterly_commitment_sees_no_fee_line(self):
        wiz = self._wizard(self.student, self.membership, self.quarterly)
        wiz._onchange_plan_id()
        self.assertAlmostEqual(
            wiz.matricula_fee, 0.0, places=2,
            msg="three months waives the fee, and one was shown")

    def test_a_pack_sees_no_fee_line(self):
        wiz = self._wizard(self.student, self.pack)
        self.assertAlmostEqual(wiz.matricula_fee, 0.0, places=2)
        self.assertAlmostEqual(
            wiz.normal_price, 75.0, places=2,
            msg="a pack carries no registration fee and its total moved")

    def test_a_pack_order_totals_what_she_collects(self):
        wiz = self._wizard(self.student, self.pack)
        asked = wiz.amount_paid
        wiz.action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        self.assertAlmostEqual(
            order.amount_total, asked, places=2,
            msg="a pack sale no longer totals the cash taken")

    # -- she can still override, and it is honoured ----------------------

    def test_a_discount_comes_off_and_the_order_follows(self):
        """What she types wins, not the default."""
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.amount_paid = 150.00
        wiz.action_create_sale()

        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        self.assertAlmostEqual(
            order.amount_total, 150.00, places=2,
            msg="she took 150.00 and the order says %.2f"
                % order.amount_total)

    def test_a_discount_comes_off_the_membership_not_the_fee(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.amount_paid = 150.00
        wiz.action_create_sale()

        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        fee_line = order.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == self.matricula)
        self.assertAlmostEqual(
            fee_line.price_total, self.fee, places=2,
            msg="the discount was taken out of the registration fee. It is "
                "a fixed studio charge; the discount belongs on the "
                "membership.")

    def test_the_invoice_matches_what_she_took(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.amount_paid = 150.00
        wiz.action_create_sale()

        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        posted = order.invoice_ids.filtered(lambda i: i.state == 'posted')
        self.assertTrue(
            posted, "a cash sale raised no invoice at all")
        # Signed, because a credit note's amount_total is POSITIVE in Odoo -
        # the direction lives in move_type. Summing them raw makes a
        # reversed invoice look like double the billing.
        billed = sum(
            inv.amount_total * (-1 if inv.move_type == 'out_refund' else 1)
            for inv in posted)
        self.assertAlmostEqual(
            billed, 150.00, places=2,
            msg="the invoice is for %.2f and 150.00 was taken" % billed)

    # -- the form says WHY, every time -----------------------------------
    #
    # The breakdown used to hide itself when no fee was due. That left one
    # figure on screen that could not be told apart from a fee silently
    # missed - and after the desk collected 145.00 against a 177.23 order,
    # that is the first thing anybody checks. So the line is always there
    # and always carries a reason.

    def test_a_first_membership_is_told_the_fee_is_charged(self):
        wiz = self._wizard(self.student, self.membership, self.monthly)
        self.assertAlmostEqual(wiz.matricula_fee, self.fee, places=2)
        self.assertTrue(
            wiz.matricula_note,
            "the registration line gives no reason at all")
        self.assertIn(
            "first membership", wiz.matricula_note.lower(),
            "the note does not say why it is being charged: %r"
            % wiz.matricula_note)

    def test_a_returning_student_is_told_why_there_is_none(self):
        wiz = self._wizard(self.returning, self.membership, self.monthly)
        self.assertAlmostEqual(wiz.matricula_fee, 0.0, places=2)
        self.assertIn(
            "held a membership", wiz.matricula_note.lower(),
            "a waived fee with no explanation reads exactly like a fee "
            "that was forgotten: %r" % wiz.matricula_note)

    def test_a_quarterly_commitment_is_told_why_there_is_none(self):
        wiz = self._wizard(self.student, self.membership, self.quarterly)
        wiz._onchange_plan_id()
        self.assertAlmostEqual(wiz.matricula_fee, 0.0, places=2)
        self.assertIn(
            "waived", wiz.matricula_note.lower(),
            "the note does not say the fee was waived: %r"
            % wiz.matricula_note)

    def test_a_pack_is_told_it_carries_none(self):
        wiz = self._wizard(self.student, self.pack)
        self.assertAlmostEqual(wiz.matricula_fee, 0.0, places=2)
        self.assertIn(
            "pack", wiz.matricula_note.lower(),
            "a pack shows a blank registration line and no reason: %r"
            % wiz.matricula_note)

    def test_the_breakdown_adds_up_whether_or_not_a_fee_applies(self):
        """Package + registration = total, on every path."""
        for who, plan, label in ((self.student, self.monthly, 'first'),
                                 (self.returning, self.monthly, 'returning'),
                                 (self.student, self.quarterly, 'quarterly')):
            wiz = self._wizard(who, self.membership, plan)
            wiz._onchange_plan_id()
            self.assertAlmostEqual(
                wiz.membership_price + wiz.matricula_fee, wiz.normal_price,
                places=2,
                msg="on the %s path the breakdown does not add up: "
                    "%.2f + %.2f is not %.2f"
                    % (label, wiz.membership_price, wiz.matricula_fee,
                       wiz.normal_price))

    # -- a gift is a gift --------------------------------------------------

    def test_a_free_first_membership_carries_no_fee(self):
        """The shared builder adds the fee by the studio's rule. That rule
        is about who pays, and on a giveaway nobody does."""
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.payment_method = 'free'
        wiz.reason = 'Opening week giveaway'
        wiz._onchange_payment_method()
        self.assertAlmostEqual(
            wiz.matricula_fee, 0.0, places=2,
            msg="a gift was shown a registration fee")

        wiz.action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)], order='id desc', limit=1)
        self.assertFalse(
            order.order_line.filtered(
                lambda l: l.product_id.product_tmpl_id == self.matricula),
            "a free membership was given away with a registration fee "
            "attached, so the order came to %.2f" % order.amount_total)
        self.assertAlmostEqual(
            order.amount_total, 0.0, places=2,
            msg="a gift came to %.2f" % order.amount_total)

    # -- the guard --------------------------------------------------------

    def test_less_than_the_fee_is_refused(self):
        """Otherwise the membership goes negative and the order is absurd."""
        wiz = self._wizard(self.student, self.membership, self.monthly)
        wiz.amount_paid = self.fee - 1.0
        with self.assertRaises(UserError):
            wiz.action_create_sale()
