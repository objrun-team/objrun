/** Build the Filter driver with provider-probe + runtime injected campaign.
 * Injected launcher binds argv from the manifest pins and normalizes before spawn.
 * Loader-level diagnostic: after the original source pin is verified, the provider-probe
 * loader's returned contents for configured-observed-spawn.ts get a print before the argv
 * demand (import.meta.path, command, args, entry, python, manifest path, four resolves).
 * The shared source file and the signed config remain unchanged. */
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pin} from './manifest.ts';

const here = import.meta.dir;
const original = join(here, 'build-nonblocking-history-release.ts');

const helperSource = `async function campaignRuntime(api,d,runDir){
  const inj=d.standInjection;
  const fs=await import("node:fs"),path=await import("node:path"),url=await import("node:url");
  let contents=inj?.contents,launcher=inj?.launcherContents,resolveDir=inj?.resolveDir,lp=inj?.proof?.launcherPin?.path??inj?.launcherPin?.path;
  if(!contents||!launcher||!resolveDir||!lp){
    const sp=path.join(runDir,"stand-injected-sources.json"),pp=path.join(runDir,"stand-injection-proof.json");
    if(!fs.existsSync(sp)||!fs.existsSync(pp))return api.campaign;
    const s=JSON.parse(fs.readFileSync(sp,"utf8")),p=JSON.parse(fs.readFileSync(pp,"utf8"));
    contents=s.campaign;launcher=s.launcher;resolveDir=path.dirname(p.originalCampaignPin.path);lp=p.launcherPin.path;
  }
  if(!contents||!launcher||!resolveDir||!lp)return api.campaign;
  const m=JSON.parse(fs.readFileSync(process.env.BENCH_MANIFEST_PATH,"utf8"));
  const st=m.adapterConfig.terminalDriver.qualifiedInterfaces.stand;
  const nonce=process.pid+"-"+Date.now()+"-"+Math.random().toString(16).slice(2);
  const ld=path.dirname(lp),lf=path.join(ld,".injected-launcher-"+nonce+".ts");
  const cf=path.join(resolveDir,".injected-campaign-"+nonce+".ts");
  let l=launcher.replace('const python="D:/ProgramData/anaconda3/python.exe";','const python='+JSON.stringify(st.pythonPin.path)+';');
  l=l.replace('const args=["-B","-X","utf8",options.script,','const args=["-B","-X","utf8",'+JSON.stringify(st.standEntryPin.path)+',');
  const entry=JSON.stringify(st.standEntryPin.path);
  l=l.replace(/(const args=\\[[^\\]]*\\];)/,'$1'+'const __entry='+entry+';const __before=args.slice();const __clean=__before.filter(x=>x!=="-B"&&x!=="-X"&&x!=="utf8"&&x!==__entry&&x!==options.script);const __after=(__before[0]==="-B"&&__before[1]==="-X"&&__before[2]==="utf8")?__before:["-B","-X","utf8",__entry,...__clean];'+'try{const __fs=await import("node:fs");const __rd=process.env.BENCH_RUN_DIR;if(__rd){const __p=__rd+"/command-intent.json";const __ci=JSON.parse(__fs.readFileSync(__p,"utf8"));__ci.standArgvBinding={before:__before,after:__after,command:python};__fs.writeFileSync(__p,JSON.stringify(__ci));}}catch{}');
  l=l.replace('spawn(python,args,','spawn(python,__after,');
  let c=contents.replace(/from\\s+["'][^"']*stand_process\\.ts["']/,"from "+JSON.stringify(lf.replaceAll("\\\\","/")));
  fs.writeFileSync(lf,l);fs.writeFileSync(cf,c);
  try{const mod=await import(url.pathToFileURL(cf).href);return mod.executeFullF??mod.campaign;}
  finally{}
}
`;

const loaderTransform = `
function loaderDebug(path, contents) {
  if (path.endsWith("qualified-relative-interfaces.ts") || path.endsWith("qualified-mapped-interfaces.ts") || path.endsWith("qualified-driver-interfaces.ts")) {
    // Route data join: the engine omits stream for its non-streaming transport, while
    // the signed route contract requires stream===false. Make the wire body explicit;
    // model/max_tokens/reasoning/provider are untouched.
    let out = contents;
    const gwAnchor = "export function gatewayWithBeforeJournal(sourceText:string,g:any){checkPin(g.pin);";
    if (out.split(gwAnchor).length !== 2) throw Error("gateway_stream_anchor");
    out = out.replace(gwAnchor, "export function gatewayWithBeforeJournal(sourceText:string,g:any){sourceText=sourceText.replace('const wire=JSON.stringify(body);','if(body.stream===undefined)body.stream=false;const wire=JSON.stringify(body);');checkPin(g.pin);");
    const vmAnchor = "if(s.relativeImports){contents=exactReplace(contents,s.expectedExpression,'script:options.standScriptPath');";
    if (out.split(vmAnchor).length !== 2) throw Error("campaign_verifier_anchor");
    out = out.replace(vmAnchor, vmAnchor + "contents=exactReplace(contents,\\\"const verifierMs=(task.verifierSeconds+30)*1000,toolMs=(task.agentSeconds+30)*1000;\\\",\\\"const verifierMs=(task.agentSeconds+task.verifierSeconds+30)*1000,toolMs=(task.agentSeconds+30)*1000;\\\");");
    // Ready wait: keep the 100ms poll, but take the TOTAL budget from the signed
    // startupDeadlineBinding.originalHttpDefaultMs instead of the hardcoded 600 ticks.
    const anchor = "return{contents,launcherContents,resolveDir:";
    if (out.split(anchor).length !== 2) throw Error("launcher_deadline_anchor");
    const inject = "const __sd=s.startupDeadlineBinding;const __ms=__sd&&Number.isSafeInteger(__sd.originalHttpDefaultMs)&&__sd.originalHttpDefaultMs>0?__sd.originalHttpDefaultMs:60000;const __steps=Math.ceil(__ms/100);try{console.error(JSON.stringify({launcherReadyDeadlineMs:__ms,launcherReadySteps:__steps,signedStartupDeadline:!!(__sd&&__sd.originalHttpDefaultMs)}))}catch{}return{contents,launcherContents:launcherContents.replace('step<600&&!ready','step<'+__steps+'&&!ready'),resolveDir:";
    return out.replace(anchor, inject);
  }
  if (!path.endsWith("provider-probe-loader.ts")) {
    if (!path.endsWith("terminal-driver.ts")) return contents;
    // Install the loader BEFORE the qualified stand is built/installed: the qualified
    // observer (owned-quota-configured-observed-spawn.ts -> configured-observed-spawn.ts)
    // is imported by installQualifiedStand, so a later install can never transform it.
    const late = "const financialSourceConfigPin=m.adapterConfig.financialSourceConfigPin as any;checkPin(financialSourceConfigPin);demand(m.provenance.sourcePins.some(p=>p.path===financialSourceConfigPin.path&&p.sha256===financialSourceConfigPin.sha256&&p.bytes===financialSourceConfigPin.bytes),'actual_child_financial_source_config_bound');installUnlimitedFinancialLoader(financialSourceConfigPin.path);";
    if (contents.split(late).length !== 2) throw Error("loader_install_move_anchor");
    let out = contents.replace(late, "");
    const early = "const prepared=d.qualifiedInterfaces?prepareQualifiedStand(m,d,entry):prepareStandInjection(m,d.standInjection);";
    if (out.split(early).length !== 2) throw Error("loader_install_early_anchor");
    out = out.replace(early, late + early);
    return out;
  }
  const filterAnchor = "||unlimitedFinancialSource(p,read(pins.get(p)))!==read(pins.get(p))";
  if (contents.split(filterAnchor).length !== 2) throw Error("loader_debug_filter_anchor");
  let out = contents.replace(filterAnchor, filterAnchor + "||p.replaceAll('\\\\\\\\','/').endsWith('/configured-observed-spawn.ts')");
  // The launcher now uses the explicit python-bootstrap argv contract:
  //   python -B -X utf8 <python_child_entry.py> --config <mapping> --original-script <stand> -- ...
  // The pinned observer still demanded the legacy direct argv, so the runtime failed
  // absolute_launcher_original_argv_required even though every value was a manifest pin.
  // The transform accepts EITHER exact contract, verified against the same manifest pins.
  const demand = "demand(resolve(command)===resolve(python)&&args[0]==='-B'&&args[1]==='-X'&&args[2]==='utf8'&&resolve(args[3])===resolve(entry),'absolute_launcher_original_argv_required');";
  const replacement = "const __direct=resolve(args[3])===resolve(entry);const __bootstrap=resolve(args[3])===resolve(bootstrap)&&args[4]==='--config'&&resolve(args[5])===resolve(config)&&args[6]==='--original-script'&&resolve(args[7])===resolve(entry);try{console.error(JSON.stringify({loaderConfiguredObservedSpawn:true,launcherBinding:__bootstrap?'explicit-absolute-launcher-v1':__direct?'direct-stand-v1':'unknown',args:args.slice(0,8),python,entry,bootstrap,config}))}catch{}demand(resolve(command)===resolve(python)&&args[0]==='-B'&&args[1]==='-X'&&args[2]==='utf8'&&(__direct||__bootstrap),'absolute_launcher_original_argv_required');";
  const retAnchor = "return{contents,loader:'ts',resolveDir:dirname(actual.path)}";
  if (out.split(retAnchor).length !== 2) throw Error("loader_debug_return_anchor");
  const inject = "if(actual.path.replaceAll('\\\\\\\\','/').endsWith('/configured-observed-spawn.ts')){const __d="+JSON.stringify(demand)+";const __r="+JSON.stringify(replacement)+";if(contents.split(__d).length===2)contents=contents.replace(__d,__r);}";
  out = out.replace(retAnchor, inject + retAnchor);
  return out;
}
`;

export async function buildProviderProbeRelease(outputRoot: string, kind: 'runner' | 'terminal-driver') {
  const anchor = 'contents=nonblockingHistorySource(path,contents,here);';
  const raw = readFileSync(original, 'utf8');
  if (raw.split(anchor).length !== 2) throw Error('provider_probe_builder_anchor');
  const driverTransform =
    'function driverInjectedCampaign(path, contents) {' +
    'if (!path.endsWith("terminal-driver.ts")) return contents;' +
    'const from = "const result=await api.campaign(api.formalExecuteOptions(";' +
    'const to = "const opts=api.formalExecuteOptions(";' +
    'const tailFrom = "readinessPath:d.readinessPin.path}));";' +
    'const tailTo = "readinessPath:d.readinessPin.path});opts.standScriptPath=(d.qualifiedInterfaces?.stand??d.standInjection).standEntryPin.path;const result=await (await campaignRuntime(api,d,c.runDir))(opts);";' +
    'if (contents.split(from).length !== 2 || contents.split(tailFrom).length !== 2) throw Error("driver_campaign_runtime_anchor");' +
    'let out = contents.replace(from, to); out = out.replace(tailFrom, tailTo);' +
    'return ' + JSON.stringify(helperSource) + ' + out;' +
    '}\n';
  const transformed =
    driverTransform + loaderTransform +
    'import {providerProbeSource} from ' + JSON.stringify(join(here, 'provider-probe-source.ts')) + ';\n' +
    raw.replace(anchor, anchor + 'contents=providerProbeSource(path,contents);contents=driverInjectedCampaign(path,contents);contents=loaderDebug(path,contents);');
  Bun.plugin({
    name: 'provider-probe-existing-common-builder',
    setup(b) {
      b.onLoad({filter: /build-nonblocking-history-release\.ts$/}, (args) => {
        if (resolve(args.path) !== resolve(original)) throw Error('provider_probe_builder_identity');
        return {contents: transformed, loader: 'ts', resolveDir: here};
      });
    }
  });
  const api = await import(original);
  const release = await api.buildCandidateInventoryRelease(outputRoot, kind);
  const attestation = {
    protocol: 'bench-provider-probe-common-release-v1',
    kind,
    ...release,
    builderPin: pin(import.meta.path),
    originalBuilderPin: pin(original),
    transformPin: pin(join(here, 'provider-probe-source.ts')),
    transformedBuilderSha256: createHash('sha256').update(transformed).digest('hex'),
    runtimeCampaign: 'injected campaign + manifest-pinned normalized launcher + loader-level configured print',
    originalSourcesModified: false
  };
  const out = join(resolve(outputRoot), 'provider-probe-release-' + kind + '.json');
  writeFileSync(out, JSON.stringify(attestation, null, 2) + '\n', {flag: 'wx'});
  return {...release, providerProbeReleasePin: pin(out)};
}

if (import.meta.main) console.log(JSON.stringify(await buildProviderProbeRelease(process.argv[2], process.argv[3] as any)));
