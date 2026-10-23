const path=require('node:path');
const {runTests}=require('../../.vscode-build/node_modules/@vscode/test-electron');
delete process.env.ELECTRON_RUN_AS_NODE;
runTests({
  vscodeExecutablePath:'/Applications/Visual Studio Code.app/Contents/MacOS/Code',
  extensionDevelopmentPath:path.resolve(__dirname,'..'),
  extensionTestsPath:path.resolve(__dirname,'host-test.js'),
  launchArgs:['--user-data-dir='+path.resolve(__dirname,'../../.scratch/vscode-test-user'),'--extensions-dir='+path.resolve(__dirname,'../../.scratch/vscode-test-extensions'),'--disable-workspace-trust','--skip-welcome','--skip-release-notes','--disable-extensions',path.resolve(__dirname,'../..')]
}).catch(e=>{console.error(e);process.exitCode=1;});
