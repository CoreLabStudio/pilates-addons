import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Set SQL DEFAULT on res_partner.autopost_bills.

    Odoo 19's _create() omits columns from the INSERT when they are absent
    from the 'stored' dict, emitting SQL_DEFAULT instead.  For that to work,
    the DB column must have a SQL-level DEFAULT.  The account module defines
    autopost_bills as required=True, default='ask', which Odoo sets as a SQL
    DEFAULT on a fresh install.  DB-upgraded instances (ours) have the NOT
    NULL constraint but no SQL DEFAULT, causing every auth_signup setUpClass
    to fail with NotNullViolation when the ORM creates a res.partner without
    explicitly passing autopost_bills.
    """
    cr.execute("""
        SELECT column_default
        FROM information_schema.columns
        WHERE table_name = 'res_partner'
          AND column_name = 'autopost_bills'
    """)
    row = cr.fetchone()
    if row is None:
        # Column does not exist yet; account module will create it with DEFAULT.
        return
    if row[0] is None:
        cr.execute(
            "ALTER TABLE res_partner ALTER COLUMN autopost_bills SET DEFAULT 'ask'"
        )
        _logger.info(
            "fitness_portal 19.0.1.9.11: added SQL DEFAULT 'ask' on "
            "res_partner.autopost_bills (fixes NotNullViolation in test setUp)"
        )
    else:
        _logger.info(
            "fitness_portal 19.0.1.9.11: res_partner.autopost_bills already "
            "has SQL DEFAULT %s — skipped", row[0]
        )
