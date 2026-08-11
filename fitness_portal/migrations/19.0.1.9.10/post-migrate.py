import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Delete phantom ir.asset record left over from a deleted static file."""
    cr.execute("""
        DELETE FROM ir_asset
        WHERE path = 'fitness_portal/static/src/js/password_validation.js'
    """)
    if cr.rowcount:
        _logger.info(
            "fitness_portal migrate: removed %d phantom ir.asset record(s) "
            "for deleted file password_validation.js",
            cr.rowcount,
        )
