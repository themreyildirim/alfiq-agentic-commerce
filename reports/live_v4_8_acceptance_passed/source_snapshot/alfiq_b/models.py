"""Offline fixtures and a bounded, direct Gemini REST transport."""
from . import core as c
from types import SimpleNamespace
from contextlib import contextmanager
import requests
import signal
import threading
from urllib.parse import quote

class RESTError(Exception):
    def __init__(self, status, message):
        self.status_code = status
        self.message = message
        super().__init__(message)

class _Deadline(BaseException):
    pass

@contextmanager
def request_deadline(seconds, provider_label='LLM'):
    enabled = hasattr(signal, 'setitimer') and threading.current_thread() is threading.main_thread()
    if not enabled:
        yield
        return
    if signal.getitimer(signal.ITIMER_REAL) != (0.0,0.0):
        raise RuntimeError('Another deadline is active; request not sent.')
    previous = signal.getsignal(signal.SIGALRM)
    def abort(signum, frame):
        raise _Deadline()
    signal.signal(signal.SIGALRM, abort)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        except _Deadline:
            raise TimeoutError(provider_label + ' REST request deadline exceeded.') from None
    finally:
        signal.setitimer(signal.ITIMER_REAL,0.0)
        signal.signal(signal.SIGALRM,previous)

class GeminiRESTClient:
    def __init__(self,key):
        if not isinstance(key,str) or not key.strip():
            raise ValueError('API key is empty.')
        self._key = key.strip()
        self.interactions = self
        self.attempts = 0

    def create(self, *, model, input, system_instruction, store,
               generation_config, response_format, timeout=60.0):
        if store is not False or response_format.get('mime_type') != 'application/json':
            raise ValueError('Only stateless JSON requests are supported.')
        payload = {
            'systemInstruction':{'parts':[{'text':system_instruction}]},
            'contents':[{'role':'user','parts':[{'text':input}]}],
            'generationConfig':{
                'responseMimeType':'application/json',
                'responseJsonSchema':response_format['schema'],
                'maxOutputTokens':generation_config['max_output_tokens'],
                'thinkingConfig':{'thinkingLevel':generation_config['thinking_level']},
            },
        }
        self.attempts += 1
        try:
            with request_deadline(timeout+5,'Gemini'), requests.Session() as session:
                response = session.post(
                    'https://generativelanguage.googleapis.com/v1beta/models/' + quote(model,safe='') + ':generateContent',
                    headers={'x-goog-api-key':self._key},json=payload,
                    timeout=(5,timeout),allow_redirects=False,
                )
                try:
                    body = response.json()
                except ValueError:
                    raise RESTError(response.status_code if response.status_code != 200 else 502,
                                    'Provider response was not JSON.') from None
                if response.status_code != 200:
                    raise RESTError(response.status_code, str((body.get('error') or {}).get('message','Provider error')))
        except requests.Timeout:
            raise TimeoutError('Gemini REST connection/read timeout.') from None
        candidates = body.get('candidates') or []
        candidate = candidates[0] if candidates else {}
        text = ''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought',False))
        usage = body.get('usageMetadata') or {}
        fields = {'total_input_tokens':'promptTokenCount','total_output_tokens':'candidatesTokenCount',
                  'total_thought_tokens':'thoughtsTokenCount','total_cached_tokens':'cachedContentTokenCount',
                  'total_tokens':'totalTokenCount'}
        return SimpleNamespace(status='completed' if candidate.get('finishReason')=='STOP' else 'incomplete',
                               output_text=text,model=body.get('modelVersion'),
                               usage={k:usage.get(v) for k,v in fields.items()})

def gemini_adapter(key, model='gemini-3.8-flash'):
    # Construction does not make an API request.
    return c.GeminiJSONAdapter(GeminiRESTClient(key),model=model,redactions=(key,key.strip()))

class FixtureModel:
    """Explicit test doubles. These do not measure LLM interpretation or ranking."""
    model = 'offline-fixture'
    def __init__(self):
        self.traces = []
        self.last_error = None
        self.patch = None
        self.preferred_ids = None
        self.fault = None

    def set_fixture(self, patch, preferred_ids=None, fault=None):
        self.patch = c.deepcopy(patch)
        self.preferred_ids = preferred_ids
        self.fault = fault

    def generate_json(self,schema,payload,system,stage,session_id=None,turn=None):
        started = c.time.perf_counter()
        if stage == 'intent_extraction':
            if self.patch is None:
                raise RuntimeError('No fixture patch has been configured; offline mode cannot interpret free text.')
            proposal = {'schema_version':'intent-extraction-wire.v1',
                        'patch_json':c.canonical_json(self.patch),
                        'evidence':[{'path':path,'quote':payload['user_message']} for path in sorted(c.extraction_paths(self.patch))]}
        elif stage == 'product_selection':
            context = payload['context']
            ids = (self.preferred_ids if self.preferred_ids in context['candidate_selections']
                   else context['candidate_selections'][0])
            lang = context['intent']['response_language']
            purpose = context['intent']['purpose'] or 'general'
            preference = c.SOFT_REASONS[lang].get(purpose,c.SOFT_REASONS[lang]['general'])
            reasons = []
            for pid in dict.fromkeys(ids):
                menu = context['evidence_sentences'][pid]
                fact = next(line for line in menu if line.startswith(('Katalog fiyatı:', 'Katalog başlangıç fiyatı:',
                                                                    'Catalog price:', 'Catalog starting price:')))
                text = fact + '\n' + preference
                if self.fault == 'wrong_price':
                    text = 'Katalog fiyatı: 1.00 USD.\n' + preference
                reasons.append({'product_id':pid,'text':text})
            proposal = {'schema_version':'selection.v1','selected_ids':ids,'reasons':reasons}
        else:
            raise RuntimeError('Unknown fixture stage: '+stage)
        if self.fault == 'invalid_intent' and stage == 'intent_extraction':
            proposal['patch_json'] = '{"set":{"price":"1.00"}}'
        self.traces.append({'timestamp':c.datetime.now(c.timezone.utc).isoformat(),
                           'stage':stage,'session_id':session_id,'turn':turn,
                           'model_requested':self.model,'model_returned':self.model,
                           'schema_valid':not list(c.Draft202012Validator(schema).iter_errors(proposal)),
                           'error_code':None,'usage':None,'real_api_call':False,
                           'latency_ms':round((c.time.perf_counter()-started)*1000,3)})
        return c.deepcopy(proposal)


def live_configuration(provider='gemini', options=None):
    from .ollama_transport import OllamaRESTClient, OLLAMA_MODEL
    options = dict(options or {})
    if provider == 'gemini':
        if set(options) - {'model'}:
            raise ValueError('Unsupported Gemini option')
        return {'provider':provider,'model':options.get('model','gemini-3.8-flash')}
    if provider != 'ollama':
        raise ValueError('Unknown LLM provider')
    allowed = {'model','base_url','num_ctx','max_output_tokens','timeout'}
    if set(options) - allowed:
        raise ValueError('Unsupported Ollama option')
    client = OllamaRESTClient(**{k:v for k,v in options.items() if k != 'model'})
    model = options.get('model',OLLAMA_MODEL)
    if not isinstance(model,str) or not model.strip():
        raise ValueError('Empty model name')
    return {'provider':provider,'model':model,'adapter_revision':'ollama-refs.4.8',**client.configuration}


def build_live_adapter(provider='gemini', api_key=None, options=None):
    config = live_configuration(provider,options)
    if provider == 'gemini':
        return gemini_adapter(api_key,model=config['model'])
    from .ollama_transport import OllamaRESTClient
    from .ollama_adapter import OllamaJSONAdapter
    client = OllamaRESTClient(**{k:v for k,v in config.items() if k not in {'provider','model','adapter_revision'}})
    adapter = OllamaJSONAdapter(client,model=config['model'])
    adapter.adapter_revision = config['adapter_revision']
    adapter.wire_schema = c.deepcopy
    adapter.request_timeout = client.timeout
    return adapter
