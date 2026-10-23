"""Actual F preparation source-set controls; no D write/SQLite/subprocess."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'scripts/repair-2026-10-08/audit-jpg-D-journal-campaign.py'
spec=importlib.util.spec_from_file_location('jpg_D_source_control_audit',SOURCE);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
RECIPE=Path(sys.argv[1]).absolute();sys.argv=sys.argv[:1]
audit.require(RECIPE.is_relative_to(ROOT/'docs/repair-2026-10-08/jpg-D-journal-preparations'),'F_actual_preparation_recipe_scope')
value=audit.read(RECIPE);DROOT=Path(value['store']);D_BEFORE=DROOT.exists()

class Controls(unittest.TestCase):
    def test_actual_prepared_95_source_roles(self):
        rows=audit.verify_recipe_source_set(value);self.assertEqual(len(rows),95);self.assertFalse(D_BEFORE);self.assertEqual(value['sourceTaskCount'],87);self.assertEqual(value['unsupportedTaskCount'],86)
    def test_missing_duplicate_extra_or_mutated_source_rejected(self):
        missing=copy.deepcopy(value);missing['sourcePins'].pop()
        duplicate=copy.deepcopy(value);duplicate['sourcePins'].append(duplicate['sourcePins'][0])
        extra=copy.deepcopy(value);extra['sourcePins'].append(audit.pin(Path(__file__)))
        bad=copy.deepcopy(value);bad['sourcePins'][0]['sha256']='0'*64
        for v in(missing,duplicate,extra,bad):
            with self.assertRaises(RuntimeError):audit.verify_recipe_source_set(v)
    def test_other_family_or_real_provider_cannot_claim_foundation(self):
        for key,new in [('family','scientific-journal-v2'),('mode','real-provider'),('protocol','jpg-journal-recipe-v1'),('formalPaidReady',True)]:
            v=copy.deepcopy(value);v[key]=new
            with self.assertRaisesRegex(RuntimeError,'D_engineering_only_recipe'):audit.verify_recipe_source_set(v)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls));audit.require(DROOT.exists()==D_BEFORE,'D_path_changed_by_F_control')
    out=ROOT/'docs/repair-2026-10-08/jpg-D-source-set-controls'/uuid.uuid4().hex;out.mkdir(parents=True,exist_ok=False)
    audit.save(out/'result.json',{'protocol':'jpg-D-source-set-F-controls-v1','sourcePin':audit.pin(SOURCE),'testPin':audit.pin(Path(__file__)),'actualPreparationRecipePin':audit.pin(RECIPE),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'DWrites':0,'models':0,'DockerOperations':0,'DStoreExistsBefore':D_BEFORE,'DStoreExistsAfter':DROOT.exists(),'actualNamespaceValidated':False,'benchmarkTrialRequirementMet':False,'paidReady':False})
    print(str(out/'result.json'));sys.exit(not result.wasSuccessful())
