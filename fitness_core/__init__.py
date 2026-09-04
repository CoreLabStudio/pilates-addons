from . import models

from .company_defaults import apply_company_details


def post_init_hook(env):
    """A fresh database never runs a migration, so the details are applied here.

    Leaving this to the migration alone meant a newly built database - which
    is what odoo.sh creates from a branch - served Terms and checkout pages
    with no company details at all.
    """
    apply_company_details(env)
