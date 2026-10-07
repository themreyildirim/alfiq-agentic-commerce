"""Persistent conversation -> constraints -> tools -> checkout -> turn JSON."""
from . import core as c
from .models import FixtureModel, build_live_adapter
import re
from threading import RLock

STATUSES = ['ok','no_match','needs_clarification','rejected']
TURN_RECOMMENDATION_SCHEMA = c.deepcopy(c.RECOMMENDATION_SCHEMA)
TURN_RECOMMENDATION_SCHEMA['properties']['matched_constraints'] = c.contract('matched-constraints', {
    'currency':c.TEXT,'stock_requirement':c.TEXT,'budget':c.nullable(c.MONEY),
    'budget_operator':{'enum':['lt','lte']},'cart_net_total':c.MONEY,'ship_to':c.nullable(c.TEXT),
    'groups':{'type':'array','minItems':1,'items':c.contract('matched-group', {
        'group_index':{'type':'integer','minimum':0},'constraints':c.GROUP_INPUT})},
})
TURN_RECOMMENDATION_SCHEMA['required'].append('matched_constraints')
TURN_SCHEMA = c.contract('agent-turn', {
    'schema_version':{'const':'agent-turn.v2'}, 'session_id':c.TEXT, 'turn':c.INTEGER,
    'timestamp':c.TEXT,'model':c.TEXT,'catalog_version':c.VERSION,
    'catalog_source':{'enum':['snapshot','live']},'policy_version':c.TEXT,
    'request':c.contract('turn-request',{'raw_text':c.TEXT,'response_language':{'enum':['tr','en']},
                                       'caller_type':{'enum':['human','agent']},'mandate_id':c.nullable(c.TEXT)}),
    'intent':c.INTENT_SCHEMA,'proposed_intent':c.nullable(c.INTENT_SCHEMA),
    'changed_fields':{'type':'array','items':c.TEXT},
    'requested_patch':c.nullable(c.INTENT_PATCH_SCHEMA),
    'change_applied':{'type':'boolean'},'assumptions':{'type':'array','items':c.TEXT},
    'status':{'enum':STATUSES},'reason_code':c.nullable(c.TEXT),'operation':c.TEXT,
    'questions':{'type':'array','items':c.TEXT},
    'recommendations':{'type':'array','maxItems':5,'items':TURN_RECOMMENDATION_SCHEMA},
    'closest_alternative':c.nullable(c.ALTERNATIVE_OUTPUT),
    'cart':c.nullable(c.CART_SCHEMA),'diff':c.DIFF_ARRAY,'simulated_order':c.nullable(c.ORDER_SCHEMA),
    'approval':c.contract('turn-approval',{'pending_token_exists':{'type':'boolean'},
                                         'source':c.nullable({'const':'human'}),'order_id':c.nullable(c.TEXT)}),
    'validation':c.contract('turn-validation',{
        'checks':{'type':'array','items':c.contract('turn-check',{'name':c.TEXT,'passed':{'type':'boolean'},'codes':{'type':'array','items':c.TEXT}})},
        'intent_repair_attempts':{'type':'integer','minimum':0,'maximum':2},
        'selection_repair_attempts':{'type':'integer','minimum':0,'maximum':2}}),
    'trace':c.contract('turn-trace',{
        'mode':{'enum':['offline_fixture','live']},'real_llm_verified':{'type':'boolean'},
        'tool_call_count':{'type':'integer','minimum':0},'context_unique_products':{'type':'integer','maximum':20},
        'tool_calls':{'type':'array','items':{'type':'object'}},'llm_calls':{'type':'array','items':{'type':'object'}},
        'api_attempts':{'type':'integer','minimum':0},
        'tokens':c.contract('turn-tokens',{name:c.nullable({'type':'integer','minimum':0}) for name in
                  ['input','output','thinking','cached','total']}),
        'latency_ms':{'type':'number','minimum':0},'cost_usd':{'type':'null'}}),
    'persistence':c.PERSISTENCE_SCHEMA,
})
TURN_SCHEMA['$id'] = 'urn:alfiq:schema:agent-turn:v2'
c.Draft202012Validator.check_schema(TURN_SCHEMA)
c.atomic_json_write(c.SCHEMA_DIR/'agent_turn.v2.json',TURN_SCHEMA)

# A single unconstrained recommendation is allowed without inventing a budget.
_budgeted_candidates = c.find_cart_candidates_core
def candidate_core(args,catalog,policy):
    if args['budget'] is not None:
        return _budgeted_candidates(args,catalog,policy)
    if len(args['groups']) != 1:
        return c.failure('INVALID_ARGUMENT',field='budget',reason='MULTI_PRODUCT_BUDGET_REQUIRED')
    group = c.deepcopy(args['groups'][0])
    wanted = group.pop('product_ids',None)
    subset = catalog
    if wanted:
        index = {p['id']:p for p in catalog['products']}
        missing = next((pid for pid in wanted if pid not in index),None)
        if missing:
            return c.failure('PRODUCT_NOT_FOUND',product_id=missing)
        subset = {**catalog,'products':[index[pid] for pid in wanted]}
    found = c.search_products_core({**group,'currency':args['currency'],'ship_to':args.get('ship_to'),
                                   'sort_by':args.get('sort_by','price_asc'),'page_size':10},subset,policy)
    if not found['ok']:
        return found
    products,candidates = [],[]
    for item in found['items']:
        pid = item['product']['id']
        quote = c.quote_cart_core([{'product_id':pid,'quantity':int(group['quantity'])}],catalog=catalog,policy=policy,
                                 currency=args['currency'],ship_to=args.get('ship_to'))
        if quote['ok']:
            products.append(item['product'])
            candidates.append({'candidate_id':'cand-'+pid,'group_product_ids':[pid],'quote':quote['quote']})
    return {'ok':True,'status':'ok' if candidates else 'no_match',
            'reason_code':None if candidates else 'NO_CANDIDATES_FOR_GROUP',
            'distinct_products':args.get('distinct_products',True),'group_candidate_counts':[found['total_matches']],
            'combinations_checked':len(found['items']),'valid_carts_found':len(candidates),'rejection_counts':{},
            'output_product_limit':10,'products':products,'candidates':candidates,'closest_alternative':None}
c.find_cart_candidates_core = candidate_core
c.TOOL_INPUTS['find_cart_candidates']['properties']['sort_by'] = {'enum':['price_asc','rating_confidence','id']}
c.ALL_TOOL_INPUTS['find_cart_candidates'] = c.TOOL_INPUTS['find_cart_candidates']
c.atomic_json_write(c.SCHEMA_DIR/'find_cart_candidates.input.v1.json',c.TOOL_INPUTS['find_cart_candidates'])

_preflight_without_category_totals = c.preflight_intent
def preflight_with_category_totals(intent,policy):
    decision = _preflight_without_category_totals(intent,policy)
    if decision['status']!='ok':
        return decision
    for limit in policy['category_limits']:
        quantity = sum(group['quantity'] for group in intent['groups'] if group.get('category')==limit['category'])
        if quantity>limit['max_units_per_order']:
            return {'status':'rejected','reason_code':'POLICY_VIOLATION','questions':[],
                    'details':{'rule':'category_limits','category':limit['category'],'requested':quantity,'allowed':limit['max_units_per_order']}}
    return decision
c.preflight_intent = preflight_with_category_totals

def human_command(message):
    return ' '.join(message.casefold().strip().split()).rstrip('.!')

class CommerceAgent:
    def __init__(self,tools,model,mode,root):
        if mode not in {'live','offline_fixture'}:
            raise ValueError('Unknown agent mode.')
        self.tools,self.model,self.mode = tools,model,mode
        self.root = c.Path(root)
        self.report_dir = self.root/'reports'
        self.report_dir.mkdir(parents=True,exist_ok=True)
        self.lock = RLock()
        with tools.store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agent_turns(session_id TEXT NOT NULL REFERENCES sessions(session_id), turn INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(session_id,turn))')
        tools.store.checkpoint()

    def active_cart(self,session):
        if not session['active_cart_id']:
            return None
        result = self.tools.store.read_cart(session['session_id'],session['active_cart_id'])
        return result.get('cart') if result['ok'] else None

    def save_intent(self,sid,intent,pending=False):
        with self.tools.store.transaction() as db:
            session = self.tools.store.session(db,sid)
            if pending:
                session['pending_intent'] = c.deepcopy(intent)
            else:
                session['intent'],session['pending_intent'] = c.deepcopy(intent),None
            self.tools.store.save_session(db,session)
        self.tools.store.checkpoint()

    def previous_turn(self,sid):
        with self.tools.store.connection() as db:
            row = db.execute('SELECT body FROM agent_turns WHERE session_id=? ORDER BY turn DESC LIMIT 1',(sid,)).fetchone()
        return c.json.loads(row[0]) if row else None

    def refresh_recommendations(self,cart,intent):
        if cart is None or cart['state'] in {'expired','needs_reconfirmation','cancelled'}:
            return []
        catalog,policy = self.tools.manager.snapshot()
        index = {p['id']:p for p in catalog['products']}
        lang = intent['response_language']
        preference = c.SOFT_REASONS[lang].get(intent['purpose'] or 'general',c.SOFT_REASONS[lang]['general'])
        output = []
        for pid in dict.fromkeys(cart['selected_ids']):
            if pid not in index:
                continue
            product = index[pid]
            menu = c.evidence_menu(product,policy,lang)
            fact = next(text for text,claim in menu.items() if claim['source']=='catalog_field' and claim['field']=='price')
            claims = [menu[fact],menu[preference]]
            output.append({**product,'reason':fact+'\n'+preference,'claims':claims,'unverifiable_points':[]})
        return output

    def run_turn(self,session_id,message,*,caller_type='human',idempotency_key=None):
        if not isinstance(session_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',session_id):
            raise ValueError('session_id must contain 1-120 letters, digits, underscores or hyphens.')
        if caller_type not in {'human','agent'}:
            raise ValueError('caller_type must be human or agent.')
        if not isinstance(message,str) or not message.strip():
            raise ValueError('A nonempty original user message is required.')
        with self.lock:
            return self._run_turn(session_id,message,caller_type,idempotency_key)

    def _run_turn(self,sid,message,caller_type,idempotency_key):
        started = c.time.perf_counter()
        tool_start,llm_start = len(self.tools.traces),len(self.model.traces)
        api_start = getattr(getattr(self.model,'client',None),'attempts',0)
        opened = self.tools.start_user_turn(sid,message)
        if not opened['ok']:
            raise ValueError('Could not open trusted session: '+c.canonical_json(opened))
        before = c.deepcopy(opened['session']['intent'])
        session = opened['session']
        cart = self.active_cart(session)
        before_cart = c.deepcopy(cart)
        extracted,selection,requested_patch = None,None,None
        checks = []
        if session['last_validation']:
            check = session['last_validation']
            checks.append({'name':'existing_cart_revalidation','passed':check['ok'],
                           'codes':[] if check['ok'] else [check['error']['code']]})
        command = human_command(message)

        def emit(status,reason=None,*,questions=None,recommendations=None,alternative=None,result=None,operation='none'):
            saved = self.tools.store.read_session(sid)['session']
            current_cart = self.active_cart(saved)
            catalog,policy = self.tools.manager.snapshot()
            tool_traces = c.deepcopy(self.tools.traces[tool_start:])
            llm_traces = c.deepcopy(self.model.traces[llm_start:])
            tokens = {}
            for label,key in {'input':'total_input_tokens','output':'total_output_tokens','thinking':'total_thought_tokens',
                              'cached':'total_cached_tokens','total':'total_tokens'}.items():
                values = [(row.get('usage') or {}).get(key) for row in llm_traces]
                tokens[label] = sum(values) if values and all(value is not None for value in values) else None
            local_checks = c.deepcopy(checks)
            if extracted:
                local_checks += [{'name':'intent_extraction_attempt_'+str(row['attempt']),
                                  'passed':row['passed'],'codes':row['codes']} for row in extracted.get('checks',[])]
            if selection:
                local_checks += [{'name':row['name'],'passed':row['passed'],'codes':row['codes']} for row in selection['validation']['checks']]
            if result:
                local_checks.append({'name':'checkout_operation','passed':result['ok'],
                                     'codes':[] if result['ok'] else [result['error']['code']]})
            body = {
                'schema_version':'agent-turn.v2','session_id':sid,'turn':saved['turn'],
                'timestamp':self.tools.store.timestamp(),'model':self.model.model,
                'catalog_version':catalog['catalog_version'],'catalog_source':'snapshot','policy_version':policy['policy_version'],
                'request':{'raw_text':message,'response_language':saved['intent']['response_language'],
                           'caller_type':caller_type,'mandate_id':None},
                'intent':saved['intent'],'proposed_intent':saved['pending_intent'],
                'changed_fields':c.changed_paths(before,saved['intent']),
                'requested_patch':requested_patch,'change_applied':before != saved['intent'] or before_cart != current_cart,
                'assumptions':saved['intent']['assumptions'],'status':status,'reason_code':reason,'operation':operation,
                'questions':questions or [],'recommendations':recommendations or [],'closest_alternative':alternative,
                'cart':current_cart,'diff':(result or {}).get('diff',[]),'simulated_order':(result or {}).get('order'),
                'approval':{'pending_token_exists':bool(current_cart and current_cart['state']=='awaiting_approval'),
                            'source':'human' if current_cart and current_cart.get('approval') else None,
                            'order_id':current_cart.get('order_id') if current_cart else None},
                'validation':{'checks':local_checks,
                              'intent_repair_attempts':max(0,len((extracted or {}).get('checks',[]))-1),
                              'selection_repair_attempts':selection['validation']['repair_attempts'] if selection else 0},
                'trace':{'mode':self.mode,'real_llm_verified':self.mode=='live' and status=='ok' and bool(llm_traces) and all(row.get('schema_valid') for row in llm_traces),
                         'tool_call_count':len(tool_traces),'context_unique_products':len(self.tools.context_ids),
                         'tool_calls':tool_traces,'llm_calls':llm_traces,
                         'api_attempts':getattr(getattr(self.model,'client',None),'attempts',0)-api_start,
                         'tokens':tokens,'latency_ms':round((c.time.perf_counter()-started)*1000,3),'cost_usd':None},
                'persistence':{'local_saved':True,'drive_backup_saved':None,'backup_error':None},
            }
            # Report the accepted constraints per product; these are hydrated
            # from persisted intent/quoted cart, never supplied by the LLM.
            for product in body['recommendations']:
                product['matched_constraints'] = {
                    'currency':saved['intent']['currency'],'stock_requirement':saved['intent']['stock_requirement'],
                    'budget':saved['intent']['budget'],'budget_operator':saved['intent']['budget_operator'],
                    'cart_net_total':current_cart['quote_snapshot']['net_total'],'ship_to':saved['intent']['ship_to'],
                    'groups':[{'group_index':index,'constraints':c.deepcopy(saved['intent']['groups'][index])}
                              for index,pid in enumerate(current_cart['selected_ids']) if pid==product['id']],
                }
            body = c.json.loads(c.canonical_json(body))
            c.Draft202012Validator(TURN_SCHEMA).validate(body)
            with self.tools.store.transaction() as db:
                db.execute('INSERT INTO agent_turns(session_id,turn,body) VALUES(?,?,?)',(sid,saved['turn'],c.canonical_json(body)))
            body['persistence'] = self.tools.store.checkpoint()
            c.Draft202012Validator(TURN_SCHEMA).validate(body)
            # Persist the completed persistence status, too.
            with self.tools.store.transaction() as db:
                db.execute('UPDATE agent_turns SET body=? WHERE session_id=? AND turn=?',(c.canonical_json(body),sid,saved['turn']))
            self.tools.store.checkpoint()
            c.atomic_json_write(self.report_dir/f'{sid}-turn-{saved["turn"]:03}.json',body)
            with (self.report_dir/'turns.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(c.canonical_json(body)+'\n')
            return body

        def finish_tool(result,operation):
            if result['ok']:
                state = result['cart']['state']
                return emit('ok',result=result,operation=operation,
                            recommendations=[] if state in {'cancelled','approved'} else self.refresh_recommendations(result['cart'],self.tools.store.read_session(sid)['session']['intent']))
            code = result['error']['code']
            if code=='BUDGET_EXCEEDED':
                saved = self.tools.store.read_session(sid)['session']
                target = saved['pending_intent'] or saved['intent']
                candidates = self.candidates(target)
                return emit('no_match',code,result=result,operation=operation,
                            alternative=candidates.get('closest_alternative') if candidates.get('ok') else None)
            if code in {'RECONFIRMATION_REQUIRED','QUOTE_EXPIRED','APPROVAL_PRECONDITION_FAILED','INTENT_NOT_READY'}:
                missing = result['error'].get('details',{}).get('missing',[])
                return emit('needs_clarification',code,result=result,operation=operation,
                            questions=['Onay için netleştirilmesi gereken alanlar: '+', '.join(missing)] if missing else [])
            return emit('rejected',code,result=result,operation=operation)

        if caller_type != 'human':
            return emit('rejected','AGENT_CALL_REQUIRES_LAYER_C')
        # Defense in depth, not a complete semantic injection detector.
        if c.DIRECTIVE_PATTERN.search(message) or re.search(r'\bADMIN\d+\b|override_price|(?:%\s*90|90\s*%)\s*(?:indirim|discount)',message,re.I):
            return emit('rejected','UNAUTHORIZED_OVERRIDE_REQUEST')
        if not c.explicit_human_approval(message) and re.search(
            r'\b(?:hemen|doğrudan|direkt)\s+(?:işlemi|siparişi|alışverişi)\s+(?:bitir|tamamla|onayla)\b'
            r'|\b(?:complete|finali[sz]e|place)\s+(?:the\s+)?(?:order|checkout)\s+(?:now|immediately|directly)\b',message,re.I):
            return emit('rejected','APPROVAL_REQUIRED')
        if c.explicit_human_approval(message):
            if session['pending_intent']:
                return emit('needs_clarification','PENDING_INTENT_UNRESOLVED',questions=['Bekleyen değişikliği önce düzeltelim veya açıkça geri alalım.'])
            if cart is None:
                return emit('rejected','APPROVAL_REQUIRED')
            if cart['state']=='expired':
                return emit('needs_clarification','QUOTE_EXPIRED')
            if cart['state']=='needs_reconfirmation':
                return emit('needs_clarification','RECONFIRMATION_REQUIRED')
            if cart['state'] not in {'awaiting_approval','approved'}:
                return emit('rejected','APPROVAL_REQUIRED')
            approval = cart.get('approval')
            if not approval:
                return emit('rejected','APPROVAL_REQUIRED')
            args = {'session_id':sid,'cart_id':cart['cart_id'],'expected_version':approval['cart_version'],
                    'approval_token':approval['token'],
                    'idempotency_key':idempotency_key or 'confirm-'+c.hashlib.sha256(approval['token'].encode()).hexdigest()[:24]}
            return finish_tool(self.tools.call('confirm_cart',args),'confirm_cart')
        if command in {'onaya gönder','onaya gonder','request approval','onay iste','yeniden onaya gönder','request approval again'}:
            if cart is None:
                return emit('rejected','CART_NOT_FOUND')
            if session['pending_intent']:
                return emit('needs_clarification','PENDING_INTENT_UNRESOLVED')
            args = {'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version']}
            return finish_tool(self.tools.call('request_approval',args),'request_approval')
        if command in {'iptal','sepeti iptal et','cancel cart','cancel'}:
            if cart is None:
                return emit('rejected','CART_NOT_FOUND')
            return finish_tool(self.tools.call('cancel_cart',{'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version']}),'cancel_cart')
        if cart and cart['state'] in {'approved','cancelled'}:
            return emit('rejected','INVALID_STATE_TRANSITION')
        if command in {'bekleyen değişikliği geri al','bekleyen degisikligi geri al','discard pending change'}:
            if session['pending_intent']:
                self.save_intent(sid,session['intent'])
            return emit('ok',operation='discard_pending_intent')

        base = session['pending_intent'] or session['intent']
        selected_override = None
        # These exact, bounded commands are code-parsed; other text goes to the LLM.
        quantity = re.fullmatch(r'(?:bunu\s+)?(\d+)\s*(?:adet|tane)(?:\s+(?:olsun|yap))?',command)
        budget = re.fullmatch(r'bütçeyi\s+(\d+(?:[.,]\d{1,2})?)\s*(?:usd|dolar|dolara)?\s*(?:yap|çıkar)?',command)
        remove = re.fullmatch(r'(ALF-\d{4})(?:\s+ürününü)?\s+(?:sepetten\s+)?(?:çıkar|kaldır)',message.strip().rstrip('.!'),re.I)
        add = re.fullmatch(r'(ALF-\d{4})(?:[\'’](?:dan|den))?\s+(\d+)\s+adet\s+(?:sepete\s+)?ekle',message.strip().rstrip('.!'),re.I)
        if command in {'bir tane daha ekle','bir adet daha ekle','add one more'} and len(base['groups'])==1:
            requested_patch = {'group_updates':[{'group_index':0,'set':{'quantity':base['groups'][0]['quantity']+1}}]}
        elif quantity and len(base['groups'])==1:
            requested_patch = {'group_updates':[{'group_index':0,'set':{'quantity':int(quantity.group(1))}}]}
        elif budget:
            requested_patch = {'set':{'budget':format(c.Decimal(budget.group(1).replace(',','.')),'.2f')}}
        elif remove and cart:
            pid = remove.group(1).upper()
            keep = [index for index,value in enumerate(cart['selected_ids']) if value!=pid]
            if len(keep)==len(cart['selected_ids']):
                return emit('rejected','PRODUCT_NOT_IN_CART')
            if not keep:
                return finish_tool(self.tools.call('cancel_cart',{'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version']}),'cancel_cart')
            requested_patch = {'set':{'groups':[c.deepcopy(session['intent']['groups'][index]) for index in keep]}}
            selected_override = [cart['selected_ids'][index] for index in keep]
            base = session['intent']
        elif add and cart:
            pid,qty = add.group(1).upper(),int(add.group(2))
            groups = c.deepcopy(base['groups'])
            if pid in cart['selected_ids']:
                index = cart['selected_ids'].index(pid)
                groups[index]['quantity'] += qty
                selected_override = list(cart['selected_ids'])
            else:
                groups.append({'product_ids':[pid],'quantity':qty})
                selected_override = list(cart['selected_ids'])+[pid]
            requested_patch = {'set':{'groups':groups,'action':'update_cart'}}
        else:
            previous = self.previous_turn(sid)
            first = previous is None or (cart is None and previous.get('reason_code') in {
                'LLM_RATE_LIMITED','LLM_TIMEOUT','LLM_MODEL_BUSY','LLM_TRANSPORT_ERROR','LLM_PROVIDER_ERROR'})
            extracted = c.extract_intent(message,current_intent=None if first else base,
                                         session_id=sid,turn=self.tools.turn_id,cart_state=cart['state'] if cart else None,
                                         tool_layer=self.tools,adapter=self.model)
            if extracted.get('literal_binding'):
                checks.append({'name':'explicit_product_bound_from_human_message','passed':True,'codes':[]})
            requested_patch = extracted.get('patch')
            if extracted['status'] != 'ok':
                if extracted['status']=='needs_clarification' and requested_patch is not None:
                    self.save_intent(sid,extracted['intent'],pending=cart is not None)
                return emit(extracted['status'],extracted['reason_code'],questions=extracted.get('questions',[]),operation='extract_intent')
        merged = c.merge_intent(base,requested_patch)
        if not merged['ok']:
            return emit('rejected','INVALID_ARGUMENT')
        proposed = merged['intent']
        ready = c.preflight_intent(proposed,self.tools.policy)
        checks.append({'name':'requested_intent_preflight','passed':ready['status']=='ok',
                       'codes':[] if ready['status']=='ok' else [ready['reason_code']]})
        if ready['status'] != 'ok':
            if ready['status']=='needs_clarification':
                self.save_intent(sid,proposed,pending=cart is not None)
            return emit(ready['status'],ready['reason_code'],questions=ready['questions'])
        # Action is a current-turn command. An earlier request for approval must
        # not silently request a new token after a later quantity/budget edit.
        action = requested_patch.get('set',{}).get('action','update_cart' if cart else proposed['action'])
        if action=='confirm_cart':
            return emit('rejected','APPROVAL_REQUIRED')
        if cart and cart['state'] not in {'draft','awaiting_approval'}:
            return emit('needs_clarification','RECONFIRMATION_REQUIRED' if cart['state']=='needs_reconfirmation' else 'QUOTE_EXPIRED')
        if cart and action=='cancel_cart':
            return finish_tool(self.tools.call('cancel_cart',{'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version']}),'cancel_cart')
        if cart and action=='request_approval' and merged['changed_fields'] in ([],['/action']):
            return finish_tool(self.tools.call('request_approval',{'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version']}),'request_approval')
        if cart:
            selected = selected_override or []
            if not selected:
                for index,group in enumerate(proposed['groups']):
                    wanted = group.get('product_ids')
                    if wanted and len(wanted)==1:
                        selected.append(wanted[0])
                    elif index<len(cart['selected_ids']):
                        selected.append(cart['selected_ids'][index])
                    else:
                        return emit('needs_clarification','GROUP_PRODUCT_SELECTION_REQUIRED')
            args = {'session_id':sid,'cart_id':cart['cart_id'],'expected_version':cart['version'],
                    'intent_patch':requested_patch,'use_pending_intent':bool(session['pending_intent']) and base is not session['intent'],
                    'selected_ids':selected,'expected_catalog_version':self.tools.catalog['catalog_version']}
            result = self.tools.call('update_cart',args)
            if result['ok'] and action=='request_approval':
                result = self.tools.call('request_approval',{'session_id':sid,'cart_id':result['cart']['cart_id'],'expected_version':result['cart']['version']})
                return finish_tool(result,'request_approval')
            return finish_tool(result,'update_cart')

        # No active cart: preserve clarified/no-match intent for follow-up turns.
        self.save_intent(sid,proposed)
        candidates = self.candidates(proposed)
        if not candidates['ok']:
            return emit('rejected',candidates['error']['code'],operation='find_cart_candidates')
        if candidates['status']=='no_match':
            return emit('no_match',candidates['reason_code'],alternative=candidates['closest_alternative'],operation='find_cart_candidates')
        def select(context,feedback):
            return self.model.generate_json(c.SELECTION_SCHEMA,{'context':context,'repair_feedback':feedback},
                                            c.SELECTION_SYSTEM,'product_selection',sid,self.tools.turn_id)
        selection = c.grounded_selection(select,candidates,proposed,self.tools)
        if selection['status']!='ok':
            code = selection['reason_code']
            if code=='GENERATION_FAILED' and self.model.traces and self.model.traces[-1].get('error_code'):
                code = self.model.traces[-1]['error_code']
            return emit(selection['status'],code,operation='product_selection')
        ids = {p['id'] for p in selection['recommendations']}
        # Unique recommendation IDs are hydrated by code; recover ordered groups
        # from the quoted, valid candidate instead of inventing an ordering.
        chosen = next(candidate for candidate in candidates['candidates']
                      if set(candidate['group_product_ids'])==ids and candidate['quote']==selection['quote'])
        result = self.tools.call('create_cart_draft',{'session_id':sid,'selected_ids':chosen['group_product_ids'],
                                                     'intent_patch':{},'expected_catalog_version':selection['catalog_version']})
        if not result['ok']:
            return finish_tool(result,'create_cart_draft')
        if action=='request_approval':
            result = self.tools.call('request_approval',{'session_id':sid,'cart_id':result['cart']['cart_id'],'expected_version':result['cart']['version']})
            if not result['ok']:
                return finish_tool(result,'request_approval')
        return emit('ok',recommendations=selection['recommendations'],result=result,operation='request_approval' if action=='request_approval' else 'create_cart_draft')

    def candidates(self,intent):
        wanted = [group.get('product_ids') for group in intent['groups']]
        if all(ids and len(ids)==1 for ids in wanted):
            catalog,policy = self.tools.manager.snapshot()
            checked = c.validate_selection_against_intent(intent,[ids[0] for ids in wanted],catalog,policy)
            if not checked['ok'] and checked['error']['code'] not in {'BUDGET_EXCEEDED','CONSTRAINT_VIOLATION'}:
                # Emit a typed tool result through quote_cart, not an unlogged shortcut.
                return self.tools.call('quote_cart',{
                    'lines':[{'product_id':ids[0],'quantity':int(group['quantity'])} for ids,group in zip(wanted,intent['groups'])],
                    'budget':intent['budget'],'budget_operator':intent['budget_operator'],'currency':intent['currency'],'ship_to':intent['ship_to']})
        return self.tools.call('find_cart_candidates',{
            'groups':intent['groups'],'budget':intent['budget'],'budget_operator':intent['budget_operator'],
            'currency':intent['currency'],'ship_to':intent['ship_to'],'distinct_products':intent['distinct_products'],
            'sort_by':intent['sort_by']})

def make_agent(root,*,mode='offline_fixture',api_key=None,clock=None,backup_root=None,
               catalog_path=None,policy_path=None,provider='gemini',llm_options=None):
    root = c.Path(root)
    backup = c.Path(backup_root) if backup_root is not None else root/'backup'
    manager = c.CatalogManager(catalog_path or c.CATALOG_PATH,policy_path or c.POLICY_PATH,
                              root/'state'/'catalog_state.json',backup/'catalog_state.json')
    store = c.StatefulCheckoutStore(root/'state'/'commerce.sqlite3',backup/'commerce.sqlite3',clock=clock)
    model = FixtureModel() if mode=='offline_fixture' else build_live_adapter(provider,api_key,llm_options)
    agent = CommerceAgent(c.AgentTools(manager,store),model,mode,root)
    agent.provider,agent.llm_options = provider,c.deepcopy(llm_options)
    return agent
