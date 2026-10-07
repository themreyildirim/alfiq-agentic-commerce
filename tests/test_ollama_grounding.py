import unittest
import tempfile
from unittest.mock import patch,MagicMock
from alfiq_b import core as c
from alfiq_b.models import build_live_adapter
from alfiq_b.cases import initial
from alfiq_b.ollama_transport import OLLAMA_MODEL
from alfiq_b.agent import make_agent
from alfiq_b.ollama_intent_slots import empty_slots

class LocalGroundingTests(unittest.TestCase):
    def test_omitted_literal_product_is_grounded_from_human_message(self):
        message="ALF-0039 ürününden 1 adet istiyorum. Bütçem 150 USD. Türkiye'ye (TR) gönderilecek. Hediyelik kullanım için seçiyorum."
        proposal={'schema_version':'intent-extraction.v1',
                  'patch':{'set':{'budget':'150.00','ship_to':'TR','purpose':'gift'}},
                  'evidence':[{'path':'/set/budget','quote':'150 USD'},
                              {'path':'/set/ship_to','quote':'TR'},
                              {'path':'/set/purpose','quote':'Hediyelik'}]}
        bound,binding=c.bind_literal_product_request(proposal,message,True)
        merged,codes=c.validate_extraction(bound,message,c.new_intent(),True)
        self.assertEqual(codes,[])
        self.assertEqual(merged['intent']['groups'][0]['product_ids'],['ALF-0039'])
        self.assertEqual(merged['intent']['groups'][0]['quantity'],1)
        self.assertEqual(binding['source'],'human_literal')
        self.assertNotIn('groups',proposal['patch']['set'])

    def test_negative_multi_id_and_followup_requests_are_not_bound(self):
        proposal={'patch':{'set':{}},'evidence':[]}
        for message,first in [("ALF-0039’dan 1 adet istemiyorum",True),
                              ("ALF-0039’dan 1 adet ve ALF-0017’den 1 adet",True),
                              ("ALF-0039’dan 1 adet ekle",False)]:
            bound,binding=c.bind_literal_product_request(proposal,message,first)
            self.assertIsNone(binding)
            self.assertEqual(bound,proposal)

    def context(self):
        intent=c.merge_intent(c.new_intent(),initial(budget='150.00'))['intent']
        intent['purpose']='gift'
        return {'intent':intent,
                'candidate_selections':[['ALF-0039']],
                'evidence_sentences':{'ALF-0039':['Katalog fiyatı: 49.00 USD.',
                                                'Katalog stok durumu: stokta.',
                                                c.SOFT_REASONS['tr']['gift']]}}

    def test_model_selected_references_render_exact_two_line_claims(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            response=MagicMock(status_code=200)
            response.json.return_value={'done':True,'done_reason':'stop','model':OLLAMA_MODEL,
                'message':{'content':c.canonical_json({'candidate_index':0,'fact_index':0})}}
            post=factory.return_value.__enter__.return_value.post;post.return_value=response
            adapter=build_live_adapter('ollama')
            proposal=adapter.generate_json(c.SELECTION_SCHEMA,{'context':self.context(),'repair_feedback':None},
                                           c.SELECTION_SYSTEM,'product_selection','test',1)
            self.assertEqual(proposal['selected_ids'],['ALF-0039'])
            self.assertEqual(proposal['reasons'][0]['text'],'Katalog fiyatı: 49.00 USD.\n'+c.SOFT_REASONS['tr']['gift'])
            self.assertTrue(adapter.traces[-1]['normalized_schema_valid'])
            sent=post.call_args.kwargs['json']['messages'][1]['content']
            self.assertIn('product_facts',sent)
            self.assertNotIn('evidence_sentences',sent)

    def test_out_of_range_reference_fails_closed(self):
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            response=MagicMock(status_code=200)
            response.json.return_value={'done':True,'done_reason':'stop','model':OLLAMA_MODEL,
                'message':{'content':c.canonical_json({'candidate_index':0,'fact_index':999})}}
            factory.return_value.__enter__.return_value.post.return_value=response
            adapter=build_live_adapter('ollama')
            result=adapter.generate_json(c.SELECTION_SCHEMA,{'context':self.context()},'',
                                         'product_selection','test',1)
            self.assertEqual(result['__llm_error__'],'LLM_SCHEMA_INVALID')
            self.assertFalse(adapter.traces[-1]['schema_valid'])

    def test_full_demo_with_missing_id_in_model_patch_preserves_requested_product(self):
        message="ALF-0039 ürününden 1 adet istiyorum. Bütçem 150 USD. Türkiye'ye (TR) gönderilecek. Hediyelik kullanım için seçiyorum."
        intent_wire={**empty_slots(),'budget':'150.00','ship_to':'TR','purpose':'gift'}
        selection_wire={'candidate_index':0,'fact_index':0}
        def response(wire):
            r=MagicMock(status_code=200)
            r.json.return_value={'done':True,'done_reason':'stop','model':OLLAMA_MODEL,
                                 'message':{'content':c.canonical_json(wire)},'prompt_eval_count':20,'eval_count':10}
            return r
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(intent_wire),response(selection_wire)]
            agent=make_agent(directory,mode='live',provider='ollama')
            first=agent.run_turn('regression-demo',message)
            self.assertEqual(first['status'],'ok')
            self.assertEqual(first['cart']['selected_ids'],['ALF-0039'])
            self.assertEqual(first['cart']['quote_snapshot']['net_total'],'49.00')
            second=agent.run_turn('regression-demo','Bir tane daha ekle')
            self.assertEqual(second['cart']['quote_snapshot']['net_total'],'98.00')
            third=agent.run_turn('regression-demo','Onaya gönder')
            self.assertTrue(third['approval']['pending_token_exists'])
            fourth=agent.run_turn('regression-demo','Onaylıyorum')
            self.assertEqual(fourth['cart']['state'],'approved')
            self.assertEqual(post.call_count,2)

if __name__=='__main__':unittest.main()
