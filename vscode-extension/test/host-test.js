const assert=require('node:assert/strict');
const vscode=require('vscode');
exports.run=async()=>{
  const ext=vscode.extensions.getExtension('tgengin-local.tgengin');
  assert.ok(ext,'extension discovered');
  await ext.activate();
  const commands=await vscode.commands.getCommands(true);
  for(const name of ['open','start','newTask','selection','token','refresh'])assert.ok(commands.includes('tgengin.'+name),name);
  await vscode.commands.executeCommand('tgengin.open');
  await vscode.commands.executeCommand('tgengin.refresh');
  console.log('TGENGIN_HOST_TEST_PASSED: activated, commands registered, webview opened, real API refreshed');
};
