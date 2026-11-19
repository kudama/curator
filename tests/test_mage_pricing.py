import io
import json
import unittest
from curator.mage_mcp import MagePricing


class Response(io.BytesIO):
    headers={}


class Opener:
    def __init__(self):self.calls=[];self.price={'estimated_gems':42}
    def open(self,request,timeout):
        data=json.loads(request.data);self.calls.append((request.full_url,data))
        method=data['method']
        if method=='initialize':value={'protocolVersion':'2025-03-26','capabilities':{}}
        elif method=='notifications/initialized':return Response(b'')
        elif method=='tools/list':value={'tools':[dict(name='estimate_cost',inputSchema=dict(type='object',required=['architecture','config'],properties={'architecture':{},'config':{}}))]}
        else:value={'structuredContent':self.price}
        return Response(json.dumps(dict(jsonrpc='2.0',id=data['id'],result=value)).encode())


class PricingTests(unittest.TestCase):
    def test_exact_request_quote_is_read_only_and_uses_advertised_schema(self):
        opener=Opener();p=MagePricing('fixture-key',opener);body={'prompt':'Synthetic','model_id':'mango-v3','image':'data:image/png;base64,fixture'}
        result=p.quote(body);self.assertEqual(result['gems'],42);self.assertEqual(result['body'],body)
        call=opener.calls[-1][1];self.assertEqual(call['params'],{'name':'estimate_cost','arguments':{'architecture':'mango','config':body}})
        self.assertTrue(all(url=='https://mcp.mage.space/mcp' for url,_ in opener.calls))
        for name in ('generate','create_upload','set_budget'):
            with self.subTest(name=name),self.assertRaises(ValueError):p.call(name,{})
        with self.assertRaises(ValueError):p.rpc('tools/call',{'name':'generate','arguments':{}})

    def test_unrecognized_cost_cannot_enable_generation(self):
        for price in ({'cost':42},{'gems':True},{'estimated_gems':float('nan')},{'gems':-1}):
            opener=Opener();opener.price=price
            with self.subTest(price=price),self.assertRaises(ValueError):MagePricing('fixture-key',opener).quote({'prompt':'Synthetic'})

    def test_schema_change_blocks_without_submitting_any_tool(self):
        opener=Opener();p=MagePricing('fixture-key',opener);p.initialize();p.tools['estimate_cost']['inputSchema']['required'].append('unknown')
        with self.assertRaisesRegex(ValueError,'schema changed'):p.quote({'prompt':'Synthetic'})
        self.assertEqual(opener.calls[-1][1]['method'],'tools/list')

    def test_live_estimate_envelope_prices_only_the_selected_model(self):
        opener=Opener();opener.price={'estimate':{'architecture':'mango','model_id':'mango-v3','status':'priced','gems':135,'balance':1000,'enough_gems':True}}
        result=MagePricing('fixture-key',opener).quote({'prompt':'Synthetic','model_id':'mango-v3'})
        self.assertEqual(result['gems'],135);self.assertNotIn('balance',result)
        self.assertEqual(opener.calls[-1][1]['params']['name'],'estimate_cost')

    def test_invalid_nested_estimates_never_fall_back_to_another_price(self):
        valid={'architecture':'mango','model_id':'mango-v3','status':'priced','gems':135}
        invalid=[None,{},*[{**valid,**change} for change in ({'status':'unpriced'},{'architecture':'other'},{'model_id':'mango-v4'},{'gems':True},{'gems':-1},{'gems':float('nan')})]]
        for estimate in invalid:
            opener=Opener();opener.price={'estimate':estimate,'estimated_gems':1}
            with self.subTest(estimate=estimate),self.assertRaises(ValueError):MagePricing('fixture-key',opener).quote({'model_id':'mango-v3'})
