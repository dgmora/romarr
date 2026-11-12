import shutil
import subprocess

import pytest

from romarr.ui import page


def test_queue_shows_hub_failure_and_bulk_refusals_after_refresh():
    node = shutil.which("node")
    if not node:
        pytest.skip("node required to execute Queue UI regression")
    source = page().split("RENDER.queue=", 1)[1].split("RENDER.history=", 1)[0]
    script = r'''
const assert=require('node:assert/strict');
const item={game:'Crash 2',platform:'psx',release:'Crash Bandicoot 2',state:'failed',
 display_release:'Crash — Discs 1, 3',detail:'metadata HTTP 503',hub:true,at:'now',download_id:'job',download_client:'hub'};
const nodes={};
const $=key=>nodes[key]??=(key==='#page'?{
 html:'',children:[],set innerHTML(v){this.html=v;this.children=[]},
 get innerHTML(){return this.html},prepend(e){this.children.unshift(e)}
}:{});
let action;
const j=async(url,options)=>{
 if(url==='/api/v1/queue')return {items:[item]};
 if(url.endsWith('/clear'))return {ok:false,removed:1,errors:[
  {game:'B',error:'disk full'},{game:'C',error:'repair identity'}]};
 action=JSON.parse(options.body);return {ok:false,error:'active operation'};
};
const retry={dataset:{qretry:'0'}},remove={dataset:{qremove:'0'}};
const document={querySelectorAll:s=>s.includes('qretry')?[retry]:[remove],
 createElement:()=>({setAttribute(){}})};
const esc=s=>String(s),refreshCounts=()=>{},toast=()=>{},go=()=>{};
const setInterval=()=>0,clearInterval=()=>{};
const RENDER={};
RENDER.queue=QUEUE;
(async()=>{
 await RENDER.queue();
 assert.match($('#page').innerHTML,/metadata HTTP 503/);
 assert.match($('#page').innerHTML,/Crash — Discs 1, 3/);
 assert.match($('#page').innerHTML,/Retry/);
 assert.doesNotMatch($('#page').innerHTML,/Preview import/);
 await retry.onclick();
 assert.equal(action.action,'retry');
 assert.deepEqual(action.identity,{at:'now',download_id:'job',download_client:'hub',release:'Crash Bandicoot 2'});
 await $('#q-clearfail').onclick();
 assert.match($('#page').innerHTML,/metadata HTTP 503/);
 assert.match($('#page').children[0].textContent,/B: disk full.*C: repair identity/);
 item.state='import-review';item.can_preview_import=true;
 await RENDER.queue();
 assert.match($('#page').innerHTML,/Preview import/);
 item.state='imported';item.can_preview_import=false;
 await RENDER.queue();
 assert.doesNotMatch($('#page').innerHTML,/Preview import/);
})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('QUEUE', source.strip().rstrip(';'))
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
