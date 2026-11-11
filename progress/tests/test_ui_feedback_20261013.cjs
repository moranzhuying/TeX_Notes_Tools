'use strict';
const fs=require('fs'),assert=require('assert'),{JSDOM,VirtualConsole}=require('jsdom');
const [base,out]=process.argv.slice(2);
async function wait(fn){const end=Date.now()+90000;while(Date.now()<end){if(fn())return;await new Promise(r=>setTimeout(r,30));}throw Error('交互等待超时');}
(async()=>{
const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const html=await(await fetch(base)).text(),nav=await(await fetch(base+'/navigation')).json();
const dom=new JSDOM(html,{url:base,runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,beforeParse(w){w.confirm=()=>true;w.fetch=(u,o)=>{const url=new URL(u,base);assert(!o?.method||o.method==='GET','真实服务禁止写请求');calls.push(url);return fetch(url,o);};}});
const w=dom.window,$=id=>w.document.getElementById(id),checks=[];
function check(name,value){assert(value,name);checks.push(name);}
try{
await wait(()=>$('baseline').textContent&&$('message').textContent.includes('轻量导航已读取'));
check('canonical搜索仅在按需栏且无镜像', $('fullQuery').closest('#searchPanel')&&!w.document.querySelector('header #fullQuery')&&!$('queryMirror')&&!$('mirrorAllSearch')&&!$('mirrorBookSearch'));
check('canonical唯一',w.document.querySelectorAll('#fullQuery').length===1);
check('八书1818基线',nav.books.length===8&&nav.books.reduce((n,b)=>n+b.units.length,0)===1818);
for(const b of nav.books){
if($('book').value!==b.name){$('book').value=b.name;$('book').dispatchEvent(new w.Event('change',{bubbles:true}));}
try{await wait(()=>w.eval('book.name')===b.name&&$('baseline').textContent&&w.eval('selectedBook')===b.name);}catch(e){throw Error(b.name+' '+$('message').textContent+' '+JSON.stringify(errors)+' '+w.eval('selectedBook')+' '+e.message);}
const expected=b.units.map(u=>u.id).sort();
for(const id of ['unit','current_body','current_proof'])check(b.name+' '+id+'稳定集合',JSON.stringify([...$(id).options].map(o=>o.value).filter(Boolean).sort())===JSON.stringify(expected));
for(const id of ['scope','current_summary'])check(b.name+' '+id+'稳定scope集合',JSON.stringify([...$(id).options].map(o=>o.value).filter(Boolean).sort())===JSON.stringify([...b.scopes].sort()));
for(const id of ['unit','current_body','current_proof','scope','current_summary'])check(b.name+' '+id+'统一显示标签',[...$(id).options].filter(o=>o.value).every(o=>/^(Chap\d+|附录 \d+) ·/.test(o.textContent)&&!/(章|节)\s+\d+ ·/.test(o.textContent)));
for(const view of ['body','proof','summary']){
w.document.querySelector('[data-view="'+view+'"]').click();
for(const scope of b.scopes.filter(s=>/^[CS]\d+$/.test(s.split('/').at(-1)))){const last=scope.split('/').at(-1),prefix=last[0]==='C'?'Chap':'§';check(b.name+' '+view+' '+scope+'标签',w.eval('scopeLabel('+JSON.stringify(scope)+')').startsWith(prefix+Number(last.slice(1))+' · '));}
check(b.name+' '+view+'目录无旧章/节编号',!/(章|节)\s+\d+ ·/.test($('tree').textContent));
}
}
w.document.querySelector('[data-view="body"]').click();
$('searchPanel').closest('details').open=true;
$('fullQuery').value='群';$('fullQuery').dispatchEvent(new w.Event('input',{bubbles:true}));
$('fullSearch').click();await wait(()=>$('fullStatus').textContent.includes('命中文件'));
await wait(()=>$('hitParticipation').textContent.split('\n').length===3);
check('全书请求',calls.filter(u=>u.pathname==='/search').at(-1).searchParams.get('book')==='');
$('book').value='General_Topology';$('book').dispatchEvent(new w.Event('change',{bubbles:true}));await wait(()=>w.eval('selectedBook')==='General_Topology');
$('fullQuery').value='拓扑';$('fullQuery').dispatchEvent(new w.Event('input',{bubbles:true}));$('fullQuery').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
await wait(()=>$('fullStatus').textContent.includes('命中文件'));await wait(()=>$('hitParticipation').textContent.split('\n').length===3);
check('Enter搜索当前书',calls.filter(u=>u.pathname==='/search').at(-1).searchParams.get('book')==='General_Topology');
$('bookSearch').click();await wait(()=>$('fullStatus').textContent.includes('命中文件'));await wait(()=>$('sourceContext').querySelector('.source-line.current'));
await wait(()=>$('participation').textContent.split('\n').length===3);
for(const id of ['participation','hitParticipation'])check(id+'三语义行',$(id).textContent.split('\n').length===3&&$(id).textContent.split('\n')[1].startsWith('PDF时间：')&&$(id).textContent.split('\n')[2].startsWith('静态链：'));
$('pdfTab').click();check('PDF tab切换',$('sourcePane').hidden&&!$('pdfPane').hidden);$('sourceTab').click();check('源码tab切换',!$('sourcePane').hidden&&$('pdfPane').hidden);
check('零运行错误',errors.length===0);check('真实服务无写请求',true);
fs.writeFileSync(out+'/jsdom.json',JSON.stringify({checks:checks.length,names:checks,errors,ids:nav.books.map(b=>({book:b.name,ids:b.units.map(u=>u.id).sort(),scopes:b.scopes}))},null,2));
console.log(JSON.stringify({checks:checks.length,errors}));
}finally{w.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
