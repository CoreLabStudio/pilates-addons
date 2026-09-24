# -*- coding: utf-8 -*-
"""Let the corrected campaign invite template actually replace the broken one.

The template shipped inside <data noupdate="1"> and its email_from referenced
object.survey_id.company_id. survey.survey has no company_id, so every send
raised and was swallowed by the try/except around send_mail - the suite
stayed green while nothing was ever queued, and only odoo.sh noticed,
because it grades on ERROR lines rather than the test summary.

Changing the file to noupdate="0" is not enough on a database that already
has the record: the flag lives on the ir_model_data row, and it stays True.
The corrected template would sit in the file for ever while the database
kept the broken one.

This runs BEFORE the data files load, clears the flag, and lets the new
definition overwrite the old one on the way in. Post-migrate would be too
late - the data has already loaded by then.
"""

XMLIDS = ('mail_template_campaign_invite',)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = FALSE
         WHERE module = 'fitness_campaigns'
           AND name IN %s
    """, (XMLIDS,))
