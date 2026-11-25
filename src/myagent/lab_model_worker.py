"""Small local OpenAI-compatible model service authored for deployment experiments."""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def assistant_message(text, tools):
    """Decode the checkpoint's documented Qwen tool envelope into OpenAI fields."""
    allowed = {t['function']['name'] for t in tools}
    calls = []
    for index, body in enumerate(re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', text, re.S)):
        value = json.loads(body)
        if value.get('name') not in allowed or not isinstance(value.get('arguments'), dict):
            raise ValueError('模型生成了未提供的工具名或非对象参数')
        calls.append({'id': f'local_{time.time_ns()}_{index}', 'type': 'function',
                      'function': {'name': value['name'], 'arguments': json.dumps(value['arguments'], ensure_ascii=False)}})
    content = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.S).strip() if calls else text
    return {'role': 'assistant', 'content': content or None, **({'tool_calls': calls} if calls else {})}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--port', type=int, default=8871)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--evidence-dir')
    args = p.parse_args()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    # Local-only assets; no surprise downloads into C: caches.
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True).eval()
    if args.device == 'cuda':
        free, total = torch.cuda.mem_get_info()
        if free - model.get_memory_footprint() < total * .30:
            raise ValueError('GPU需要保留至少30%空闲，当前不足以加载此模型')
        model = model.to(device='cuda', dtype=torch.float16)
        torch.cuda.empty_cache()
    torch.set_num_threads(min(6, torch.get_num_threads()))
    lock = threading.Lock()

    def generate(prompt, count):
        inputs = tokenizer(prompt, return_tensors='pt').to(model.device)
        if inputs['input_ids'].shape[1] + count > 8192:
            raise ValueError('本教学服务单请求上下文上限8192 token，请缩短不相关材料')
        def sync():
            if args.device == 'cuda': torch.cuda.synchronize()
        if args.device == 'cuda':
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            free, total = torch.cuda.mem_get_info()
            if free < total * .30:
                raise ValueError('GPU空闲已低于30%，暂不推理')
        sync()
        start = time.perf_counter()
        with torch.inference_mode():
            import inspect
            options = {'logits_to_keep': 1} if 'logits_to_keep' in inspect.signature(model.forward).parameters else {}
            cache = None
            # Bounded prefill chunks avoid an 8k attention workspace consuming
            # almost all laptop VRAM; elapsed time includes every real chunk.
            for offset in range(0, inputs['input_ids'].shape[1], 256):
                end = min(offset + 256, inputs['input_ids'].shape[1])
                result = model(input_ids=inputs['input_ids'][:, offset:end],
                               attention_mask=inputs['attention_mask'][:, :end],
                               past_key_values=cache, use_cache=True, **options)
                cache = result.past_key_values
            sync()
            first = time.perf_counter()
            token = result.logits[:, -1:].argmax(-1)
            generated = [token.item()]
            for _ in range(count-1):
                if token.item() == tokenizer.eos_token_id:
                    break
                result = model(input_ids=token, past_key_values=cache, use_cache=True, **options)
                cache = result.past_key_values
                token = result.logits[:, -1:].argmax(-1)
                generated.append(token.item())
                if token.item() == tokenizer.eos_token_id:
                    break
        sync()
        end = time.perf_counter()
        n = inputs['input_ids'].shape[1]
        return tokenizer.decode(generated, skip_special_tokens=True), {
            'prompt_tokens': n, 'completion_tokens':len(generated),'total_tokens':n+len(generated)}, {
            'prefill_seconds':first-start,'decode_seconds':end-first,
            'prefill_tok_s':n/max(first-start,1e-9),
            'decode_tok_s':max(0,len(generated)-1)/max(end-first,1e-9),
            'device':args.device,'model_path':args.model,'torch':torch.__version__,
            'cuda_peak_allocated_bytes':torch.cuda.max_memory_allocated() if args.device=='cuda' else None,
            'threads':torch.get_num_threads(),'dtype':str(next(model.parameters()).dtype),
            'finish_reason':'stop' if generated[-1]==tokenizer.eos_token_id else 'length',
            'prefill_chunk_size':256,
            'notice':'单次同步墙钟测量；每次请求重新prefill，无跨请求prompt cache；小模型能力须实际测量'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def send(self,data,status=200):
            raw=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

        def do_GET(self):
            if self.path=='/v1/models':
                self.send({'object':'list','data':[{'id':'local-qwen','object':'model','owned_by':'local'}]})
            elif self.path=='/health':
                self.send({'ready':True,'model_path':args.model,'device':args.device,
                           'dtype':str(next(model.parameters()).dtype),'quantization':None,
                           'model_memory_bytes':model.get_memory_footprint(),'threads':torch.get_num_threads(),
                           'supports_tools':True,'context_window':8192,
                           'cuda_allocated_bytes':torch.cuda.memory_allocated() if args.device=='cuda' else None,
                           'cuda_reserved_bytes':torch.cuda.memory_reserved() if args.device=='cuda' else None})
            else:
                self.send({'error':'unknown route'},404)

        def do_POST(self):
            try:
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/shutdown':
                    self.send({'stopping':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
                if self.path!='/v1/chat/completions':
                    self.send({'error':'unknown route'},404);return
                messages=data.get('messages',[])
                tools=data.get('tools',[])
                for message in messages:
                    for call in message.get('tool_calls',[]):
                        function=call.get('function',call)
                        if isinstance(function.get('arguments'),str):
                            function['arguments']=json.loads(function['arguments'])
                # Base checkpoints may lack a chat template: use a documented plain-text fallback.
                prompt='\n'.join(str(m.get('content','')) for m in messages)
                if getattr(tokenizer,'chat_template',None):
                    prompt=tokenizer.apply_chat_template(messages,tools=tools or None,tokenize=False,add_generation_prompt=True)
                with lock:
                    if 'threads' in data:
                        if data['threads'] not in (1,3,6):
                            raise ValueError('threads must be 1, 3 or 6')
                        torch.set_num_threads(data['threads'])
                    limit=data.get('max_tokens') or data.get('max_completion_tokens') or (512 if tools else 128)
                    text,usage,timings=generate(prompt,min(512,max(1,int(limit))))
                message=assistant_message(text,tools)
                finish='tool_calls' if message.get('tool_calls') else timings['finish_reason']
                response={'id':'local-'+str(time.time_ns()),'object':'chat.completion','created':int(time.time()),
                           'model':'local-qwen','choices':[{'index':0,'message':message,
                                                         'finish_reason':finish}], 'usage':usage,'timings':timings,'raw_model_output':text}
                if args.evidence_dir:
                    directory=Path(args.evidence_dir);directory.mkdir(parents=True,exist_ok=True)
                    (directory/(response['id']+'.json')).write_text(json.dumps(
                        {'request':data,'response':response},ensure_ascii=False,indent=2),encoding='utf-8')
                if data.get('stream'):
                    delta={k:v for k,v in message.items() if k!='tool_calls'}
                    if message.get('tool_calls'):
                        delta['tool_calls']=[{'index':i,**call} for i,call in enumerate(message['tool_calls'])]
                    chunk={**response,'object':'chat.completion.chunk',
                           'choices':[{'index':0,'delta':delta,'finish_reason':None}]}
                    done={**response,'object':'chat.completion.chunk',
                          'choices':[{'index':0,'delta':{},'finish_reason':finish}]}
                    raw=('data: '+json.dumps(chunk)+'\n\ndata: '+json.dumps(done)+'\n\ndata: [DONE]\n\n').encode()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                else:
                    self.send(response)
            except Exception as exc:
                self.send({'error':str(exc)},500)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__':
    main()
