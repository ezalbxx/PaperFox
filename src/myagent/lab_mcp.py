"""Authored MCP JSON-RPC server/client for machine-learning classification evidence."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from .jobs import atomic_json
from .tools.base import ToolResult

SCHEMA={'type':'object','properties':{'y_true':{'type':'array','items':{'type':'integer'}},
         'y_pred':{'type':'array','items':{'type':'integer'}}},'required':['y_true','y_pred']}
TOOL={'name':'classification_metrics','description':'Compute measured accuracy and confusion counts from integer classification labels.',
      'inputSchema':SCHEMA}
PUBMED_TOOL = {'name': 'search_pubmed',
    'description': 'Search actual PubMed records via NCBI E-utilities; returns PMID, title, journal, year and URL. Results are candidates, not verified support for a claim.',
    'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 5}}, 'required': ['query']}}


def search_pubmed(args):
    """Our small ESearch -> ESummary client; original API replies travel with it."""
    query, limit = str(args['query']).strip(), int(args.get('limit', 3))
    if not query or not 1 <= limit <= 5:
        raise ValueError('检索词不能为空，limit为1—5')
    exchanges = []
    def retrieve(utility, params):
        url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/' + utility + '?' + urllib.parse.urlencode(
            {'db': 'pubmed', 'retmode': 'json', 'tool': 'wisdom_tree_lab_agent', **params})
        request = urllib.request.Request(url, headers={'User-Agent': 'WisdomTreeLab/1.0'})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode('utf-8')
            value = json.loads(raw)
            exchanges.append({'url': url, 'http_status': response.status, 'raw_response': raw})
        if 'error' in value:
            raise ValueError(str(value['error']))
        return value
    search = retrieve('esearch.fcgi', {'term': query, 'retmax': limit, 'sort': 'relevance'})['esearchresult']
    ids = search.get('idlist', [])
    records = []
    if ids:
        time.sleep(.36)  # Public NCBI endpoint permits three requests per second.
        summaries = retrieve('esummary.fcgi', {'id': ','.join(ids)})['result']
        for pmid in ids:
            item = summaries[pmid]
            records.append({'pmid': pmid, 'title': item.get('title', ''),
                'journal': item.get('fulljournalname', ''), 'publication_date': item.get('pubdate', ''),
                'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'})
    return {'query': query, 'total_found': int(search.get('count', 0)), 'records': records,
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'source_responses': exchanges,
        'notice': 'Real PubMed candidate records; relevance and claims require reading the papers. NCBI disclaimer: https://www.ncbi.nlm.nih.gov/About/disclaimer.html',
        'interface_reference': 'https://www.ncbi.nlm.nih.gov/books/NBK25499/'}


def rpc(message):
    method=message.get('method');params=message.get('params',{})
    if method=='initialize':
        return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},
                'serverInfo':{'name':'myagent-labstats','version':'1.0'}}
    if method=='tools/list':
        return {'tools':[TOOL, PUBMED_TOOL]}
    if method=='tools/call' and params.get('name')==PUBMED_TOOL['name']:
        return {'content':[{'type':'text','text':json.dumps(search_pubmed(params['arguments']), ensure_ascii=False)}], 'isError':False}
    if method=='tools/call' and params.get('name')==TOOL['name']:
        args=params['arguments'];actual,pred=args['y_true'],args['y_pred']
        if not actual or len(actual)!=len(pred):
            raise ValueError('分类标签必须非空且长度相同')
        labels=sorted(set(actual)|set(pred))
        matrix=[[sum(a==x and b==y for a,b in zip(actual,pred)) for y in labels] for x in labels]
        value={'n':len(actual),'correct':sum(a==b for a,b in zip(actual,pred)),
               'accuracy':sum(a==b for a,b in zip(actual,pred))/len(actual),'labels':labels,'confusion_matrix':matrix}
        return {'content':[{'type':'text','text':json.dumps(value)}],'isError':False}
    raise ValueError('未知MCP方法或工具')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def do_POST(self):
        message=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        log = getattr(self.server, 'events', None)
        if message.get('method')=='notifications/initialized':
            if log is not None:
                log.append({'request':message,'response':{'http_status':202}})
            self.send_response(202);self.send_header('Content-Length','0');self.end_headers();return
        try:
            result={'jsonrpc':'2.0','id':message['id'],'result':rpc(message)}
        except (ValueError,KeyError,OSError) as exc:
            result={'jsonrpc':'2.0','id':message.get('id'),'error':{'code':-32602,'message':str(exc)}}
        raw=json.dumps(result).encode();self.send_response(200)
        if log is not None:
            log.append({'request':message,'response':result})
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)


class LabMCP:
    name='mcp__labstats__classification_metrics'
    description='Our machine-learning MCP tool. Compute real accuracy/confusion counts through a local JSON-RPC MCP server. Saves initialize/tools-list/tools-call protocol evidence; does not run shell.'
    parameters=SCHEMA
    method_name='classification_metrics'

    def __init__(self,pipeline,task_id):
        self.project,self.task_id=pipeline.project,task_id

    def run(self,args,ctx):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        events=[]
        def exchange(method,params=None):
            msg={'jsonrpc':'2.0','method':method,'params':params or {}}
            if not method.startswith('notifications/'):
                msg['id']=len(events)+1
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/mcp',data=json.dumps(msg).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=5) as r:
                raw=r.read();reply=json.loads(raw) if raw else {'http_status':r.status}
            events.append({'request':msg,'response':reply})
            if 'error' in reply:
                raise ValueError(reply['error']['message'])
            return reply.get('result',{})
        try:
            exchange('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'myagent','version':'1.0'}})
            exchange('notifications/initialized')
            listed=exchange('tools/list')
            definition=next(t for t in listed['tools'] if t['name']==self.method_name)
            if definition['inputSchema']!=self.parameters:
                raise ValueError('MCP工具定义与本次模型接口不同')
            result=exchange('tools/call',{'name':self.method_name,'arguments':args})
        finally:
            server.shutdown();server.server_close()
            path=self.project.root/'outputs/mcp'/f'{uuid4().hex[:12]}.json'
            path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(path,{'transport':'HTTP JSON-RPC, single local request session','events':events})
        from .lab_project import task_generation
        receipt={'id':path.stem,'task_id':self.task_id,'adapter':'mcp','state':'completed','returncode':0,
                 'plan_generation':task_generation(self.project,self.task_id),'method':self.method_name,
                 'path':str(path.relative_to(self.project.root)),'output':result}
        self.project.data['receipts'].append(receipt);self.project.save()
        return ToolResult(output=json.dumps({'result':result,'artifact':receipt['path'],'receipt_id':receipt['id']},ensure_ascii=False))


class LabPubMed(LabMCP):
    """Our own client connects to our MCP server, without a DSH process."""
    name='mcp__labstats__search_pubmed'
    method_name='search_pubmed'
    description=PUBMED_TOOL['description']+' Uses our HTTP MCP client/server and saves original protocol evidence; no DSH runtime.'
    parameters=PUBMED_TOOL['inputSchema']
