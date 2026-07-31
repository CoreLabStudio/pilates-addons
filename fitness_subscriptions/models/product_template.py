from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fitness_is_subscription_plan = fields.Boolean(
        "Is Fitness Subscription Plan",
        default=False,
        help="Enable for recurring fitness plans. Activates weekly-allowance "
             "tracking on the subscription (sale.order).",
    )
    fitness_is_clase_fija = fields.Boolean(
        "Is Clase Fija Plan",
        default=False,
        help="When enabled, confirming or renewing a subscription automatically "
             "creates bookings for every occurrence of the member's fixed class "
             "slot within the billing period (auto-placement).",
    )

    # ── ENFORCEMENT fields — read by validate_subscription_for_booking() and
    #    _select_payment_source(). These are the authoritative cap values. ────────

    weekly_class_allowance = fields.Integer(
        "Weekly Class Allowance",
        default=0,
        help="Maximum allowance-paid bookings a member may make in one ISO week "
             "(Mon 00:00 – Sun 23:59). Admin-editable; changes take effect "
             "immediately for all new bookings. Ignored for unlimited plans.",
    )
    fitness_promo_first_cycle_bonus = fields.Integer(
        "Promo First-Cycle Bonus (Floating Credits)",
        default=0,
        help="Floating credits granted once when this subscription is first confirmed "
             "(first cycle only). Set to 1 for '+1 Promo' plans; 0 for all others. "
             "Not applied on renewal.",
    )
    is_unlimited = fields.Boolean(
        "Unlimited",
        default=False,
        help="When enabled, the weekly class allowance is not enforced — "
             "any number of classes may be booked against this plan, subject to "
             "normal capacity/overlap rules.",
    )

    # ── REPORTING ONLY — DO NOT read in validation or _select_payment_source ─────
    # This field previously stored the monthly cap (4 / 8 / 12). Enforcement has
    # moved to weekly_class_allowance above. This field is now a running total of
    # classes attended in the current billing cycle across all subscriptions on this
    # plan; it is incremented on every booking (allowance-paid and floating-credit)
    # and reset to 0 at cycle renewal. Its values on the product record are legacy
    # (4 / 8 / 12) and have no operational effect.
    monthly_class_allowance = fields.Integer(
        "Monthly Class Allowance (legacy / reporting only)",
        default=0,
        help="REPORTING ONLY. Previously the monthly cap; now a running total of "
             "classes attended this billing cycle. Not used to enforce any booking "
             "limit. See Weekly Class Allowance for the active cap.",
    )

    # Discipline restriction reuses the same two-field model as fitness_packages
    # (fitness_class_type + fitness_session_type, defined on product.template
    # by the fitness_packages module) — no new discipline field is introduced.
