# -*- coding: utf-8 -*-
"""Every field on the duplicates list has a label of its own.

partner_ids and partner_count were both called "Contacts". Odoo warns
about that each time it reflects the model, so every fitness_portal
upgrade logged "Two fields ... have the same label" and the staging build
turned amber. The count is now "Number of contacts".

The check below runs the very reflection the upgrade runs, so it fails on
exactly the warning the build shows.
"""
import logging

from odoo.tests import TransactionCase, tagged

MODEL = 'fitness.duplicate.candidate'


@tagged('post_install', '-at_install')
class TestDuplicateCandidateLabels(TransactionCase):

    def test_reflecting_the_model_logs_no_same_label_warning(self):
        logger = logging.getLogger('odoo.addons.base.models.ir_model')
        with self.assertLogs(logger, 'WARNING') as logs:
            self.env['ir.model.fields']._reflect_fields([MODEL])
            # assertLogs wants at least one record; this marker is it.
            logger.warning('label check done')
        same = [line for line in logs.output if 'have the same label' in line]
        self.assertEqual(same, [], 'the upgrade still warns about a shared label')

    def test_labels_are_unique(self):
        labels = {}
        for name, field in self.env[MODEL]._fields.items():
            labels.setdefault(field.string, []).append(name)
        shared = {label: names for label, names in labels.items() if len(names) > 1}
        self.assertEqual(shared, {}, 'two fields share a label')

    def test_the_count_is_translated(self):
        field = self.env['ir.model.fields']._get(MODEL, 'partner_count')
        self.assertEqual(field.field_description, 'Number of contacts')
        for lang, expected in (('es_ES', 'Número de contactos'),
                               ('ca_ES', 'Nombre de contactes')):
            if not self.env['res.lang']._lang_get(lang):
                continue  # the odoo.sh build installs English only
            self.assertEqual(field.with_context(lang=lang).field_description,
                             expected, '%s label of partner_count' % lang)
