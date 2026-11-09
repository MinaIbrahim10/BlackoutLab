"""Authenticated notebook UI transport; no public port or general-purpose proxy."""
import html
import json
import re
import secrets
from importlib.resources import files

import httpx
from .api import RunRequest

READ_PATH = re.compile(r'/api/(?:config|scenarios|runs(?:/[a-f0-9]{32}(?:/(?:state|report|events(?:\?after=[0-9]+)?))?)?)')


class NotebookBridge:
    def __init__(self, port=8081):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid local lab port')
        self.base = f'http://127.0.0.1:{port}'

    def request(self, path, options=None):
        if not isinstance(path, str) or len(path) > 256:
            raise ValueError('Invalid API path')
        options = options or {}
        if not isinstance(options, dict) or set(options) - {'method','headers','body'}:
            raise ValueError('Invalid request options')
        method = options.get('method','GET')
        if method not in ('GET','POST'):
            raise ValueError('Only lab reads and run creation are allowed')
        body = None
        if method == 'GET':
            if not READ_PATH.fullmatch(path) or options.get('body') is not None:
                raise ValueError('Read path is not allowlisted')
        else:
            raw = options.get('body','')
            if path != '/api/runs' or not isinstance(raw,str) or len(raw) > 8192:
                raise ValueError('Only bounded run creation is allowed')
            body = RunRequest.model_validate_json(raw).model_dump()
        with httpx.Client(timeout=10,trust_env=False) as client:
            response = client.request(method,self.base+path,json=body)
            return {'status':response.status_code,'body':response.json()}


def render_notebook(callback_name, height=1100):
    if not isinstance(callback_name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',callback_name):
        raise ValueError('Invalid callback name')
    if type(height) is not int or not 300 <= height <= 3000:
        raise ValueError('Invalid viewer height')
    token = secrets.token_hex(12)
    identity = 'blackout-notebook-'+token
    assets = files('blackout').joinpath('static')
    page = assets.joinpath('index.html').read_text(encoding='utf-8')
    css = assets.joinpath('style.css').read_text(encoding='utf-8')
    app = assets.joinpath('app.js').read_text(encoding='utf-8')
    child = r"""
const pending=new Map();let requestId=0;
window.fetch=(path,options={})=>new Promise((resolve,reject)=>{
  const id=++requestId;
  const timer=setTimeout(()=>{pending.delete(id);reject(Error('Notebook connection timed out. Keep the Colab session connected and idle.'));},15000);
  pending.set(id,{resolve,reject,timer});
  parent.postMessage({channel:CHANNEL,id,path,options},'*');
});
window.addEventListener('message',event=>{
  if(event.source!==parent||event.data?.channel!==CHANNEL)return;
  const item=pending.get(event.data.id);if(!item)return;
  pending.delete(event.data.id);clearTimeout(item.timer);
  if(event.data.error)item.reject(Error(event.data.error));
  else item.resolve(new Response(JSON.stringify(event.data.result.body),{status:event.data.result.status,headers:{'Content-Type':'application/json'}}));
});
document.addEventListener('click',async event=>{
  const anchor=event.target.closest('a#download');if(!anchor)return;
  event.preventDefault();
  try{
    const response=await fetch(anchor.getAttribute('href'));if(!response.ok)throw Error('Report download failed');
    const report=await response.json(),url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='blackout-report.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){const banner=document.getElementById('banner');banner.textContent=error.message;banner.hidden=false;}
});
""".replace('CHANNEL',json.dumps(token))
    page = page.replace('<link rel="stylesheet" href="/static/style.css">','<style>'+css+'</style>')
    page = page.replace('<script src="/static/app.js" defer></script>','')
    page = page.replace('</body>','<script>'+child+app+'</script></body>')
    parent_script = r"""
(()=>{
  const frame=document.getElementById(FRAME);
  window.addEventListener('message',async event=>{
    if(event.source!==frame.contentWindow||event.data?.channel!==CHANNEL)return;
    const id=event.data.id;
    try{
      const response=await google.colab.kernel.invokeFunction(CALLBACK,[event.data.path,event.data.options],{});
      frame.contentWindow.postMessage({channel:CHANNEL,id,result:response.data['application/json']},'*');
    }catch(error){frame.contentWindow.postMessage({channel:CHANNEL,id,error:'Notebook request failed. Check the running lab and Colab session.'},'*');}
  });
})();
""".replace('FRAME',json.dumps(identity)).replace('CHANNEL',json.dumps(token)).replace('CALLBACK',json.dumps(callback_name))
    return (f'<iframe id="{identity}" title="BlackoutLab notebook" sandbox="allow-scripts allow-downloads" '
            f'style="width:100%;height:{height}px;border:0" srcdoc="{html.escape(page,quote=True)}"></iframe>'
            '<script>'+parent_script+'</script>')


def display_lab(port=8081, height=1100):
    """Display the real control UI using the current trusted Colab output session."""
    from google.colab import output
    from IPython.display import HTML, JSON, display
    bridge = NotebookBridge(port)
    callback = 'blackout.lab_'+secrets.token_hex(12)
    def invoke(path, options=None):
        try:
            return JSON(bridge.request(path,options))
        except ValueError:
            return JSON({'status':400,'body':{'detail':'Notebook request is not allowed'}})
    output.register_callback(callback,invoke)
    display(HTML(render_notebook(callback,height)))
