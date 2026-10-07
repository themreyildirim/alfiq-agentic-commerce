import tempfile
import unittest
from pathlib import Path
from alfiq_b import core as c
from alfiq_b.evaluate import run_evaluation


class DiagnosticEvaluationTests(unittest.TestCase):
    def test_subset_five_repeats_includes_stock_effects_but_cannot_claim_full_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            report=run_evaluation(directory,case_ids=['P02-spa-pair','M11-stock-drift'],repetitions=5)
            self.assertTrue(report['complete'])
            self.assertEqual(report['scope'],'diagnostic_subset')
            self.assertFalse(report['is_full_acceptance_report'])
            self.assertEqual(report['coverage']['cases'],2)
            self.assertEqual(report['coverage']['completed_case_runs'],10)
            self.assertEqual(report['coverage']['completed_turns'],25)
            self.assertEqual(report['failures'],[])
            self.assertEqual(report['store_invariant_failures'],[])
            self.assertTrue(all(report['thresholds'].values()))
            self.assertFalse(report['offline_controls_passed'])
            self.assertFalse(report['live_acceptance_passed'])
            self.assertFalse(report['llm_interpretation_and_ranking_verified'])

    def test_subset_resume_does_not_duplicate_results_and_rejects_another_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            first=run_evaluation(directory,case_ids=['P02-spa-pair'],repetitions=5)
            resumed=run_evaluation(directory,case_ids=['P02-spa-pair'],repetitions=5,resume=True)
            self.assertEqual(first,resumed)
            self.assertEqual(len((Path(directory)/'results.jsonl').read_text(encoding='utf-8').splitlines()),5)
            with self.assertRaises(ValueError):
                run_evaluation(directory,case_ids=['M11-stock-drift'],repetitions=5,resume=True)
            with self.assertRaises(ValueError):
                run_evaluation(directory,repetitions=5,resume=True)

    def test_invalid_diagnostic_ids_fail_before_running(self):
        with tempfile.TemporaryDirectory() as directory:
            for ids in [[],['P02-spa-pair','P02-spa-pair'],['NON_EXISTENT'],['P02-spa-pair',None],'P02-spa-pair']:
                with self.assertRaises(ValueError):run_evaluation(directory,case_ids=ids)
            self.assertFalse((Path(directory)/'results.jsonl').exists())
