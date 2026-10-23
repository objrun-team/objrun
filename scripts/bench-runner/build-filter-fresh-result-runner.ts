/** Build the Filter-only runner from the pinned shared bundle.
 *
 * Reproducible: <base runner.js> + applyFilterFreshResultToBundle -> <outputRoot>/<sha>/runner.js.
 * The base bundle (cb1264e7) is read, never modified. The output sha is the sha256 of the
 * patched bytes, so the bundle dir name is self-verifying.
 */
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {pin} from './manifest.ts';
import {applyFilterFreshResultToBundle} from './filter-fresh-result-source.ts';

const [basePathArg, outputRootArg] = process.argv.slice(2);
if (!basePathArg || !outputRootArg) throw Error('required <base-runner.js> <outputRoot>');
const basePath = resolve(basePathArg);
const outputRoot = resolve(outputRootArg);
const base = readFileSync(basePath, 'utf8');
const patched = applyFilterFreshResultToBundle(base);
const bytes = Buffer.from(patched, 'utf8');
const sha = createHash('sha256').update(bytes).digest('hex');
const dir = join(outputRoot, sha);
mkdirSync(dir, {recursive: true});
const entry = join(dir, 'runner.js');
if (!existsSync(entry)) writeFileSync(entry, bytes, {flag: 'wx'});
if (pin(entry).sha256 !== sha) throw Error('existing_bundle_content_mismatch');

const attestation = {
  protocol: 'bench-filter-fresh-result-runner-release-v1',
  kind: 'runner',
  taskScope: ['terminal-bench:filter-js-from-html'],
  baseBundlePin: pin(basePath),
  bundlePin: pin(entry),
  transformPin: pin(join(import.meta.dir, 'filter-fresh-result-source.ts')),
  builderPin: pin(import.meta.path),
  patchedSegments: [
    'executeFor: recoverFor guard now requires originalResultsPaths.length > 0',
    'executeFor: absent/empty originalResultsPaths returns await freshCampaignResult(bench,m,c,custody)',
    'injected freshCampaignResult: driver-campaign-outcome.json + provider-native-close.json + cash close + stand/engine closures + task-0.json -> StageResult'
  ],
  unchanged: {
    allOtherModules: 'byte-identical to the base bundle outside the three patched segments',
    financialTransform: 'preserved from the base bundle (not rebuilt; source drift would otherwise import a newer financial transform)'
  },
  whyPatch: 'The current source tree no longer reproduces cb1264e7: financial-policy-source.ts drifted from 55b3022c…(9766B) to d28044a9…(14131B). A source rebuild would change financial behavior beyond the authorized segment.',
  sourceBuildCommandIfFinancialTransformIsPinned: 'bun build-unlimited-release.ts <outputRoot> runner with this transform appended after nonblockingHistorySource',
  modelCalls: 0,
  queueWrites: 0,
  resourcesAcquired: 0
};
const attPath = join(dir, 'filter-fresh-result-release.json');
const text = JSON.stringify(attestation, null, 2) + '\n';
if (!existsSync(attPath)) writeFileSync(attPath, text, {flag: 'wx'});
else if (readFileSync(attPath, 'utf8') !== text) throw Error('existing_filter_release_attestation_conflict');
console.log(JSON.stringify({bundlePin: pin(entry), releasePin: pin(attPath)}));
