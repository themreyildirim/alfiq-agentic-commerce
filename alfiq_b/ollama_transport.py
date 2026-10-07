"""Local, non-streaming Ollama JSON transport; no model downloads or cloud fallback."""
from types import SimpleNamespace
from urllib.parse import urlsplit
import json
import requests
from .models import RESTError, request_deadline

OLLAMA_MODEL = 'qwen3:4b-instruct-2507-q4_K_M'


class OllamaRESTClient:
    provider_label = 'Ollama'
    max_attempts = 1

    def __init__(self, base_url='http://127.0.0.1:11434', num_ctx=4096,
                 max_output_tokens=1024, timeout=120.0):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'localhost','127.0.0.1','::1'}
                or parsed.username or parsed.password or parsed.path not in {'','/'}
                or parsed.query or parsed.fragment):
            raise ValueError('Ollama requires a local HTTP endpoint with no credentials or path')
        if (type(num_ctx) is not int or not 2048 <= num_ctx <= 32768
                or type(max_output_tokens) is not int or not 64 <= max_output_tokens < num_ctx):
            raise ValueError('Invalid context or output token limit')
        if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 5 <= timeout <= 300:
            raise ValueError('Timeout must be between 5 and 300 seconds')
        self.base_url = base_url.rstrip('/')
        self.num_ctx, self.max_output_tokens, self.timeout = num_ctx,max_output_tokens,float(timeout)
        self.interactions = self
        self.attempts = 0
        self.configuration = {'base_url':self.base_url,'num_ctx':num_ctx,
                              'max_output_tokens':max_output_tokens,'timeout':self.timeout}

    def create(self, *, model, input, system_instruction, store,
               generation_config, response_format, timeout=None):
        if store is not False or response_format.get('mime_type') != 'application/json':
            raise ValueError('Only stateless JSON requests are supported')
        limit = self.timeout if timeout is None else min(float(timeout),self.timeout)
        payload = {
            'model':model,
            'messages':[{'role':'system','content':system_instruction + '\nReturn JSON matching this schema:\n'
                         + json.dumps(response_format['schema'],ensure_ascii=False)},
                        {'role':'user','content':input}],
            'stream':False, 'format':response_format['schema'], 'keep_alive':'5m',
            'options':{'num_ctx':self.num_ctx,'num_predict':self.max_output_tokens,
                       'temperature':0,'seed':42},
        }
        self.attempts += 1
        try:
            with request_deadline(limit + 5,'Ollama'), requests.Session() as session:
                session.trust_env = False
                response = session.post(self.base_url + '/api/chat',json=payload,
                                        timeout=(5,limit),allow_redirects=False)
                try:
                    body = response.json()
                except ValueError:
                    raise RESTError(response.status_code if response.status_code != 200 else 502,
                                    'Ollama response was not JSON') from None
                if not isinstance(body,dict):
                    raise RESTError(502,'Ollama response was not an object')
                if response.status_code != 200 or body.get('error'):
                    error = body.get('error') or 'Ollama request failed'
                    raise RESTError(response.status_code if response.status_code != 200 else 502,str(error))
        except requests.Timeout:
            raise TimeoutError('Ollama connection/read timeout; request will not be retried automatically') from None
        message = body.get('message')
        if not isinstance(message,dict) or not isinstance(message.get('content'),str):
            raise RESTError(502,'Ollama response had no text message')
        # Do not strip fences, fabricate STOP, or accept output truncated by num_predict.
        completed = body.get('done') is True and body.get('done_reason') == 'stop'
        counts = {}
        for key in ['prompt_eval_count','eval_count','prompt_eval_cached_count']:
            value = body.get(key)
            counts[key] = value if type(value) is int and value >= 0 else None
        incoming,outgoing = counts['prompt_eval_count'],counts['eval_count']
        total = incoming + outgoing if incoming is not None and outgoing is not None else None
        return SimpleNamespace(status='completed' if completed else 'incomplete',
                               output_text=message['content'],model=body.get('model'),
                               usage={'total_input_tokens':incoming,'total_output_tokens':outgoing,
                                      'total_thought_tokens':None,
                                      'total_cached_tokens':counts['prompt_eval_cached_count'],
                                      'total_tokens':total})
