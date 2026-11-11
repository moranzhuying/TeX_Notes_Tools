'use strict';
const fs=require('fs'),assert=require('assert'),{JSDOM}=require('jsdom');
const html=fs.readFileSync(require('path').join(__dirname,'../workbench_editor.html'),'utf8');
const handler=html.split('\n').find(s=>s.startsWith("$('hitOpenTex').onclick="));
(async()=>{const dom=new JSDOM('<button id="hitOpenTex"></button>');const w=dom.window;let submitted,notice;const hit={book:'Book',unit:'C01',path:'中文 空格 & [合法] #定位.tex',line:17,sha256:'a'.repeat(64)};
const run=new Function('$','safe','selectedHit','catalog','busy','api','confirm','msg',handler+";return $('hitOpenTex').onclick();");
for(const change of ['新增','删除','等长替换']){submitted=null;notice=null;const api=async(url,body)=>{if(url==='/participation')return {absolute_path:hit.path};submitted=body;throw Error('搜索命中源码已变化，请重新搜索；未调用TeXstudio');};
await run(id=>w.document.getElementById(id),fn=>async()=>{try{await fn();}catch(e){notice=e.message;}},hit,{allow_open:true},false,api,()=>true,m=>{notice=m;});
assert.equal(submitted.expected,hit.sha256);assert.equal(submitted.line,17);assert.equal(submitted.path,hit.path);assert(notice.includes('已变化'),change);}
w.close();console.log(JSON.stringify({checks:9,variants:['新增','删除','等长替换'],note:'真实DOM执行生产点击处理器；HTTP冲突由Python隔离suite独立验证'}));})().catch(e=>{console.error(e);process.exitCode=1;});
