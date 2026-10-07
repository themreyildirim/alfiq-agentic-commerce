import unittest,tempfile
from pathlib import Path
from alfiq_b.agent import make_agent,TURN_SCHEMA
from alfiq_b.cases import initial
from alfiq_b.public_runner import run_public
from alfiq_b import core as c

class SubmissionTests(unittest.TestCase):
    def test_increment_preserves_constraints_and_hydrates_matched_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            agent=make_agent(folder)
            agent.model.set_fixture(initial(budget='200.00',min_rating='4.5',min_review_count=5))
            agent.run_turn('increment','ALF-0039’dan 1 adet, 200 USD bütçe, TR gönderim, en az 4.5 puan ve 5 değerlendirme.')
            body=agent.run_turn('increment','Bir tane daha ekle')
            self.assertEqual(body['status'],'ok')
            self.assertEqual(body['cart']['quote_snapshot']['net_total'],'98.00')
            self.assertEqual(body['intent']['groups'][0]['min_review_count'],5)
            matched=body['recommendations'][0]['matched_constraints']
            self.assertEqual(matched['groups'][0]['constraints']['quantity'],2)
            self.assertEqual(matched['cart_net_total'],'98.00')
            c.Draft202012Validator(TURN_SCHEMA).validate(body)

    def test_public_live_requires_opt_in(self):
        with self.assertRaises(ValueError):run_public('unused',mode='live',api_key='dummy-test-key')

    def test_original_inputs_capture_all_outputs_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'public'
            report=run_public(output,local_state_root=Path(directory)/'active')
            self.assertTrue(report['execution_complete'])
            self.assertEqual(report['completed_cases'],23)
            self.assertEqual(report['outputs'],33)
            self.assertTrue(report['llm_fixtures'])
            self.assertEqual(run_public(output,resume=True),report)
            s5=c.read_json(output/'cases'/'S5'/'output-02.json')['output']
            self.assertFalse(s5['ok'])
            self.assertEqual(s5['error']['code'],'INVALID_ARGUMENT')
            self.assertTrue(any('approval_token' in item for item in s5['error']['details']['violations']))
            s3=c.read_json(output/'cases'/'S3'/'output-01.json')['output']
            self.assertEqual(s3['cart']['selected_ids'],['ALF-0041'])
            self.assertEqual(s3['trace']['api_attempts'],0)

if __name__=='__main__':unittest.main(verbosity=2)
