"""Read-only Mage MCP tools for exact request pricing and account discovery.

Generation stays on the existing idempotent REST submission path. This client
cannot call generate, upload, modify account settings, or invoke arbitrary tools.
"""
import json
import uuid
from urllib.request import Request
from urllib.error import HTTPError, URLError
from .errors import UserError

ENDPOINT='https://mcp.mage.space/mcp'


class MagePricing:
    def __init__(self, credential, opener):
        self.credential, self.opener = credential, opener
        self.session=None
        self.ready=False
        self.protocol='2025-03-26'

    def rpc(self, method, params, notification=False):
        if method not in {'initialize','notifications/initialized','tools/list','tools/call'} or method=='tools/call' and params.get('name') not in {'estimate_cost','get_account','get_model'}:
            raise UserError('Unsupported pricing operation')
        payload=dict(jsonrpc='2.0',method=method,params=params)
        identity=uuid.uuid4().hex
        if not notification:payload['id']=identity
        headers={'Authorization':'Bearer '+self.credential,'Content-Type':'application/json',
                 'Accept':'application/json, text/event-stream','MCP-Protocol-Version':self.protocol}
        if self.session:headers['Mcp-Session-Id']=self.session
        request=Request(ENDPOINT,data=json.dumps(payload).encode(),headers=headers,method='POST')
        try:
            with self.opener.open(request,timeout=25) as response:
                self.session=response.headers.get('Mcp-Session-Id') or self.session
                raw=response.read(2*1024*1024+1)
                content_type=response.headers.get('Content-Type','')
            if len(raw)>2*1024*1024:raise UserError('Mage pricing response exceeds the supported size')
            if notification:return {}
            if 'text/event-stream' in content_type:
                messages=[json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith('data:')]
                value=next((v for v in messages if v.get('id')==identity),None)
            else:value=json.loads(raw)
            if not isinstance(value,dict) or value.get('id')!=identity or 'error' in value or not isinstance(value.get('result'),dict):
                raise UserError('Mage pricing returned an unsupported response')
            return value['result']
        except HTTPError as error:
            code=error.code;error.close()
            raise UserError('Mage pricing connection failed (HTTP '+str(code)+'). No generation was submitted.') from None
        except (OSError,URLError,json.JSONDecodeError,UnicodeDecodeError):
            raise UserError('Mage pricing is unavailable. No generation was submitted.') from None

    def initialize(self):
        if self.ready:return
        result=self.rpc('initialize',dict(protocolVersion='2025-03-26',capabilities={},clientInfo=dict(name='Curator',version='0.5.0')))
        if result.get('protocolVersion') not in {'2025-03-26','2025-06-18'}:
            raise UserError('Mage pricing protocol needs an integration update')
        self.protocol=result['protocolVersion']
        self.rpc('notifications/initialized',{},notification=True)
        self.tools={t['name']:t for t in self.rpc('tools/list',{}).get('tools',[]) if isinstance(t,dict) and isinstance(t.get('name'),str)}
        self.ready=True

    def call(self,name,arguments):
        if name not in {'estimate_cost','get_account','get_model'}:raise UserError('Unsupported pricing tool')
        self.initialize()
        schema=self.tools.get(name,{}).get('inputSchema',{})
        required=set(schema.get('required',[]));properties=set(schema.get('properties',{}))
        if not schema or not required<=set(arguments) or not set(arguments)<=properties:
            raise UserError('Mage pricing tool schema changed; no generation submitted')
        result=self.rpc('tools/call',dict(name=name,arguments=arguments))
        if result.get('isError'):raise UserError('Mage could not price this exact request; no generation submitted')
        value=result.get('structuredContent')
        if not isinstance(value,dict):
            try:value=json.loads(next(c['text'] for c in result.get('content',[]) if c.get('type')=='text'))
            except (StopIteration,ValueError,KeyError):raise UserError('Mage pricing result format needs an integration update') from None
        if not isinstance(value,dict):raise UserError('Mage pricing returned an invalid result')
        return value

    def quote(self,body,architecture='mango'):
        result=self.call('estimate_cost',dict(architecture=architecture,config=body))
        # Current Mage responses wrap the exact price in an estimate receipt.
        if 'estimate' in result:
            estimate=result['estimate']
            if not isinstance(estimate,dict) or estimate.get('status')!='priced' or estimate.get('architecture')!=architecture or body.get('model_id') is not None and estimate.get('model_id')!=body['model_id']:
                raise UserError('Mage did not price this exact model and request; no generation submitted')
            price=estimate.get('gems')
        else:
            # Legacy explicitly named Gems fields; never generic currency/cost.
            price=result.get('estimated_gems',result.get('gems',result.get('total_gems')))
        if type(price) not in (int,float) or price<0 or not __import__('math').isfinite(price):
            raise UserError('Mage returned no usable request-specific Gems estimate')
        return dict(gems=price,body=body,**({'architecture':architecture} if architecture!='mango' else {}),basis='Mage estimate_cost for this exact request; estimate, not a provider-enforced cap')
