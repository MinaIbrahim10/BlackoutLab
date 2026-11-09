// DOM integration, not visual/browser QA. Requires jsdom and an installed package.
const {JSDOM, VirtualConsole} = require('jsdom');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {mkdtemp, rm} = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, label) {
  for (let i=0; i<300; i++) { if (await predicate()) return; await delay(30); }
  throw Error('Timed out: '+label);
}
(async () => {
  const socket=net.createServer();
  await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
  const port=socket.address().port;
  await new Promise(resolve=>socket.close(resolve));
  const folder=await mkdtemp(path.join(os.tmpdir(),'blackout-ui-'));
  const server=spawn(process.env.PYTHON||'python',['-m','blackout','serve','--port',String(port)],{
    cwd:folder, env:{...process.env,OLLAMA_BASE_URL:'http://127.0.0.1:1'},stdio:'ignore'
  });
  let dom;
  try {
    const base='http://127.0.0.1:'+port;
    await until(async()=>{try{return (await fetch(base+'/healthz')).ok;}catch{return false;}},'server health');
    const errors=[];
    const console=new VirtualConsole();
    console.on('jsdomError',error=>errors.push(error.message));
    dom=await JSDOM.fromURL(base,{resources:'usable',runScripts:'dangerously',virtualConsole:console,
      beforeParse(window){
        window.fetch=(url,options)=>fetch(new URL(url,base),options);
        const interval=window.setInterval.bind(window);
        window.setInterval=(fn,ms,...args)=>interval(fn,ms===300?5:ms,...args);
      }});
    const window=dom.window, document=window.document, $=id=>document.getElementById(id);
    await until(()=>$('connection').textContent.includes('Lab connected'),'initial connection');
    assert.equal(document.querySelectorAll('.scenario-option').length,3);
    const results=[];
    for(let i=0;i<3;i++) {
      document.querySelectorAll('.scenario-option')[i].click();
      const previous=$('download').getAttribute('href');
      $('launch').click();
      await until(()=>$('incidentStatus').textContent==='Recovered' && !$('launch').disabled && $('download').getAttribute('href')!==previous,'recovery '+i);
      assert.equal(document.querySelectorAll('#checks .pass').length,6);
      assert.equal($('ordersValue').textContent,'2');
      assert.equal($('paymentsValue').textContent,'2');
      assert.equal($('stockValue').textContent,'17');
      assert.equal(document.querySelectorAll('.agent-row.disabled').length,5);
      const report=await (await fetch(new URL($('download').getAttribute('href'),base))).json();
      assert.equal(report.status,'recovered');
      assert.equal(report.metrics.agent_calls,0);
      const count=document.querySelectorAll('.timeline-entry').length;
      $('replay').click();
      await until(()=>!$('replay').disabled,'timeline replay');
      assert.equal(document.querySelectorAll('.timeline-entry').length,count);
      results.push({scenario:report.scenario,status:report.status,checks:report.metrics.checks_passed});
    }
    document.querySelector('[data-view="history"]').click();
    await until(()=>document.querySelectorAll('#historyRows button').length===3,'history');
    assert.equal($('history').hidden,false);
    document.querySelector('#historyRows button').click();
    await until(()=>!$('launch').disabled && !$('download').hidden,'reopen history');
    assert.equal($('operations').hidden,false);
    document.querySelector('[data-view="guide"]').click();
    assert.equal($('guide').hidden,false);
    document.querySelector('[data-view="operations"]').click();
    $('mode').value='multi'; $('mode').dispatchEvent(new window.Event('change'));
    $('launch').click();
    await until(()=>$('incidentStatus').textContent==='Unresolved' && !$('launch').disabled,'visible inference failure');
    assert.equal(document.querySelectorAll('.agent-row.failed').length,1);
    const failed=await (await fetch(new URL($('download').getAttribute('href'),base))).json();
    assert.equal(failed.actions.length,0);
    assert.equal(failed.metrics.agent_failures,1);
    assert.deepEqual(errors,[]);
    process.stdout.write(JSON.stringify({kind:'DOM integration; no visual QA',results,history:true,replay:true,download:true,unavailableModel:'visible, no fallback',javascriptErrors:errors},null,2)+'\n');
  } finally {
    dom?.window.close(); server.kill();
    await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
    await rm(folder,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
