const vscode = require('vscode');
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const {request} = require('./client');

function activate(context) {
  const output = vscode.window.createOutputChannel('TgEngin');
  const changed = new vscode.EventEmitter();
  let tasks = [], panel, current, terminal, refreshing = false;
  const cfg = () => vscode.workspace.getConfiguration('tgengin');
  const api = async (route, body) => request(cfg().get('endpoint'), route, await context.secrets.get('token:' + cfg().get('endpoint')), body);
  const guarded = fn => async (...args) => {
    try {
      if (!vscode.workspace.isTrusted) throw new Error('请先信任此工作区，再使用 TgEngin。');
      return await fn(...args);
    } catch(e) { vscode.window.showErrorMessage(`TgEngin: ${e.message}`); }
  };
  const tree = {
    onDidChangeTreeData: changed.event,
    getChildren: () => tasks,
    getTreeItem: t => {
      const item = new vscode.TreeItem(t.id);
      item.description = `${t.state} · ${t.agent}`;
      item.tooltip = t.description || t.id;
      item.command = {command:'tgengin.open', title:'查看任务', arguments:[t.id]};
      item.iconPath = new vscode.ThemeIcon(t.state === 'done' ? 'pass' : t.state === 'failed' ? 'error' : 'circle-outline');
      return item;
    }
  };
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    const target = current;
    try {
      tasks = (await api('/tasks?limit=100')).rows;
      changed.fire();
      let detail;
      if (target && panel) {
        const id = encodeURIComponent(target);
        const [task, first] = await Promise.all([api('/tasks/' + id), api('/tasks/' + id + '/messages?limit=200')]);
        // Display the most recent page for long tasks, not permanently the first page.
        const messages = first.total > 200 ? await api('/tasks/' + id + '/messages?limit=200&offset=' + (first.total - 200)) : first;
        detail = {task, messages};
      }
      if (target === current) panel?.webview.postMessage({type:'state', tasks, current, detail, endpoint:cfg().get('endpoint')});
    } catch(e) {
      panel?.webview.postMessage({type:'error', text:e.message + '。可点击“启动 / 连接”。'});
      throw e;
    } finally { refreshing = false; }
  }
  async function open(id) {
    if (typeof id === 'string') current = id;
    if (!panel) {
      panel = vscode.window.createWebviewPanel('tgengin', 'TgEngin', vscode.ViewColumn.One, {enableScripts:true, localResourceRoots:[vscode.Uri.joinPath(context.extensionUri,'media')]});
      panel.webview.html = html(panel.webview, context.extensionUri);
      panel.onDidDispose(() => {panel = undefined;});
      panel.webview.onDidReceiveMessage(guarded(async m => {
        if (!m || typeof m.type !== 'string') return;
        if (m.type === 'ready' || m.type === 'refresh') await refresh();
        if (m.type === 'start') await start();
        if (m.type === 'new') await newTask(false, typeof m.text === 'string' ? m.text : undefined);
        if (m.type === 'select' && tasks.some(t => t.id === m.id)) {current = m.id; await refresh();}
        if (m.type === 'intervene' && current && typeof m.text === 'string' && m.text.trim()) {
          await api('/tasks/' + encodeURIComponent(current) + '/messages', {body:m.text});
          panel?.webview.postMessage({type:'sent'});
          await refresh();
        }
        if ((m.type === 'tree' || m.type === 'why') && current) {
          const data = await api('/tasks/' + encodeURIComponent(current) + '/' + m.type);
          await vscode.window.showTextDocument(await vscode.workspace.openTextDocument({content:JSON.stringify(data,null,2),language:'json'}), {preview:true,viewColumn:vscode.ViewColumn.Beside});
        }
      }));
    } else {panel.reveal(); await refresh();}
  }
  async function start() {
    try {await api('/about'); await open(); await refresh(); return;} catch {}
    const url = new URL(cfg().get('endpoint'));
    if (!['127.0.0.1','localhost','[::1]'].includes(url.hostname)) throw new Error('远程引擎不可达，请先在服务器启动，或修改 TgEngin: Endpoint 设置');
    const root = cfg().get('engineRoot'), bun = cfg().get('bunPath');
    if (!fs.existsSync(path.join(root,'app/src/main.ts')) || !fs.existsSync(bun)) throw new Error('找不到源码或 Bun，请检查 TgEngin: Engine Root / Bun Path 设置');
    if (!terminal) {
      // A VS Code terminal owns the process; no shell interpolation of paths or secrets.
      terminal = vscode.window.createTerminal({name:'TgEngin Engine', cwd:root, shellPath:bun,
        shellArgs:['--env-file=' + path.join(root,'.env'), path.join(root,'app/src/main.ts')],
        env:{TGENGIN_CONFIG:cfg().get('configPath') || path.join(root,'config.yaml')}});
    }
    terminal.show(true);
    await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:'TgEngin 正在启动…'}, async () => {
      for (let i=0;i<30;i++) {
        await new Promise(r=>setTimeout(r,500));
        try {await api('/about'); await open(); await refresh(); return;} catch {}
      }
      throw new Error('启动未就绪。请查看 TgEngin Engine 终端，并确认 config.yaml 端口与 Endpoint 一致');
    });
  }
  async function pick(items, title) {
    if (!items?.length) throw new Error(title + '：引擎尚未配置，请参考插件 README 的初始化说明');
    return vscode.window.showQuickPick(items,{title,ignoreFocusOut:true});
  }
  async function newTask(selection, supplied) {
    const editor = vscode.window.activeTextEditor;
    const selected = selection && editor ? `\n\n文件：${editor.document.uri.fsPath}\n选中内容（编辑器当前版本）：\n${editor.document.getText(editor.selection)}` : '';
    const about = await api('/about');
    const description = supplied?.trim() || await vscode.window.showInputBox({title:'TgEngin：描述任务',prompt:'任务可调用工具并直接修改工作目录中的文件',ignoreFocusOut:true});
    if (!description?.trim()) return;
    const mode = await pick(about.declared.modes,'选择执行模式'); if (!mode) return;
    const agent = await pick(about.declared.agents,'选择智能体'); if (!agent) return;
    const place = await pick(about.declared.places,'选择执行位置'); if (!place) return;
    let folder;
    if (place === 'local' && vscode.workspace.workspaceFolders?.length) {
      folder = vscode.workspace.workspaceFolders.length === 1 ? vscode.workspace.workspaceFolders[0] : await vscode.window.showWorkspaceFolderPick();
      if (!folder) return;
    }
    const workdir = await vscode.window.showInputBox({title:'确认任务工作目录',value:folder?.uri.fsPath || '',prompt:place === 'local' ? '引擎所在机器上的绝对路径；文件工具将直接在此执行' : '执行位置中的绝对路径（不是本机路径）',ignoreFocusOut:true,validateInput:v=>v.trim() ? undefined : '请填写工作目录'});
    if (!workdir) return;
    const result = await api('/tasks',{id:'vscode-' + crypto.randomUUID(),source:'user',description:description + selected,mode,agent,place,workdir});
    current = result.id;
    panel?.webview.postMessage({type:'sent'});
    await open(current);
    await refresh();
  }
  const register = (name, fn) => context.subscriptions.push(vscode.commands.registerCommand(name,guarded(fn)));
  register('tgengin.open',open); register('tgengin.start',start);
  register('tgengin.newTask',()=>newTask(false)); register('tgengin.selection',()=>newTask(true));
  register('tgengin.refresh',refresh);
  register('tgengin.token',async()=>{
    const value = await vscode.window.showInputBox({title:'引擎 API 令牌（留空清除）',password:true,ignoreFocusOut:true});
    if (value !== undefined) {await context.secrets.store('token:' + cfg().get('endpoint'),value); await refresh();}
  });
  const view = vscode.window.createTreeView('tgengin.tasks',{treeDataProvider:tree});
  const timer = setInterval(()=>{if (panel?.visible || view.visible) refresh().catch(()=>{});},2500);
  context.subscriptions.push(output,changed,view,{dispose:()=>clearInterval(timer)},vscode.window.onDidCloseTerminal(t=>{if(t===terminal) terminal=undefined;}));
  refresh().catch(()=>{});
}
function html(webview, uri) {
  const nonce = crypto.randomBytes(16).toString('hex');
  const script = webview.asWebviewUri(vscode.Uri.joinPath(uri,'media','panel.js'));
  const style = webview.asWebviewUri(vscode.Uri.joinPath(uri,'media','panel.css'));
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';"><link rel="stylesheet" href="${style}"></head><body>
  <header><h1>TgEngin <small>任务工作台</small></h1><button id="start">启动 / 连接</button><button id="refresh">刷新</button></header>
  <p id="status">正在连接…</p><div class="layout"><aside><h3>最近 100 个任务</h3><div id="tasks"></div></aside><main>
  <h2 id="title">创建任务，开始工作</h2><p id="meta"></p><button id="tree">执行树 JSON</button><button id="why">诊断原因</button>
  <div id="messages"><p>输入需求后，选择模式、智能体和工作目录。</p></div>
  <textarea id="input" rows="5" placeholder="输入新任务，或向运行中的任务补充要求…"></textarea>
  <p class="hint">任务可能直接修改工作目录中的文件。消息每 2.5 秒刷新，显示最近 200 条。结束的任务请新建任务继续。</p>
  <button id="new">新建任务</button><button id="intervene">发送给当前运行任务</button>
  </main></div><script nonce="${nonce}" src="${script}"></script></body></html>`;
}
module.exports = {activate};
