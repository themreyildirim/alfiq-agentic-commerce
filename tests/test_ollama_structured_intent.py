import tempfile
import unittest
from unittest.mock import MagicMock, patch
from jsonschema import ValidationError
from alfiq_b import core as c
from alfiq_b.agent import make_agent
from alfiq_b.models import build_live_adapter
from alfiq_b.ollama_intent_slots import empty_slots,group_slots,compile_slots,allowed_categories,normalize_product_query,requested_group_count,numeric_filter_permissions,budget_operator_permission


def response(body):
    result = MagicMock(status_code=200)
    result.json.return_value = {
        'done': True, 'done_reason': 'stop',
        'model': 'qwen3:4b-instruct-2507-q4_K_M',
        'message': {'content': c.canonical_json(body)},
        'prompt_eval_count': 20, 'eval_count': 10,
    }
    return result


class StructuredIntentTests(unittest.TestCase):
    def payload(self, first=True):
        return {'user_message': '100 dolar altında, iyi puanlı bir ürün öner',
                'current_intent': c.new_intent(), 'first_request': first,
                'cart_state': None, 'patch_contract': c.INTENT_PATCH_SCHEMA,
                'category_vocabulary': sorted(set(c.CATEGORY_ALIASES.values())),
                'policy_reference': {}, 'repair_feedback': None}

    def test_provider_grammar_constrains_slots_and_compiles_real_evidence(self):
        slots = {**empty_slots(),'budget':'100.00',
                 'groups':[group_slots(quantity=1,min_rating='4.5')]}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.return_value = response(slots)
            adapter = build_live_adapter('ollama')
            wire = adapter.generate_json(c.INTENT_WIRE_SCHEMA, self.payload(),
                                         c.INTENT_SYSTEM, 'intent_extraction', 'nested-test', 1)
            decoded, errors = c.decode_intent_wire(wire)
            self.assertEqual(errors, [])
            self.assertEqual(decoded['patch'],{'set':{'budget':'100.00','groups':[{'quantity':1,'min_rating':'4.5'}]}})
            merged, errors = c.validate_extraction(decoded,self.payload()['user_message'],c.new_intent(),True)
            self.assertEqual(errors,[])
            self.assertEqual(merged['intent']['groups'][0]['min_rating'],'4.5')
            self.assertEqual({item['path'] for item in decoded['evidence']},{'/set/budget','/set/groups'})
            grammar = post.call_args.kwargs['json']['format']
            self.assertNotIn('min_rating', grammar['properties'])
            self.assertNotIn('evidence', grammar['properties'])
            group = grammar['properties']['groups']['anyOf'][0]['items']
            self.assertIn('min_rating', group['properties'])
            self.assertEqual(set(grammar['required']),set(grammar['properties']))
            self.assertFalse(grammar['additionalProperties'])

    def test_observed_top_level_rating_error_still_fails_closed(self):
        bad = {'schema_version': 'intent-extraction.v1',
               'patch': {'set': {'min_rating': '4.5'}}, 'evidence': []}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.return_value = response(bad)
            adapter = build_live_adapter('ollama')
            wire = adapter.generate_json(c.INTENT_WIRE_SCHEMA, self.payload(),
                                         c.INTENT_SYSTEM, 'intent_extraction', 'bad-nested-test', 1)
            self.assertEqual(wire['__llm_error__'], 'LLM_SCHEMA_INVALID')
            self.assertFalse(adapter.traces[-1]['schema_valid'])

    def test_followup_slots_compile_updates_and_preserve_inherited_constraints(self):
        body = {**empty_slots(),'groups':[group_slots(quantity=2)]}
        payload=self.payload(False)
        payload['user_message']='2 adet olsun'
        payload['current_intent']=c.merge_intent(c.new_intent(),{
            'set':{'budget':'100.00','ship_to':'TR','groups':[{'quantity':1,'min_rating':'4.5','min_review_count':5}]}})['intent']
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.return_value = response(body)
            wire=build_live_adapter('ollama').generate_json(
                c.INTENT_WIRE_SCHEMA, payload, '', 'intent_extraction', 'followup', 1)
            decoded,errors=c.decode_intent_wire(wire)
            self.assertEqual(errors,[])
            self.assertNotIn('set',decoded['patch'])
            merged,errors=c.validate_extraction(decoded,payload['user_message'],payload['current_intent'],False)
            self.assertEqual(errors,[])
            self.assertEqual(merged['intent']['budget'],'100.00')
            self.assertEqual(merged['intent']['ship_to'],'TR')
            self.assertEqual(merged['intent']['groups'][0],{'quantity':2,'min_rating':'4.5','min_review_count':5})

    def test_strict_budget_bound_is_grounded_in_matching_human_amount(self):
        for message in ['100 dolar altında', '100 doların altında', 'Under 100 dollars', '100 USD altı']:
            proposal = {'schema_version': 'intent-extraction.v1',
                        'patch': {'set': {'budget': '100.00', 'budget_operator': 'lte'}},
                        'evidence': [{'path': '/set/budget', 'quote': message},
                                     {'path': '/set/budget_operator', 'quote': message}]}
            bound, binding = c.bind_literal_budget_operator(proposal, message)
            self.assertEqual(bound['patch']['set']['budget_operator'], 'lt')
            self.assertEqual(binding['source'], 'human_literal')
            _, errors = c.validate_extraction(bound, message, c.new_intent(), True)
            self.assertEqual(errors, [])
            self.assertEqual(proposal['patch']['set']['budget_operator'], 'lte')
        untouched, binding = c.bind_literal_budget_operator(proposal, 'Under 50 dollars')
        self.assertEqual(untouched, proposal)
        self.assertIsNone(binding)
        for message in ['not under 100 dollars','100 dolar altında olmasın']:
            untouched, binding = c.bind_literal_budget_operator(proposal, message)
            self.assertEqual(untouched, proposal)
            self.assertIsNone(binding)

    def test_literal_product_binding_preserves_rating_evidence(self):
        message = 'ALF-0039’dan 1 adet; en az 4.5 puan ve 5 değerlendirme.'
        proposal = {'schema_version': 'intent-extraction.v1',
                    'patch': {'set': {'groups': [{'quantity': 1, 'min_rating': '4.5', 'min_review_count': 5}]}},
                    'evidence': [{'path': '/set/groups', 'quote': message}]}
        bound, _ = c.bind_literal_product_request(proposal, message, True)
        merged, errors = c.validate_extraction(bound, message, c.new_intent(), True)
        self.assertEqual(errors, [])
        self.assertEqual(merged['intent']['groups'][0]['min_rating'], '4.5')
        self.assertEqual(merged['intent']['groups'][0]['min_review_count'], 5)

    def test_missing_explicit_id_cannot_be_replaced_when_quantity_omitted(self):
        message = 'ALF-0099 kodlu ürünü 100 dolara sepete ekle'
        proposal = {**empty_slots(),'action':'add_to_cart'}
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post = factory.return_value.__enter__.return_value.post
            post.return_value = response(proposal)
            agent = make_agent(directory, mode='live', provider='ollama')
            turn = agent.run_turn('missing-id-regression', message)
            self.assertEqual(turn['status'], 'rejected')
            self.assertEqual(turn['reason_code'], 'PRODUCT_NOT_FOUND')
            self.assertIsNone(turn['cart'])
            self.assertEqual(turn['recommendations'], [])
            self.assertEqual(post.call_count, 1)

    def test_compiled_quote_does_not_accept_a_fabricated_numeric_constraint(self):
        slots={**empty_slots(),'budget':'500.00'}
        with self.assertRaises(ValidationError):
            compile_slots(slots,self.payload())
        # Defense in depth: bypassing the provider guard still fails the
        # controller's independent numeric evidence check.
        proposal={'schema_version':'intent-extraction.v1','patch':{'set':{'budget':'500.00'}},
                  'evidence':[{'path':'/set/budget','quote':self.payload()['user_message']}]}
        _,errors=c.validate_extraction(proposal,self.payload()['user_message'],c.new_intent(),True)
        self.assertIn('INTENT_NUMBER_NOT_IN_EVIDENCE',errors)

    def test_money_formatting_preserves_amount_and_rejects_rounding(self):
        slots={**empty_slots(),'budget':'100'}
        proposal=compile_slots(slots,self.payload())
        self.assertEqual(proposal['patch']['set']['budget'],'100.00')
        slots['budget']='100.009'
        with self.assertRaises(ValueError):
            compile_slots(slots,self.payload())

    def test_category_hints_require_explicit_human_mentions(self):
        vocabulary=sorted(set(c.CATEGORY_ALIASES.values()))
        self.assertEqual(allowed_categories('100 dolar altında, iyi puanlı, hediyelik bir ürün öner',vocabulary),[])
        self.assertEqual(allowed_categories('Bir spa işletmesi için 2 ürün öner',vocabulary),['Spa & Wellness'])
        self.assertEqual(allowed_categories('spaghetti için bir hediye',vocabulary),[])
        self.assertEqual(allowed_categories('spa istemiyorum',vocabulary),[])
        self.assertEqual(allowed_categories('not Spa & Wellness',vocabulary),[])
        self.assertEqual(allowed_categories('En ucuz bardağı öner',vocabulary),[])
        self.assertEqual(allowed_categories('12 adet bakır bardak seti',vocabulary),['Copper Drinkware'])

    def test_unrequested_spa_category_is_rejected_if_provider_ignores_grammar(self):
        slots={**empty_slots(),'budget':'100.00','budget_operator':'lt','purpose':'gift',
               'groups':[group_slots(category='Spa & Wellness',quantity=1,min_rating='4.5')]}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.return_value=response(slots)
            adapter=build_live_adapter('ollama')
            result=adapter.generate_json(c.INTENT_WIRE_SCHEMA,self.payload(),c.INTENT_SYSTEM,
                                         'intent_extraction','category-regression',1)
            self.assertEqual(result['__llm_error__'],'LLM_SCHEMA_INVALID')
            schema=post.call_args.kwargs['json']['format']
            self.assertEqual(schema['properties']['groups']['anyOf'][0]['items']['properties']['category'],{'type':'null'})

    def test_generic_gift_without_spa_filter_has_a_feasible_grounded_cart(self):
        message='100 dolar altında, iyi puanlı, hediyelik bir ürün öner'
        slots={**empty_slots(),'budget':'100.00','budget_operator':'lt','purpose':'gift',
               'groups':[group_slots(quantity=1,min_rating='4.5')]}
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('gift-category-regression',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['intent']['budget'],'100.00')
            self.assertEqual(turn['intent']['budget_operator'],'lt')
            self.assertEqual(turn['intent']['groups'],[{'quantity':1,'min_rating':'4.5'}])
            self.assertIsNotNone(turn['cart'])
            self.assertLess(c.Decimal(turn['cart']['quote_snapshot']['net_total']),c.Decimal('100.00'))
            self.assertEqual(post.call_count,2)

    def test_selected_pair_gets_exactly_its_own_grounded_reasons(self):
        context = {'intent': c.new_intent(), 'candidate_selections': [['ALF-0017', 'ALF-0039']],
                   'evidence_sentences': {'ALF-0017': ['Katalog fiyatı: 89.00 USD.'],
                                          'ALF-0039': ['Katalog fiyatı: 49.00 USD.']}}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.return_value = response(
                {'candidate_index': 0, 'fact_index': 0})
            adapter = build_live_adapter('ollama')
            selected = adapter.generate_json(c.SELECTION_SCHEMA, {'context': context}, '',
                                             'product_selection', 'pair-test', 1)
            self.assertEqual(selected['selected_ids'], ['ALF-0017', 'ALF-0039'])
            self.assertEqual([r['product_id'] for r in selected['reasons']], ['ALF-0017', 'ALF-0039'])
            self.assertTrue(selected['reasons'][1]['text'].startswith('Katalog fiyatı: 49.00 USD.'))

    def test_observed_gift_query_is_normalized_and_audited_without_losing_filters(self):
        message='100 dolar altında, iyi puanlı, hediyelik bir ürün öner'
        slots={**empty_slots(),'budget':'100.00','budget_operator':'lt','purpose':'gift',
               'groups':[group_slots(query='gift',quantity=1,min_rating='4.5')]}
        original=c.deepcopy(slots)
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('gift-query-regression',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['intent']['groups'],[{'quantity':1,'min_rating':'4.5'}])
            self.assertEqual(turn['intent']['budget'],'100.00')
            self.assertEqual(turn['intent']['purpose'],'gift')
            self.assertEqual(turn['intent']['budget_operator'],'lt')
            records=[c.json.loads(line) for line in (c.REPORT_DIR/'ollama_intent_refs.jsonl').read_text(encoding='utf-8').splitlines()]
            record=next(item for item in reversed(records) if item['session_id']=='gift-query-regression')
            self.assertEqual(record['slots']['groups'][0]['query'],'gift')
            self.assertEqual(record['query_normalizations'][0]['code'],'PURPOSE_ONLY_QUERY_REMOVED')
            self.assertEqual(post.call_count,2)
        self.assertEqual(slots,original)

    def test_purpose_query_normalization_preserves_product_and_literal_searches(self):
        for query,message in [('coffee','Hediyelik kahve ürünü öner'),('tea','A gift for a tea lover'),
                              ('gift box','Looking for a gift box'),('gift','"gift" kelimesiyle ara')]:
            self.assertEqual(normalize_product_query(query,message),(query,None))
        for message in ['Hediyelik bir ürün öner','Suggest a well rated gift under 80 dollars',
                        'Bir hediye öner, kahve istemiyorum','A gift, not coffee']:
            value,record=normalize_product_query('gift',message)
            self.assertIsNone(value)
            self.assertEqual(record['quote'],message)
        self.assertEqual(normalize_product_query('gift','Search available items'),('gift',None))

    def test_purpose_query_cannot_silently_drop_an_explicit_product_type(self):
        for message in ['Hediyelik kahve ürünü öner','A gift for a tea lover','Hediyelik bir şişe öner']:
            with self.assertRaisesRegex(ValueError,'explicitly requested product type'):
                normalize_product_query('gift',message)

    def test_generic_gift_followup_preserves_inherited_product_query(self):
        payload=self.payload(False)
        payload['user_message']='Hediyelik olsun'
        payload['current_intent']=c.merge_intent(c.new_intent(),{
            'set':{'groups':[{'query':'coffee','quantity':1}],'budget':'80.00'}})['intent']
        slots={**empty_slots(),'purpose':'gift','groups':[group_slots(query='gift')]}
        proposal=compile_slots(slots,payload)
        merged,errors=c.validate_extraction(proposal,payload['user_message'],payload['current_intent'],False)
        self.assertEqual(errors,[])
        self.assertEqual(merged['intent']['groups'],[{'query':'coffee','quantity':1}])
        self.assertEqual(merged['intent']['budget'],'80.00')
        self.assertEqual(merged['intent']['purpose'],'gift')

    def test_initial_product_count_requires_positive_unambiguous_phrase(self):
        for message,count in [('300 dolar bütçeyle 2 ürün öner',2),('Spa için 3 farklı üründen bir set kur',3),
                              ('Recommend two different products',2),('İki ürün öner',2),('Choose 4 items',4)]:
            binding=requested_group_count(message,True)
            self.assertEqual(binding['count'],count)
            self.assertIn(binding['quote'],message)
            self.assertIsNone(requested_group_count(message,False))
        for message in ['2 adet olsun','20 kişiye hediye','ALF-0039 ürününden 2 adet',
                        '2 aynı ürün','2 ürün istemiyorum','not two products','no more than 2 products',
                        'en fazla 2 ürün','en az 3 ürün','2-3 ürün','2 ürün ve 3 ürün']:
            self.assertIsNone(requested_group_count(message,True),message)

    def test_missing_second_product_is_rejected_even_when_provider_ignores_grammar(self):
        payload=self.payload()
        payload['user_message']='Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner'
        slots={**empty_slots(),'budget':'300.00','purpose':'spa',
               'groups':[group_slots(category='Spa & Wellness',quantity=1)]}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.return_value=response(slots)
            adapter=build_live_adapter('ollama')
            wire=adapter.generate_json(c.INTENT_WIRE_SCHEMA,payload,c.INTENT_SYSTEM,
                                       'intent_extraction','count-regression',1)
            self.assertEqual(wire['__llm_error__'],'LLM_SCHEMA_INVALID')
            schema=post.call_args.kwargs['json']['format']['properties']['groups']
            self.assertEqual(schema['minItems'],2)
            self.assertEqual(schema['maxItems'],2)
            self.assertNotIn('anyOf',schema)
            # The compiler independently enforces the same count.
            with self.assertRaises(ValidationError):
                compile_slots(slots,payload)

    def test_spa_pair_retains_two_groups_and_selects_two_distinct_products(self):
        message='Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner'
        slots={**empty_slots(),'budget':'300.00','purpose':'spa',
               'groups':[group_slots(category='Spa & Wellness',quantity=1,group_index=i) for i in range(2)]}
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('spa-count-regression',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['intent']['groups'],[{'category':'Spa & Wellness','quantity':1} for _ in range(2)])
            self.assertEqual(len(set(turn['cart']['selected_ids'])),2)
            self.assertEqual(turn['cart']['quote_snapshot']['net_total'],'207.00')
            self.assertEqual(post.call_count,2)

    def test_product_count_does_not_double_each_groups_unit_quantity(self):
        payload=self.payload()
        payload['user_message']='Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner'
        slots={**empty_slots(),'groups':[group_slots(quantity=2,group_index=i) for i in range(2)]}
        with self.assertRaises(ValidationError):
            compile_slots(slots,payload)
        payload['user_message']='2 farklı ürün öner, her birinden 3 adet istiyorum'
        self.assertEqual(requested_group_count(payload['user_message'],True)['unit_quantity_default'],None)
        slots['groups']=[group_slots(quantity=3,group_index=i) for i in range(2)]
        proposal=compile_slots(slots,payload)
        self.assertEqual([group['quantity'] for group in proposal['patch']['set']['groups']],[3,3])

    def test_unrequested_rating_and_review_defaults_fail_closed_even_if_grammar_is_ignored(self):
        payload=self.payload()
        payload['user_message']='Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner'
        # Observed v4.3 response: both groups exist, but numeric filters were fabricated.
        slots={**empty_slots(),'budget':'300.00','purpose':'spa','groups':[
            group_slots(category='Spa & Wellness',quantity=1,min_rating='4.5',min_review_count=0,group_index=i)
            for i in range(2)]}
        with patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.return_value=response(slots)
            adapter=build_live_adapter('ollama')
            wire=adapter.generate_json(c.INTENT_WIRE_SCHEMA,payload,c.INTENT_SYSTEM,
                                       'intent_extraction','invented-numeric-regression',1)
            self.assertEqual(wire['__llm_error__'],'LLM_SCHEMA_INVALID')
            fields=post.call_args.kwargs['json']['format']['properties']['groups']['items']['properties']
            self.assertEqual(fields['min_rating'],{'type':'null'})
            self.assertEqual(fields['min_review_count'],{'type':'null'})
            with self.assertRaises(ValidationError):
                compile_slots(slots,payload)

    def test_numeric_filter_permissions_keep_requested_filters_available(self):
        for message,expected in [
            ('Spa için 2 ürün',{'min_rating':False,'min_review_count':False}),
            ('iyi puanlı hediyelik ürün',{'min_rating':True,'min_review_count':False}),
            ('a well-rated gift',{'min_rating':True,'min_review_count':False}),
            ('en az 4,5 puan ve 5 değerlendirme',{'min_rating':True,'min_review_count':True}),
            ('at least 4.5 stars and 10 reviews',{'min_rating':True,'min_review_count':True}),
            ('en az 10 yorumlu',{'min_rating':False,'min_review_count':True}),
        ]:
            self.assertEqual(numeric_filter_permissions(message),expected,message)

    def test_review_followup_updates_only_review_count_and_preserves_other_filters(self):
        payload=self.payload(False)
        payload['user_message']='En az 10 değerlendirme olsun'
        payload['current_intent']=c.merge_intent(c.new_intent(),{
            'set':{'budget':'100.00','groups':[{'quantity':1,'min_rating':'4.5','min_review_count':5}]}})['intent']
        slots={**empty_slots(),'groups':[group_slots(min_review_count=10)]}
        proposal=compile_slots(slots,payload)
        merged,errors=c.validate_extraction(proposal,payload['user_message'],payload['current_intent'],False)
        self.assertEqual(errors,[])
        self.assertEqual(merged['intent']['groups'],[{'quantity':1,'min_rating':'4.5','min_review_count':10}])
        self.assertEqual(merged['intent']['budget'],'100.00')

    def test_plain_budget_cannot_be_made_strict_without_human_comparison(self):
        payload=self.payload()
        payload['user_message']='Spa için 300 dolar bütçe'
        slots={**empty_slots(),'budget':'300.00','budget_operator':'lt','purpose':'spa'}
        with self.assertRaises(ValidationError):
            compile_slots(slots,payload)
        slots['budget_operator']='lte'
        self.assertEqual(compile_slots(slots,payload)['patch']['set']['budget_operator'],'lte')

    def test_budget_operator_permissions_distinguish_initial_default_from_followup(self):
        for message in ['100 dolar altında','Under 80 dollars','50 USD altı']:
            self.assertEqual(budget_operator_permission(message,True)['allowed'],['lt'])
        self.assertEqual(budget_operator_permission('at most 100 dollars',False)['allowed'],['lte'])
        self.assertEqual(budget_operator_permission('300 dolar bütçe',True)['allowed'],['lte'])
        self.assertEqual(budget_operator_permission('Bütçeyi 100 dolara çıkar',False)['allowed'],[])
        payload=self.payload(False)
        payload['user_message']='Bütçeyi 100 dolara çıkar'
        payload['current_intent']=c.merge_intent(c.new_intent(),{'set':{'budget':'50.00','budget_operator':'lt'}})['intent']
        proposal=compile_slots({**empty_slots(),'budget':'100.00'},payload)
        merged,errors=c.validate_extraction(proposal,payload['user_message'],payload['current_intent'],False)
        self.assertEqual(errors,[])
        self.assertEqual(merged['intent']['budget_operator'],'lt')

    def test_judge_detects_omitted_product_and_wrong_budget_comparator(self):
        from alfiq_b.evaluate import check_turn
        from alfiq_b.cases import CASES
        spec=next(case for case in CASES if case['id']=='P02-spa-pair')['steps'][0]
        slots={**empty_slots(),'budget':'300.00','budget_operator':'lte','purpose':'spa',
               'groups':[group_slots(category='Spa & Wellness',quantity=1,group_index=i) for i in range(2)]}
        with tempfile.TemporaryDirectory() as directory, patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            agent=make_agent(directory,mode='live',provider='ollama')
            body=agent.run_turn('judge-regression',spec['text'])
            self.assertTrue(check_turn(body,spec,agent)['passed'])
            altered=c.deepcopy(body)
            altered['intent']['budget_operator']='lt'
            result=check_turn(altered,spec,agent)
            self.assertIn('REQUEST_INTENT_MISMATCH:budget_operator',result['hard_constraint_errors'])
            altered=c.deepcopy(body)
            altered['intent']['groups']=altered['intent']['groups'][:1]
            result=check_turn(altered,spec,agent)
            self.assertIn('REQUEST_INTENT_MISMATCH:groups',result['hard_constraint_errors'])


if __name__ == '__main__':
    unittest.main()
