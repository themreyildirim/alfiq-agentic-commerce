import tempfile
import unittest
from unittest.mock import MagicMock,patch
from jsonschema import ValidationError
from alfiq_b import core as c
from alfiq_b.agent import make_agent
from alfiq_b.ollama_grounding_hints import grounded_hints
from alfiq_b.ollama_intent_slots import compile_slots,empty_slots,group_slots,numeric_filter_permissions,normalize_product_query


def payload(message,first=True,intent=None):
    return {'user_message':message,'first_request':first,'current_intent':intent or c.new_intent(),
            'category_vocabulary':sorted(set(c.CATEGORY_ALIASES.values()))}


def response(body):
    result=MagicMock(status_code=200)
    result.json.return_value={'done':True,'done_reason':'stop','model':'qwen3:4b-instruct-2507-q4_K_M',
                              'message':{'content':c.canonical_json(body)},'prompt_eval_count':30,'eval_count':20}
    return result


class GroundedHintTests(unittest.TestCase):
    def test_country_answer_cannot_inherit_an_approval_action_from_history(self):
        intent=c.merge_intent(c.new_intent(),{'set':{'action':'request_approval',
                                                   'budget':'100.00','purpose':'gift'}})['intent']
        for text,country in [('Türkiye’ye gönder','TR'),('Send it to Canada','CA')]:
            data=payload(text,False,intent)
            self.assertFalse(grounded_hints(data)['approval_context_present'])
            with self.assertRaises(ValidationError):
                compile_slots({**empty_slots(),'ship_to':country,'action':'request_approval'},data)
            for action in [None,'update_cart']:
                compiled=compile_slots({**empty_slots(),'ship_to':country,'action':action},data)
                self.assertEqual(compiled['patch']['set']['ship_to'],country)
                self.assertNotEqual(compiled['patch']['set'].get('action'),'request_approval')
        self.assertEqual(grounded_hints(payload('Türkiye’ye gönder ve onaya gönder',False,intent))['action'],'request_approval')

    def test_negated_approval_context_cannot_permit_request_approval(self):
        for text in ['Türkiye’ye gönder; onay istemiyorum','Onaya gönderme',
                     'Onaya gönder istemiyorum',"Don't request approval",'Do not request approval',
                     'Onaya gönder; hayır, onaya gönderme']:
            data=payload(text)
            self.assertFalse(grounded_hints(data)['approval_context_present'],text)
            with self.assertRaises(ValidationError):
                compile_slots({**empty_slots(),'action':'request_approval'},data)

    def test_country_edit_invalidates_previous_approval_without_requesting_a_new_one(self):
        initial={**empty_slots(),'action':'request_approval','budget':'100.00','currency':'USD','ship_to':'TR',
                 'groups':[group_slots(product_ids=['ALF-0039'],quantity=1)]}
        shipping={**empty_slots(),'ship_to':'US'}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(initial),response({'candidate_index':0,'fact_index':0}),response(shipping)]
            agent=make_agent(directory,mode='live',provider='ollama')
            first=agent.run_turn('country-edit','ALF-0039 1 adet, 100 USD bütçe, TR gönderim; onaya gönder')
            self.assertEqual(first['cart']['state'],'awaiting_approval')
            updated=agent.run_turn('country-edit','US gönder')
            self.assertEqual(updated['status'],'ok')
            self.assertEqual(updated['cart']['state'],'draft')
            self.assertIsNone(updated['cart']['approval'])
            self.assertEqual(updated['intent']['ship_to'],'US')
            premature=agent.run_turn('country-edit','Onaylıyorum')
            self.assertEqual(premature['reason_code'],'APPROVAL_REQUIRED')
            pending=agent.run_turn('country-edit','Onaya gönder')
            confirmed=agent.run_turn('country-edit','Onaylıyorum')
            self.assertEqual(pending['cart']['state'],'awaiting_approval')
            self.assertEqual(confirmed['cart']['state'],'approved')
            self.assertEqual(post.call_count,3)
            schema=post.call_args_list[2].kwargs['json']['format']['properties']['action']
            self.assertNotIn('request_approval',schema['anyOf'][0]['enum'])

    def test_product_count_after_budget_phrase_is_not_a_money_amount(self):
        for text in ['Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner',
                     '300 USD bütçeyle 20 adet alacağım',
                     'My budget is 300 dollars for 2 products']:
            self.assertEqual(grounded_hints(payload(text))['budget_values'],['300.00'],text)
        for text in ['Bütçem 250', 'Bütçeyi 250 yap', 'Budget: 250', 'Budget of 250']:
            self.assertEqual(grounded_hints(payload(text))['budget_values'],['250.00'],text)
        for text in ['Bütçeyle 2 ürün öner', 'Budget 20 products']:
            self.assertEqual(grounded_hints(payload(text))['budget_values'],[],text)

    def test_embedded_approval_request_binds_action_but_is_not_consent(self):
        for text in ['ALF-0017’den 2 adet, 300 USD bütçe, TR gönderim; onaya gönder.',
                     'ALF-0039, please request approval', 'Submit the cart for approval']:
            self.assertEqual(grounded_hints(payload(text))['action'],'request_approval',text)
        for text in ['Onaylıyorum','Onaya gönderme','Onaya gönder istemiyorum',
                     "Don't request approval",'Do not request approval','Sepete ekle']:
            self.assertIsNone(grounded_hints(payload(text))['action'],text)
        data=payload('ALF-0017’den 2 adet, 300 USD bütçe, TR gönderim; onaya gönder.')
        slots={**empty_slots(),'budget':'300.00','currency':'USD','ship_to':'TR',
               'groups':[group_slots(product_ids=['ALF-0017'],quantity=2)]}
        for action in ['add_to_cart','recommend',None]:
            with self.assertRaises(ValidationError):compile_slots({**slots,'action':action},data)
        self.assertEqual(compile_slots({**slots,'action':'request_approval'},data)['patch']['set']['action'],'request_approval')

    def test_category_label_query_is_removed_and_audited_without_losing_category(self):
        message='Bir spa işletmesi için 300 dolar bütçeyle 2 ürün öner'
        slots={**empty_slots(),'action':'recommend','purpose':'spa','budget':'300.00',
               'groups':[group_slots(group_index=i,category='Spa & Wellness',quantity=1,query='spa') for i in range(2)]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('spa-label-hint',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['intent']['groups'],[{'category':'Spa & Wellness','quantity':1}]*2)
            self.assertEqual(turn['cart']['selected_ids'],['ALF-0013','ALF-0015'])
            self.assertEqual(turn['cart']['quote_snapshot']['net_total'],'207.00')
            records=[c.json.loads(line) for line in (c.REPORT_DIR/'ollama_intent_refs.jsonl').read_text(encoding='utf-8').splitlines()]
            record=next(row for row in reversed(records) if row['session_id']=='spa-label-hint')
            self.assertEqual(record['slots']['groups'][0]['query'],'spa')
            self.assertEqual([item['code'] for item in record['query_normalizations']],['CATEGORY_LABEL_QUERY_REMOVED']*2)

    def test_explicit_spa_keyword_search_and_compound_product_query_are_preserved(self):
        for query,text,category in [('spa','Spa ürünlerinde "spa" kelimesini ara','Spa & Wellness'),
                                    ('spa','Adında spa geçen ürünleri öner','Spa & Wellness'),
                                    ('spa','Search for spa in product names','Spa & Wellness'),
                                    ('spa bowl','Spa bowl öner','Spa & Wellness'),
                                    ('spa','Bir spa ürünü öner',None)]:
            self.assertEqual(normalize_product_query(query,text,category),(query,None))

    def test_embedded_request_approval_stock_drift_requires_reconfirmation(self):
        from alfiq_b.cases import CASES
        from alfiq_b.evaluate import apply_effect,check_turn,store_invariants
        case=next(row for row in CASES if row['id']=='M11-stock-drift')
        slots={**empty_slots(),'action':'request_approval','budget':'300.00','currency':'USD','ship_to':'TR',
               'groups':[group_slots(product_ids=['ALF-0017'],quantity=2)]}
        clock={'now':c.datetime.now(c.timezone.utc)}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(slots),response({'candidate_index':0,'fact_index':0})]
            root=c.Path(directory)
            agent=make_agent(root,mode='live',provider='ollama',clock=lambda:clock['now'])
            turns=[]
            for spec in case['steps']:
                agent=apply_effect(agent,spec.get('effect'),clock,root,'live',None)
                turn=agent.run_turn('stock-request-hint',spec['text'])
                self.assertTrue(check_turn(turn,spec,agent)['passed'])
                turns.append(turn)
            self.assertEqual([turn['cart']['state'] for turn in turns],['awaiting_approval','needs_reconfirmation','needs_reconfirmation','cancelled'])
            self.assertEqual(store_invariants(agent),[])
            self.assertEqual(post.call_count,2)
            self.assertEqual(post.call_args_list[0].kwargs['json']['format']['properties']['action'],{'type':'string','enum':['request_approval']})

    def test_absent_money_country_currency_cannot_be_invented(self):
        data=payload('Türk kahvesi seven birine hediye arıyorum, stokta olsun')
        hints=grounded_hints(data)
        self.assertEqual(hints['budget_values'],[])
        self.assertEqual(hints['currencies'],[])
        self.assertEqual(hints['countries'],[])
        valid={**empty_slots(),'purpose':'coffee','groups':[group_slots(query='coffee',quantity=1)]}
        self.assertNotIn('budget',compile_slots(valid,data)['patch']['set'])
        for field,value in [('budget','80.00'),('budget','0.00'),('currency','EUR'),('ship_to','TR')]:
            with self.assertRaises(ValidationError):compile_slots({**valid,field:value},data)

    def test_explicit_currency_amounts_and_symbols_are_preserved(self):
        for text,currency,amount in [('100 USD bütçe','USD','100.00'),('Bütçem 250 euro','EUR','250.00'),
                                      ('under $75','USD','75.00'),('€250 budget','EUR','250.00')]:
            hints=grounded_hints(payload(text))
            self.assertEqual(hints['currencies'],[currency])
            self.assertEqual(hints['budget_values'],[amount])
        data=payload('En ucuz bardağı öner; 100 USD bütçe, TR gönderim.')
        valid={**empty_slots(),'budget':'100.00','currency':'USD','ship_to':'TR',
               'sort_by':'price_asc','groups':[group_slots(query='cup',quantity=1)]}
        self.assertEqual(compile_slots(valid,data)['patch']['set']['currency'],'USD')
        with self.assertRaises(ValidationError):compile_slots({**valid,'currency':'EUR'},data)

    def test_bilingual_keywords_preserve_specific_type_and_exclusions(self):
        for text,query in [('Türk kahvesi seven birine hediye','coffee'),('En ucuz bardağı öner','cup'),
                           ('12 adet bakır bardak seti','glasses'),('Bakır şişe istiyorum','bottle'),
                           ('Under 100 dollars, she loves tea','tea')]:
            self.assertEqual(grounded_hints(payload(text))['queries'],[query])
        for text in ['kahve istemiyorum','not coffee','ALF-0039 ürününden 1 adet']:
            self.assertEqual(grounded_hints(payload(text))['queries'],[])
        data=payload('Türk kahvesi seven birine hediye')
        with self.assertRaises(ValidationError):
            compile_slots({**empty_slots(),'groups':[group_slots(query='türk kahvesi',quantity=1)]},data)

    def test_unmentioned_followup_values_inherit_without_restated_quantity(self):
        intent=c.merge_intent(c.new_intent(),{'set':{'budget':'100.00','response_language':'en','purpose':'gift',
                                                   'groups':[{'quantity':1,'query':'tea'}]}})['intent']
        data=payload("OK, what's the closest you have?",False,intent)
        proposal=compile_slots({**empty_slots(),'action':'recommend'},data)
        merged,errors=c.validate_extraction(proposal,data['user_message'],intent,False)
        self.assertEqual(errors,[])
        for field in ['budget','response_language','groups','purpose']:
            self.assertEqual(merged['intent'][field],intent[field])
        with self.assertRaises(ValidationError):
            compile_slots({**empty_slots(),'action':'recommend','groups':[group_slots(quantity=1)]},data)
        with self.assertRaises(ValidationError):compile_slots({**empty_slots(),'action':'recommend','response_language':'tr'},data)

    def test_english_vague_request_needs_a_question_without_fake_budget(self):
        message='Looking for something nice for my mom'
        hints=grounded_hints(payload(message))
        self.assertTrue(hints['needs_clarification'])
        self.assertEqual(hints['language'],'en')
        body={**empty_slots(),'response_language':'en','purpose':'gift',
              'clarification_questions':['What does she enjoy, and what is your budget?']}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.return_value=response(body)
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('vague-hint',message)
            self.assertEqual(turn['status'],'needs_clarification')
            self.assertEqual(turn['reason_code'],'AMBIGUOUS_REQUEST')
            self.assertEqual(turn['intent']['response_language'],'en')
            self.assertIsNone(turn['intent']['budget'])
            self.assertEqual(post.call_count,1)
        with self.assertRaises(ValidationError):compile_slots({**body,'clarification_questions':[]},payload(message))

    def test_unbudgeted_coffee_pipeline_stays_unbudgeted_and_uses_catalog_query(self):
        message='Türk kahvesi seven birine hediye arıyorum, stokta olsun'
        body={**empty_slots(),'purpose':'coffee','groups':[group_slots(query='coffee',quantity=1)]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(body),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('unbudgeted-coffee-hint',message)
            self.assertEqual(turn['status'],'ok')
            self.assertIsNone(turn['intent']['budget'])
            self.assertIsNone(turn['intent']['ship_to'])
            self.assertEqual(turn['intent']['groups'],[{'query':'coffee','quantity':1}])
            self.assertEqual(turn['intent']['currency'],'USD')
            self.assertEqual(turn['intent']['purpose'],'coffee')

    def test_plain_gift_stays_actionable_without_fake_budget(self):
        message='Bir hediye öner'
        self.assertFalse(grounded_hints(payload(message))['needs_clarification'])
        body={**empty_slots(),'purpose':'gift','groups':[group_slots(quantity=1)]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.side_effect=[response(body),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('plain-gift-hint',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['cart']['state'],'draft')
            self.assertIsNone(turn['intent']['budget'])
            self.assertIsNone(turn['intent']['ship_to'])

    def test_confidence_is_a_sort_order_not_an_invented_rating_filter(self):
        message='Puanına en çok güvenebileceğim ürünü öner'
        self.assertEqual(grounded_hints(payload(message))['sort_by'],'rating_confidence')
        self.assertFalse(numeric_filter_permissions(message)['min_rating'])
        body={**empty_slots(),'sort_by':'rating_confidence','groups':[group_slots(quantity=1)]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            factory.return_value.__enter__.return_value.post.side_effect=[response(body),response({'candidate_index':0,'fact_index':0})]
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('confidence-hint',message)
            self.assertEqual(turn['status'],'ok')
            self.assertEqual(turn['cart']['selected_ids'],['ALF-0001'])

    def test_immediate_checkout_cannot_be_downgraded_to_recommendation(self):
        for message in ['ALF-0039’dan 1 adet; 100 USD bütçe, TR gönderim; hemen işlemi bitir.',
                        'ALF-0017 ürününü seçtim, direkt siparişi tamamla',
                        'Please complete the order now']:
            with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
                agent=make_agent(directory,mode='live',provider='ollama')
                turn=agent.run_turn('immediate-hint',message)
                self.assertEqual(turn['status'],'rejected')
                self.assertEqual(turn['reason_code'],'APPROVAL_REQUIRED')
                self.assertIsNone(turn['cart'])
                factory.assert_not_called()

    def test_literal_product_id_cannot_be_substituted_in_request_slots(self):
        data=payload('ALF-0099 kodlu ürünü 100 dolara sepete ekle')
        slots={**empty_slots(),'groups':[group_slots(product_ids=['ALF-0039'],quantity=1)]}
        with self.assertRaises(ValidationError):compile_slots(slots,data)
        slots['groups'][0]['product_ids']=['ALF-0099']
        self.assertEqual(compile_slots(slots,data)['patch']['set']['groups'][0]['product_ids'],['ALF-0099'])

    def test_invalid_money_is_not_rounded_or_discarded_as_an_unbudgeted_request(self):
        for text in ['Bütçem -50 USD','Bütçem 100.009 USD','Bütçem 999999999999999999999999999999999 USD']:
            hints=grounded_hints(payload(text))
            self.assertTrue(hints['invalid_money'],text)
            self.assertTrue(hints['needs_clarification'],text)
            self.assertEqual(hints['budget_values'],[],text)
            with self.assertRaises(ValidationError):compile_slots(empty_slots(),payload(text))

    def test_shipping_followup_completes_unbudgeted_gift_approval_without_inventing_budget(self):
        initial={**empty_slots(),'purpose':'gift','groups':[group_slots(quantity=1)]}
        shipping={**empty_slots(),'ship_to':'TR'}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(initial),response({'candidate_index':0,'fact_index':0}),response(shipping)]
            agent=make_agent(directory,mode='live',provider='ollama')
            messages=['Bir hediye öner','Onaya gönder','Türkiye’ye gönder','Onaya gönder','Onaylıyorum']
            turns=[agent.run_turn('shipping-hint',message) for message in messages]
            self.assertEqual([turn['status'] for turn in turns],['ok','needs_clarification','ok','ok','ok'])
            self.assertEqual([turn['cart']['state'] for turn in turns],['draft','draft','draft','awaiting_approval','approved'])
            self.assertFalse(turns[2]['approval']['pending_token_exists'])
            self.assertEqual(turns[-1]['cart']['state'],'approved')
            self.assertEqual(turns[-1]['intent']['ship_to'],'TR')
            self.assertIsNone(turns[-1]['intent']['budget'])
            self.assertEqual(post.call_count,3)

    def test_english_followup_preserves_language_and_budget_across_no_match(self):
        vague={**empty_slots(),'purpose':'gift','response_language':'en',
               'clarification_questions':['What does she enjoy? What is your budget?']}
        tea={**empty_slots(),'budget':'100.00','budget_operator':'lt','purpose':'tea','clarification_questions':[],
             'groups':[group_slots(query='tea')]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.side_effect=[response(vague),response(tea),response({**empty_slots(),'action':'recommend'})]
            agent=make_agent(directory,mode='live',provider='ollama')
            messages=['Looking for something nice for my mom','Under 100 dollars, she loves tea',"OK, what's the closest you have?"]
            turns=[agent.run_turn('english-hint',message) for message in messages]
            self.assertEqual([turn['status'] for turn in turns],['needs_clarification','no_match','no_match'])
            self.assertEqual(turns[-1]['intent']['response_language'],'en')
            self.assertEqual(turns[-1]['intent']['budget'],'100.00')
            self.assertEqual(turns[-1]['intent']['budget_operator'],'lt')
            self.assertEqual(turns[-1]['intent']['groups'],[{'query':'tea','quantity':1}])
            self.assertEqual(turns[-1]['intent']['purpose'],'tea')
            self.assertEqual(post.call_count,3)

    def test_unbudgeted_out_of_stock_id_has_the_correct_rejection_reason(self):
        slots={**empty_slots(),'action':'add_to_cart',
               'groups':[group_slots(product_ids=['ALF-0022'],quantity=2)]}
        with tempfile.TemporaryDirectory() as directory,patch('alfiq_b.ollama_transport.requests.Session') as factory:
            post=factory.return_value.__enter__.return_value.post
            post.return_value=response(slots)
            turn=make_agent(directory,mode='live',provider='ollama').run_turn('stock-hint','ALF-0022’den 2 adet sepete ekle')
            self.assertEqual(turn['status'],'rejected')
            self.assertEqual(turn['reason_code'],'OUT_OF_STOCK')
            self.assertIsNone(turn['cart'])
            self.assertEqual(post.call_count,1)
