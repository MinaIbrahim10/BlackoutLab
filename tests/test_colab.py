import json
import pytest
import httpx
from blackout.colab import NotebookBridge, render_notebook


@pytest.mark.parametrize('path,options',[
    ('https://example.com/api/config',None),
    ('/internal/'+'a'*32+'/fault',{'method':'POST','body':'{}'}),
    ('/api/runs',{'method':'DELETE'}),
    ('/api/runs',{'method':'POST','body':json.dumps({'scenario':'shell'})}),
    ('/api/runs',{'method':'POST','body':'x'*9000}),
    ('/api/config?target=http://example.com',None),
    ('/api/config',{'headers':{},'credentials':'include'}),
])
def test_bridge_rejects_requests_outside_lab_surface(path,options,monkeypatch):
    def unexpected(*args,**kwargs):raise AssertionError('Network must not be reached')
    monkeypatch.setattr('blackout.colab.httpx.Client',unexpected)
    with pytest.raises(ValueError):NotebookBridge().request(path,options)


def test_bridge_forwards_only_validated_run_creation_and_reads(monkeypatch):
    original=httpx.Client
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(202 if request.method=='POST' else 200,json={'ok':True})
    monkeypatch.setattr('blackout.colab.httpx.Client',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    bridge=NotebookBridge()
    assert bridge.request('/api/config')['status']==200
    assert bridge.request('/api/runs',{'method':'POST','body':json.dumps({'scenario':'orphaned-payment','mode':'multi'})})['status']==202
    assert bridge.request('/api/runs/'+'a'*32+'/events?after=2')['body']=={'ok':True}
    assert all(request.url.host=='127.0.0.1' and request.url.port==8081 for request in calls)
    assert json.loads(calls[1].content)=={'scenario':'orphaned-payment','mode':'multi'}


def test_notebook_renderer_isolates_styles_and_checks_message_source():
    page=render_notebook('blackout.test')
    assert 'sandbox="allow-scripts allow-downloads"' in page
    assert 'event.source!==frame.contentWindow' in page
    assert 'google.colab.kernel.invokeFunction("blackout.test"' in page
    assert '/static/app.js' not in page
    assert '/static/style.css' not in page
    assert 'allow-same-origin' not in page
    for callback in ['bad\"name','</script>','https://external']:
        with pytest.raises(ValueError):render_notebook(callback)
