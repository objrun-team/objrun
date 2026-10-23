const vscode = acquireVsCodeApi();
const el = id => document.getElementById(id);
const saved = vscode.getState();
el('input').value = saved?.draft || '';
el('input').addEventListener('input',()=>vscode.setState({draft:el('input').value}));
for (const type of ['start','refresh','tree','why','new','intervene']) el(type).onclick=()=>vscode.postMessage({type,text:el('input').value});
let lastMessages = '';
window.addEventListener('message',({data:m})=>{
  if(m.type==='error'){el('status').textContent=m.text;return;}
  if(m.type==='sent'){el('input').value='';vscode.setState({draft:''});return;}
  if(m.type!=='state')return;
  el('status').textContent='已连接 · '+m.endpoint;
  el('tasks').replaceChildren(...m.tasks.map(t=>{
    const b=document.createElement('button');b.className='task'+(t.id===m.current?' selected':'');
    b.textContent=t.id+'\n'+t.state+' · '+t.agent;
    b.onclick=()=>vscode.postMessage({type:'select',id:t.id});return b;
  }));
  el('tree').disabled=el('why').disabled=!m.current;
  el('intervene').disabled=!m.detail || !['open','claimed'].includes(m.detail.task.state);
  if(!m.detail)return;
  el('title').textContent=m.current;
  el('meta').textContent='状态：'+m.detail.task.state;
  const serialized=JSON.stringify(m.detail.messages.rows);
  if(serialized===lastMessages)return;lastMessages=serialized;
  const box=el('messages'),nearBottom=box.scrollHeight-box.scrollTop-box.clientHeight<80;
  box.replaceChildren(...m.detail.messages.rows.map(msg=>{
    const article=document.createElement('article'),label=document.createElement('strong'),body=document.createElement('pre');
    label.textContent=(msg.human?'你':msg.role||msg.kind)+' · '+msg.kind+' · 单元 '+msg.unit;
    body.textContent=msg.text ?? (msg.parsed ? JSON.stringify(msg.parsed,null,2):msg.body);
    article.append(label,body);return article;
  }));
  if(nearBottom)box.scrollTop=box.scrollHeight;
});
vscode.postMessage({type:'ready'});
