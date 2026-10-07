"""Narrow lexical permissions for model values, never catalog/test answers.

Unsupported wording is still handled by the model and controller. These hints
prevent fabricated defaults and provide known bilingual catalog search terms.
"""
import re
from decimal import Decimal,InvalidOperation


QUERY_ALIASES = [
    (r'bardak\s+set(?:i|leri)?|glasses','glasses'),
    (r'kahve\w*|coffee','coffee'),
    (r'çay\w*|tea','tea'),
    (r'şişe\w*|bottles?','bottle'),
    (r'sürahi\w*|pitchers?','pitcher'),
    (r'bardak\w*|bardağ\w*|cups?|kupa\w*|mugs?','cup'),
]


def positive_matches(pattern,message):
    for match in re.finditer(r'(?<!\w)(?:'+pattern+r')(?!\w)',message,re.I):
        before=message[max(0,match.start()-35):match.start()]
        after=message[match.end():match.end()+35]
        if re.search(r"(?:not|no|without|except|exclude|don't|never)\s+(?:the\s+)?$",before,re.I):continue
        if re.match(r'\s*(?:istemiyorum|olmasın|değil|hariç|alma)\b',after,re.I):continue
        yield match


def grounded_hints(payload):
    message=payload['user_message']
    first=payload['first_request']
    amounts=set()
    invalid_money=False
    number=r'([+-]?\d+(?:[.,]\d+)?)'
    money=r'(?:USD|dolar\w*|dollars?|EUR|euro\w*|TL|TRY|GBP|CAD|AUD|JPY|CHF|CNY|INR)'
    for pattern in [r'(?<![\w+-])'+number+r'\s*'+money+r'\b',
                    r'[$€₺£]\s*'+number,
                    r'\b(?:budget|bütçe(?:m|miz|n|niz|yi|mi|mizi|si|sini|ye|me|mize)?)\b\s*(?:is|of|:|=)?\s*'+number+r'(?![\d.,])\b(?!\s*(?:adet|tane|ürün\w*|products?|items?|units?|copies)\b)',
                    r'(?:under|below|less than)\s+'+number+r'\b',
                    r'(?<![\w+-])'+number+r'\s+(?:altında|altı)\b']:
        for match in re.finditer(pattern,message,re.I):
            value=Decimal(match.group(1).replace(',','.'))
            try:
                if value>=0 and value==value.quantize(Decimal('.01')):amounts.add(format(value,'.2f'))
                else:invalid_money=True
            except InvalidOperation:
                invalid_money=True
    currencies=[]
    for pattern,value in [(r'USD|dolar\w*|dollars?|\$','USD'),(r'EUR|euro\w*|€','EUR'),
                          (r'GBP|pounds?|sterlin|£','GBP'),(r'TRY|TL|lira|₺','TRY'),
                          (r'CAD','CAD'),(r'AUD','AUD'),(r'JPY|yen','JPY'),(r'CHF','CHF')]:
        symbol={'USD':'$','EUR':'€','GBP':'£','TRY':'₺'}.get(value)
        if (symbol and symbol in message) or re.search(r'(?<!\w)(?:'+pattern+r')(?!\w)',message,re.I):currencies.append(value)
    countries=[]
    names={'TR':r'Türkiye\w*|Turkey','US':r'United States|USA|Amerika\w*',
           'CA':r'Canada|Kanada\w*','GB':r'United Kingdom|Britain|İngiltere\w*',
           'DE':r'Germany|Almanya\w*','FR':r'France|Fransa\w*','NL':r'Netherlands|Hollanda\w*',
           'AE':r'United Arab Emirates|BAE','AU':r'Australia|Avustralya\w*',
           'JP':r'Japan|Japonya\w*','BR':r'Brazil|Brezilya\w*'}
    for code,pattern in names.items():
        if re.search(r'\b'+code+r'\b',message) or list(positive_matches(pattern,message)):countries.append(code)
    queries=[]
    for pattern,query in QUERY_ALIASES:
        if query=='cup' and 'glasses' in queries:continue
        if list(positive_matches(pattern,message)):queries.append(query)
    literal_ids=re.findall(r'\bALF-\d{4}\b',message,re.I)
    if literal_ids:queries=[] # A literal product ID does not need a keyword filter.
    explicit_gift=bool(list(positive_matches(r'hediye\w*|hediyelik\w*|gifts?|presents?',message)))
    gift=explicit_gift or bool(re.search(r'for my (?:mom|mother|dad|father|parents)|(?:annem|babam)\s+için',message,re.I))
    purpose=[]
    if len(queries)==1 and queries[0] in {'coffee','tea'}:purpose=queries[:]
    elif gift:purpose=['gift']
    elif list(positive_matches(r'spa|wellness|hamam|sauna',message)):purpose=['spa']
    turkish=bool(re.search(r'\b(?:öner\w*|istiyorum|ürün\w*|hediye\w*|bütçe\w*|gönder\w*|adet|tane|puan\w*|olsun|için)\b',message,re.I))
    english=bool(re.search(r'\b(?:looking|recommend|suggest|something|please|she|loves|what|my|for|want|under)\b',message,re.I))
    language='en' if first and english and not turkish else None
    explicit_language=re.search(r'Türkçe|in Turkish|İngilizce|in English',message,re.I)
    if explicit_language:language='en' if re.search(r'English|İngilizce',explicit_language.group(0),re.I) else 'tr'
    quantities=bool(re.search(r'\b(?:adet\w*|tane\w*|kişilik|kişiye|people|persons|units?|copies|quantity|aded\w*|two|three|four|five|ikiye|üçe|birer|ikişer|üçer)\b',message,re.I))
    ambiguous=bool(first and not amounts and not queries and not explicit_gift and re.search(
        r'\bsomething\b|güzel\s+bir\s+şey|bir\s+şey',message,re.I))
    sort=None
    if re.search(r'puan\w*.*güven|güven\w*.*puan|rating.*confidence|confidence.*rating',message,re.I):sort='rating_confidence'
    elif re.search(r'en ucuz|cheapest|lowest price',message,re.I):sort='price_asc'
    approval_request=bool(list(positive_matches(
        r'onaya\s+(?:gönder|gonder)(?:in|iniz|elim|ilsin)?|onay\s+iste(?:yin|yelim)?'
        r'|request(?:\s+(?:human|my))?\s+approval|submit(?:\s+(?:it|the\s+cart))?\s+for\s+approval',message)))
    # A previous approval request is not a command in the current message.
    # This only permits extracting a request for approval, never human consent.
    approval_context=bool(list(positive_matches(r'onay\w*|approv\w*',message)))
    if re.search(
            r'onaya\s+(?:gönderme\w*|gonderme\w*|yollama\w*)\b'
            r'|onay(?:a)?\s+(?:gönder|gonder|yolla|iste)\s+(?:istemiyorum|değil|hariç)\b'
            r"|(?:don't|do not|never)\s+(?:request|submit(?:\s+(?:it|the\s+cart))?\s+for)\s+approval\b",message,re.I):
        approval_context=False
    approval_request=approval_request and approval_context
    return {'budget_values':sorted(amounts),'currencies':currencies,'countries':countries,
            'shipping_requested':bool(re.search(r'gönder\w*|ship\w*|deliver\w*|\bsend\b',message,re.I)),
            'queries':queries,'product_ids':sorted(set(pid.upper() for pid in literal_ids)),
            'purpose_values':purpose,'language':language,
            'language_allowed':language or payload['current_intent']['response_language'],
            'quantity_requested':quantities,'needs_clarification':ambiguous or invalid_money,
            'invalid_money':invalid_money,'sort_by':sort,
            'approval_context_present':approval_context,
            'action':'request_approval' if approval_request else 'recommend' if list(positive_matches(r'closest|nearest|en yakın|alternatif\w*|alternatives?',message)) else None}


def apply_hints(schema,hints,first_request):
    # This modifies a newly generated provider grammar, never raw model values.
    from .ollama_intent_slots import optional
    general=schema['properties']
    if hints['action']:general['action']={'type':'string','enum':[hints['action']]}
    elif not hints['approval_context_present']:
        from . import core as c
        general['action']=optional({'type':'string','enum':[
            value for value in c.INTENT_FIELDS['action']['enum'] if value!='request_approval']})
    for field,values in [('budget',hints['budget_values']),('currency',hints['currencies']),('ship_to',hints['countries']),('purpose',hints['purpose_values'])]:
        general[field]=optional({'type':'string','enum':values}) if values else {'type':'null'}
    if first_request and hints['purpose_values']:
        general['purpose']={'type':'string','enum':hints['purpose_values']}
    if len(hints['currencies'])==1 and hints['currencies'][0]!='USD':
        general['currency']={'type':'string','enum':hints['currencies']}
    if len(hints['countries'])==1 and hints['shipping_requested']:
        general['ship_to']={'type':'string','enum':hints['countries']}
    language_schema={'type':'string','enum':[hints['language_allowed']]}
    general['response_language']=language_schema if hints['language'] else optional(language_schema)
    if hints['sort_by']:general['sort_by']={'type':'string','enum':[hints['sort_by']]}
    else:general['sort_by']=optional({'type':'string','enum':['price_asc']}) if first_request else {'type':'null'}
    if hints['needs_clarification']:
        general['clarification_questions']={'type':'array','minItems':1,'maxItems':5,'items':{'type':'string','minLength':1}}
    group_array=general['groups']
    if 'anyOf' in group_array:group_array=group_array['anyOf'][0]
    group=group_array['items']['properties']
    if len(hints['queries'])==1:
        group['query']={'type':'string','enum':hints['queries']}
        if first_request:general['groups']=group_array
    group['product_ids']=optional({'type':'array','minItems':1,'maxItems':40,'uniqueItems':True,
                                  'items':{'type':'string','enum':hints['product_ids']}}) if hints['product_ids'] else {'type':'null'}
    if not hints['quantity_requested']:
        group['quantity']=optional({'type':'integer','enum':[1]}) if first_request else {'type':'null'}
    return schema
