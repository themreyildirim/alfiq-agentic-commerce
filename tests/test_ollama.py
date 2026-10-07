import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import requests
from alfiq_b import core as c
from alfiq_b.models import build_live_adapter, live_configuration
from alfiq_b.ollama_transport import OllamaRESTClient, OLLAMA_MODEL
from alfiq_b.ollama_probe import run_probe
from alfiq_b.agent import make_agent
from alfiq_b.evaluate import run_evaluation, apply_effect
from alfiq_b.public_runner import run_public

SCHEMA = {'type':'object','properties':{'status':{'const':'ready'}},
          'required':['status'],'additionalProperties':False}

class OllamaTests(unittest.TestCase):
    def response(self,content='{"status":"ready"}',reason='stop'):
        response = MagicMock(status_code=200)
        response.json.return_value = {'model':OLLAMA_MODEL,'message':{'content':content},
                                     'done':True,'done_reason':reason,'prompt_eval_count':11,'eval_count':8}
        return response

    def test_json_schema_local_endpoint_and_actual_usage(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.return_value = self.response()
            adapter = build_live_adapter('ollama')
            self.assertEqual(adapter.generate_json(SCHEMA,{},'JSON only','connection_test'),{'status':'ready'})
            args,kwargs = post.call_args
            self.assertEqual(args[0],'http://127.0.0.1:11434/api/chat')
            self.assertEqual(kwargs['json']['format'],SCHEMA)
            self.assertEqual(kwargs['json']['options']['num_ctx'],4096)
            self.assertFalse(kwargs['json']['stream'])
            self.assertNotIn('headers',kwargs)
            self.assertEqual(adapter.traces[-1]['usage']['total_tokens'],19)
            self.assertIsNone(adapter.traces[-1]['usage']['total_cached_tokens'])
            self.assertEqual(adapter.traces[-1]['model_returned'],OLLAMA_MODEL)

    def test_truncated_response_is_not_success(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.return_value = self.response(reason='length')
            adapter = build_live_adapter('ollama')
            output = adapter.generate_json(SCHEMA,{},'JSON only','connection_test')
            self.assertEqual(output['__llm_error__'],'LLM_INCOMPLETE_RESPONSE')
            self.assertFalse(adapter.traces[-1]['schema_valid'])

    def test_probe_reports_actual_success_and_invalid_output(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.return_value = self.response()
            success = run_probe(allow_live=True)
            self.assertTrue(success['ok'])
            self.assertFalse(success['uses_llm_fixtures'])
            self.assertEqual(success['api_attempts'],1)
            post.return_value = self.response('{"status":"wrong"}')
            self.assertFalse(run_probe(allow_live=True)['ok'])

    def test_timeout_is_one_attempt_and_is_typed(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.side_effect = requests.ReadTimeout('test timeout')
            adapter = build_live_adapter('ollama')
            with self.assertRaisesRegex(c.LLMServiceError,'LLM_TIMEOUT'):
                adapter.generate_json(SCHEMA,{},'JSON only','connection_test')
            self.assertEqual(post.call_count,1)
            self.assertEqual(adapter.client.attempts,1)

    def test_bad_json_duplicate_keys_are_not_accepted(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.return_value = self.response('{"status":"ready","status":"ready"}')
            adapter = build_live_adapter('ollama')
            self.assertEqual(adapter.generate_json(SCHEMA,{},'JSON only','test')['__llm_error__'],'LLM_INVALID_JSON')

    def test_model_not_installed_returns_typed_error(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            response = MagicMock(status_code=404)
            response.json.return_value = {'error':'model not found'}
            factory.return_value.__enter__.return_value.post.return_value = response
            adapter = build_live_adapter('ollama')
            with self.assertRaisesRegex(c.LLMServiceError,'LLM_MODEL_NOT_AVAILABLE'):
                adapter.generate_json(SCHEMA,{},'JSON only','test')

    def test_local_endpoint_validation_and_explicit_live_guards(self):
        for url in ['https://example.com','http://0.0.0.0:11434','http://user:pass@localhost:11434','http://localhost:11434/path']:
            with self.assertRaises(ValueError):OllamaRESTClient(base_url=url)
        with patch('alfiq_b.ollama_transport.requests.Session') as network:
            with self.assertRaises(ValueError):run_probe()
            with self.assertRaises(ValueError):run_evaluation('unused',mode='live',provider='ollama')
            with self.assertRaises(ValueError):run_public('unused',mode='live',provider='ollama')
            network.assert_not_called()

    def test_restart_preserves_ollama_options_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as network:
            root = Path(directory)
            options = {'num_ctx':2048,'timeout':90}
            agent = make_agent(root/'active',mode='live',provider='ollama',llm_options=options,backup_root=root/'backup')
            clock = {'now':c.datetime.now(c.timezone.utc)}
            restored = apply_effect(agent,{'type':'restart_from_backup'},clock,root,'live',None)
            self.assertEqual(restored.model.client.num_ctx,2048)
            self.assertEqual(restored.model.client.timeout,90)
            self.assertEqual(restored.provider,'ollama')
            network.assert_not_called()

    def test_resume_refuses_a_changed_provider_or_context(self):
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.side_effect = requests.ReadTimeout('test timeout')
            root = Path(directory)
            report = run_evaluation(root,mode='live',provider='ollama',allow_live=True)
            self.assertFalse(report['complete'])
            self.assertEqual(report['llm_configuration']['provider'],'ollama')
            calls = factory.return_value.__enter__.return_value.post.call_count
            with self.assertRaises(ValueError):
                run_evaluation(root,mode='live',provider='ollama',allow_live=True,resume=True,llm_options={'num_ctx':2048})
            with self.assertRaises(ValueError):
                run_evaluation(root,mode='live',provider='gemini',allow_live=True,resume=True,api_key='dummy')
            self.assertEqual(factory.return_value.__enter__.return_value.post.call_count,calls)

if __name__ == '__main__':unittest.main()
