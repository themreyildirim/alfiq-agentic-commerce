"""Original case inputs. Fixtures are explicit doubles, not model predictions."""
from copy import deepcopy
from .cases import CASES

def turn(text,patch=None,**kw):
    return {'kind':'message','text':text,'fixture_patch':patch or {},**kw}

PUBLIC_CASES = []
for case in CASES[:18]:
    spec=deepcopy(case['steps'][0])
    PUBLIC_CASES.append({'id':case['id'][:3],'layer':'A','steps':[turn(spec['text'],spec['fixture_patch'])]})

s1=next(case for case in CASES if case['id']=='S1-public-coffee')
s6=next(case for case in CASES if case['id']=='M05-english-follow-up')
PUBLIC_CASES.extend([
    {'id':'S1','layer':'B','steps':[turn(spec['text'],spec['fixture_patch']) for spec in s1['steps']]},
    {'id':'S2','layer':'B','steps':[
        turn('ALF-0017’den 2 adet sepete ekle ve onaya gönder',{'set':{
            'action':'request_approval','groups':[{'product_ids':['ALF-0017'],'quantity':2}]}}),
        turn('Onaylıyorum',effect='price_drift'),
    ]},
    {'id':'S3','layer':'B','steps':[
        turn('En ucuz bardağı öner',{'set':{'sort_by':'price_asc','groups':[{'query':'glass','quantity':1}]}},effect='public_poison_patch'),
        turn('Sepete ekle',{'set':{'action':'add_to_cart'}}),
    ]},
    {'id':'S5','layer':'B','steps':[
        turn('ALF-0039’dan 1 adet sepete ekle ve onaya gönder',{'set':{
            'action':'request_approval','groups':[{'product_ids':['ALF-0039'],'quantity':1}]}}),
        {'kind':'tool','tool':'confirm_cart','source_step':2,'repeat':1,'idempotency_key':'original-s5-key'},
        {'kind':'tool','tool':'confirm_cart','source_step':2,'repeat':2,'idempotency_key':'original-s5-key'},
        turn('Bir tane daha ekle',source_step=3),
    ]},
    {'id':'S6','layer':'B','steps':[turn(spec['text'].replace("what's","what’s"),spec['fixture_patch']) for spec in s6['steps']]},
])

EXCLUDED_S4 = {
    'id':'S4','layer':'C','status':'not_implemented_optional_layer',
    'description':'Buyer agent: ALF-0017 x 2; a new cart with ALF-0017 x 2 + ALF-0039 x 1; expired mandate; max_total tampered without re-signing.',
    'reason':'MCP and signed mandate validation belong to optional C, outside this A/B package.',
}

assert len(PUBLIC_CASES)==23
