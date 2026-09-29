# -*- coding: utf-8 -*-
"""The registration fee totals what the studio charges for it.

Yoleyva reported an order where the Registration (Matricula) line read
32.23 a unit and 26.64 net, against a fee the studio sells at 39.00
including tax. She was right, and it was not a display problem: the
line was genuinely built at the wrong price, so every membership that
carried a registration fee had been undercharged 6.77.

The cause is one line of arithmetic done twice. The fee was priced by
taking the tax-EXCLUDED figure out of fitness_taxed_price and writing it
as price_unit. That is correct only where the tax is configured
price-EXCLUDED. On this database all 44 sellable products carry one tax,
21% G, set to tax_included - so Odoo read the already-reduced 32.23 as
the gross and reduced it again.

These assert on the TOTAL of the line rather than on price_unit,
deliberately. price_unit means different things under the two tax
configurations, and a test that pins it would pass on a database
configured the other way while the student was charged the wrong money.
What the studio and the student both care about is what the order comes
to.
"""

from odoo.tests import TransactionCase, tagged

MATRICULA = 'fitness_subscriptions.product_matricula'


@tagged("post_install", "-at_install")
class TestMatriculaIsChargedInFull(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matricula = cls.env.ref(MATRICULA).sudo()
        cls.plan_monthly = cls.env['sale.subscription.plan'].sudo().create({
            'name': 'Matricula Test Mensual',
            'billing_period_value': 1, 'billing_period_unit': 'month'})
        cls.plan_quarterly = cls.env['sale.subscription.plan'].sudo().create({
            'name': 'Matricula Test Trimestral',
            'billing_period_value': 3, 'billing_period_unit': 'month'})
        cls.membership = cls.env['product.template'].sudo().create({
            'name': 'Matricula Test Membership', 'type': 'service',
            'list_price': 145.0, 'sale_ok': True,
            'fitness_is_subscription_plan': True,
            'fitness_class_type': 'barre',
            'fitness_session_type': 'group',
            'taxes_id': [(6, 0, cls.matricula.taxes_id.ids)],
        })
        cls.student = cls.env['res.partner'].sudo().create(
            {'name': 'Matricula Test Student'})

    def _order_from(self, product, partner, plan):
        lines = product.fitness_order_line_vals(partner, plan=plan)
        self.assertTrue(lines, "the product built no lines at all")
        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'order_line': [(0, 0, line) for line in lines],
        })
        return order

    def _matricula_line(self, order):
        return order.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == self.matricula)

    # -- the fault Yoleyva reported --------------------------------------

    def test_the_fee_totals_what_the_studio_charges(self):
        order = self._order_from(
            self.membership, self.student, self.plan_monthly)
        line = self._matricula_line(order)
        self.assertEqual(
            len(line), 1,
            "a first monthly membership should carry one registration fee")

        expected = self.matricula.fitness_effective_price()
        self.assertAlmostEqual(
            line.price_total, expected, places=2,
            msg="the registration fee totals %.2f, and the studio sells it "
                "at %.2f. price_unit on the line is %.2f."
                % (line.price_total, expected, line.price_unit))

    def test_it_is_not_reduced_twice(self):
        """The specific arithmetic that went wrong, named."""
        order = self._order_from(
            self.membership, self.student, self.plan_monthly)
        line = self._matricula_line(order)

        gross = self.matricula.fitness_effective_price()
        taxes = self.matricula.taxes_id.filtered(
            lambda t: t.company_id == self.env.company)
        if not taxes:
            self.skipTest("no tax on the registration product here")
        once_reduced = taxes.compute_all(
            gross, currency=self.matricula.currency_id, quantity=1.0,
        )['total_excluded']

        self.assertNotAlmostEqual(
            line.price_total, once_reduced, places=2,
            msg="the line totals %.2f, which is the fee with the tax taken "
                "off once. It was written as price_unit and Odoo took it "
                "off again." % line.price_total)

    def test_the_membership_line_is_unaffected(self):
        """The pack line was always right; it must stay right."""
        order = self._order_from(
            self.membership, self.student, self.plan_monthly)
        pack = order.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id == self.membership)
        self.assertEqual(len(pack), 1)
        self.assertAlmostEqual(
            pack.price_total, 145.0, places=2,
            msg="the membership itself now totals %.2f instead of 145.00"
                % pack.price_total)

    def test_the_order_total_is_the_two_added_up(self):
        order = self._order_from(
            self.membership, self.student, self.plan_monthly)
        expected = 145.0 + self.matricula.fitness_effective_price()
        self.assertAlmostEqual(
            order.amount_total, expected, places=2,
            msg="the order comes to %.2f; the student owes %.2f"
                % (order.amount_total, expected))

    # -- the rules around it, which must not have moved ------------------

    def test_three_months_still_waives_it(self):
        order = self._order_from(
            self.membership, self.student, self.plan_quarterly)
        self.assertFalse(
            self._matricula_line(order),
            "a quarterly commitment waives the registration fee, and one "
            "was charged")

    def test_a_second_membership_still_waives_it(self):
        first = self._order_from(
            self.membership, self.student, self.plan_monthly)
        first.action_confirm()

        second = self._order_from(
            self.membership, self.student, self.plan_monthly)
        self.assertFalse(
            self._matricula_line(second),
            "the registration fee is charged once, and this is her second "
            "membership")

    def test_the_desk_and_the_portal_build_the_same_fee(self):
        """One builder, so the two screens cannot drift apart."""
        portal = self._order_from(
            self.membership, self.student, self.plan_monthly)
        desk_lines = self.membership.fitness_order_line_vals(
            self.student, plan=self.plan_monthly, total_price=145.0)
        desk = self.env['sale.order'].sudo().create({
            'partner_id': self.student.id,
            'order_line': [(0, 0, line) for line in desk_lines],
        })
        self.assertAlmostEqual(
            self._matricula_line(portal).price_total,
            self._matricula_line(desk).price_total, places=2,
            msg="the registration fee differs between a portal purchase "
                "and a desk sale")
