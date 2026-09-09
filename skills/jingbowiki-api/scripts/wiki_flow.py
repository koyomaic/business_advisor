#!/usr/bin/env python3
"""API-only Wiki upload readiness, search and streaming chat. Requires requests."""
import argparse,json,mimetypes,os,pathlib,sys,time
import requests

def emit(x):
    print(json.dumps(x,ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://10.200.3.235:18082/api/v1')
    sub=parser.add_subparsers(dest='command',required=True)
    upload=sub.add_parser('upload');upload.add_argument('--kb-id',required=True);upload.add_argument('--file',required=True);upload.add_argument('--wait-seconds',type=int,default=0)
    wait=sub.add_parser('wait');wait.add_argument('--kb-id',required=True);wait.add_argument('--knowledge-id',required=True);wait.add_argument('--wait-seconds',type=int,default=900)
    search=sub.add_parser('search');search.add_argument('--kb-id',required=True);search.add_argument('--query',required=True)
    ask=sub.add_parser('ask');ask.add_argument('--kb-id',required=True);ask.add_argument('--agent-id',required=True);ask.add_argument('--session-id');ask.add_argument('--query',required=True)
    a=parser.parse_args();base=a.base_url.rstrip('/');s=requests.Session()
    if os.environ.get('JINGBOWIKI_API_KEY'):s.headers['X-API-Key']=os.environ['JINGBOWIKI_API_KEY']
    elif os.environ.get('JINGBOWIKI_TOKEN'):s.headers['Authorization']='Bearer '+os.environ['JINGBOWIKI_TOKEN']
    else:
        email=os.environ.get('JINGBOWIKI_EMAIL');password=os.environ.get('JINGBOWIKI_PASSWORD')
        if not email or not password:raise RuntimeError('需要当前用户的 API Key、token，或登录凭据环境变量；不在脚本中保存凭据。')
        r=s.post(base+'/auth/login',json={'email':email,'password':password},timeout=(10,30));r.raise_for_status();d=r.json()
        if not d.get('success') or not d.get('token'):raise RuntimeError('登录未返回有效 token')
        s.headers['Authorization']='Bearer '+d['token']
    def api(method,path,**kw):
        r=s.request(method,base+path,timeout=(10,120),**kw);r.raise_for_status()
        d=r.json() if r.content else None
        if isinstance(d,dict) and d.get('success') is False:raise RuntimeError('业务接口返回失败，请核对参数和权限')
        return d
    kb=api('GET','/knowledge-bases/'+a.kb_id)['data'];strategy=kb.get('indexing_strategy',{})
    if not strategy.get('wiki_enabled') or any(strategy.get(k) for k in ['vector_enabled','keyword_enabled','graph_enabled']):
        raise RuntimeError('目标知识库不是纯 Wiki，请先按 pure-wiki.md 配置。')
    if a.command=='search':
        emit(api('GET','/knowledgebase/'+a.kb_id+'/wiki/search',params={'q':a.query,'limit':10}));return
    if a.command in ['upload','wait']:
        if a.command=='upload':
            file=pathlib.Path(a.file)
            created=True
            try:
                with file.open('rb') as f:
                    r=api('POST','/knowledge-bases/'+a.kb_id+'/knowledge/file',files={'file':(file.name,f,mimetypes.guess_type(file.name)[0] or 'application/octet-stream')},data={'enable_multimodel':'false','channel':'api'})
            except requests.HTTPError as e:
                if e.response.status_code!=409:raise
                r=e.response.json();existing=r.get('data') or {}
                if r.get('code')!='duplicate_file' or existing.get('knowledge_base_id')!=a.kb_id or not existing.get('id'):raise
                created=False
            kid=r['data']['id'];emit({'stage':'accepted' if created else 'existing','created':created,'knowledge_id':kid,'knowledge_base_id':a.kb_id})
            if a.wait_seconds<=0: # 默认不阻塞：受理即上传成功，解析在后台异步进行
                k=api('GET','/knowledge/'+kid)['data']
                emit({'stage':'uploaded','knowledge_id':kid,'parse_status':k.get('parse_status'),'enable_status':k.get('enable_status'),'message':'上传成功；解析后台异步进行，需要确认进度时用 wait 子命令，不要重复上传。'})
                return
        else:kid=a.knowledge_id
        deadline=time.monotonic()+a.wait_seconds;previous=None
        while time.monotonic()<deadline:
            k=api('GET','/knowledge/'+kid)['data']
            if k.get('knowledge_base_id')!=a.kb_id:raise RuntimeError('知识条目不属于指定知识库')
            stats=api('GET','/knowledgebase/'+a.kb_id+'/wiki/stats')
            state=(k['parse_status'],k['enable_status'],stats.get('pending_tasks'),stats.get('total_pages'))
            if state!=previous:emit({'stage':'processing','knowledge_id':kid,'parse_status':state[0],'enable_status':state[1],'pending_tasks':state[2],'wiki_pages':state[3]});previous=state
            if state[0] in ['failed','cancelled','deleting']:raise RuntimeError(k.get('error_message') or state[0])
            if state[0]=='completed' and state[1]=='enabled' and state[2]==0:
                pages=api('GET','/knowledgebase/'+a.kb_id+'/wiki/pages',params={'query':k.get('title') or k.get('file_name'),'page_size':100})
                if not any(p.get('status')=='published' and kid in (p.get('source_refs') or []) for p in pages.get('pages',[])):
                    raise RuntimeError('解析完成但未找到当前文件已发布的 Wiki 页面，请检查入库日志，不能报告可问答。')
                emit({'stage':'ready','knowledge_id':kid,'wiki_pages':state[3]});return
            time.sleep(5)
        raise TimeoutError('等待达到上限，后台可能仍在运行。使用 wait 子命令继续查看，不要重复上传。')
    # Avoid creating a conversation before Wiki processing has completed.
    stats=api('GET','/knowledgebase/'+a.kb_id+'/wiki/stats')
    if stats.get('pending_tasks',0):
        emit({'stage':'not_ready','message':'资料仍在处理中，请等待 Wiki 就绪后再提问。'});return
    if not stats.get('total_pages',0):
        emit({'stage':'empty','message':'知识库还没有可问答的 Wiki 页面，请先上传资料并等待处理完成。'});return
    # Streaming chat; persist session id to caller before submitting a question.
    agent=api('GET','/agents/'+a.agent_id)['data'];cfg=agent['config']
    if cfg.get('agent_mode')!='smart-reasoning' or cfg.get('agent_type')!='wiki-qa':raise RuntimeError('请选择 wiki-qa 智能体')
    sid=a.session_id
    if not sid:sid=api('POST','/sessions',json={'title':'Wiki资料问答'})['data']['id']
    emit({'stage':'session','session_id':sid})
    assistant_id=None;complete=False;errors=[]
    def consume(lines):
        nonlocal assistant_id,complete
        if not lines:return
        raw='\n'.join(lines)
        if raw=='[DONE]':return
        d=json.loads(raw)
        assistant_id=d.get('assistant_message_id') or assistant_id
        if d.get('response_type')=='complete':complete=True
        if d.get('response_type')=='error':errors.append(d.get('content') or d.get('data') or 'stream error')
    try:
        with s.post(base+'/agent-chat/'+sid,json={'query':a.query,'agent_id':a.agent_id,'knowledge_base_ids':[a.kb_id],'agent_enabled':True,'web_search_enabled':False,'disable_title':True,'channel':'api'},stream=True,timeout=(10,360)) as r:
            r.raise_for_status();r.encoding='utf-8';data=[]
            for line in r.iter_lines(decode_unicode=True):
                if not line:consume(data);data=[]
                elif line.startswith('data:'):data.append(line[5:].lstrip())
            consume(data)
    except requests.RequestException:
        # A dropped connection may have already submitted the query. Never auto-resubmit.
        emit({'stage':'recovering','session_id':sid})
    if not assistant_id:
        raise RuntimeError('未获得回答消息 ID；请读取该会话历史确认请求状态，不要自动重复发送问题。')
    deadline=time.monotonic()+300
    while time.monotonic()<deadline:
        history=api('GET','/messages/'+sid+'/load')['data']
        m=next((m for m in history if m.get('id')==assistant_id),None)
        if m and m.get('is_completed') and m.get('content','').strip():
            emit({'stage':'answered','session_id':sid,'message_id':assistant_id,'stream_complete':complete,'warnings':errors,'answer':m['content']});return
        time.sleep(3)
    raise TimeoutError('回答尚未完成；保留 session_id 查询历史，不要重复提问。')

if __name__=='__main__':
    try:main()
    except Exception as e:
        # Do not print credentials or entire server request/response objects.
        emit({'stage':'error','message':str(e)});sys.exit(1)
