"""Explicit source-review policies, never inferred path hints or readiness flags.



All policies still require actual collection and oracle controls. The maps do

not certify dependencies, images, runtime containment or a benchmark score.

"""

from prepare import public



ADDITIONAL_SINGLE_DATA = {

    'civ6-adjacency-optimizer': ('JSON','/output/scenario_3.json'),

    'earthquake-phase-association': ('CSV','/root/results.csv'),

    'llm-prefix-cache-replay': ('JSON','/root/report.json'),

    'exceltable-in-ppt': ('PPTX','/root/results.pptx'),

    'edit-pdf': ('PDF','/root/output/output.pdf'),

    'powerlifting-coef-calc': ('XLSX','/root/data/openipf.xlsx'),

    'bike-rebalance': ('JSON','/root/report.json'),

    'dapt-intrusion-detection': ('CSV','/root/network_stats.csv'),

    'manufacturing-codebook-normalization': ('JSON','/app/output/solution.json'),

    'energy-ac-optimal-power-flow': ('JSON','/root/report.json'),

    'energy-market-pricing': ('JSON','/root/report.json'),

    'energy-unit-commitment': ('JSON','/root/report.json'),

    'grid-dispatch-operator': ('JSON','/root/report.json'),

    'paratransit-routing': ('JSON','/root/report.json'),

    'seismic-phase-picking': ('CSV','/root/results.csv'),

    'azure-bgp-oscillation-route-leak': ('JSON','/app/output/oscillation_report.json'),

    'enterprise-information-search': ('JSON','/root/answer.json'),

    'exoplanet-detection-period': ('TXT','/root/period.txt'),

    'financial-modeling-qa': ('TXT','/root/answer.txt'),

    'flood-risk-analysis': ('CSV','/root/output/flood_results.csv'),

    'gravitational-wave-detection': ('CSV','/root/detection_results.csv'),

    'invoice-fraud-detection': ('JSON','/root/fraud_report.json'),

    'mars-clouds-clustering': ('CSV','/root/pareto_frontier.csv'),

    'pdf-excel-diff': ('JSON','/root/diff_report.json'),

    'protein-expression-analysis': ('XLSX','/root/protein_expression.xlsx'),

    'radar-vital-signs': ('CSV','/root/results.csv'),

    'sales-pivot-analysis': ('XLSX','/root/demographic_analysis.xlsx'),

    'sec-financial-report': ('JSON','/root/answers.json'),

    'software-dependency-audit': ('CSV','/root/security_audit.csv'),

    'tictoc-unnecessary-abort-detection': ('JSON','/root/unnecessary_aborts.json'),

    'travel-planning': ('JSON','/app/output/itinerary.json'),

    'shock-analysis-supply': ('XLSX','/root/test-supply.xlsx'),

    'xlsx-recover-data': ('XLSX','/root/nasa_budget_recovered.xlsx'),

}



def policy(task_id):
    if task_id=='manufacturing-codebook-normalization':
        return {'format':'JSON','output':'/app/output/solution.json','inputs':[],'kind':'file','maximumFiles':1,'maximumBytes':64*1024**2,'approvedDataOnly':True,'origin':'task-scoped opaque JSON transport; original oracle exceeds eight MiB; complete original 16-node cold controls required'}

    if task_id in public.SELECTED:

        return {**public.SELECTED[task_id], 'kind':'file', 'maximumFiles':1,

                'maximumBytes':8*1024**2, 'approvedDataOnly':True,

                'origin':'existing ordinary artifact v2 reviewed data policy'}

    if task_id in ADDITIONAL_SINGLE_DATA:

        format_,output=ADDITIONAL_SINGLE_DATA[task_id]

        return {'format':format_,'output':output,'inputs':[],'kind':'file',

                'maximumFiles':1,'maximumBytes':8*1024**2,'approvedDataOnly':True,

                'origin':'explicit verifier output path/source review; actual cold controls required'}

    if task_id=='weighted-gdp-calc':

        return {'format': 'ordinary multi-file data', 'output': '/root/gdp.xlsx', 'kind': 'files', 'outputs': [{'path': '/root/gdp.xlsx', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/sheet.csv.0', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/sheet.csv.1', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 3, 'maximumBytes': 25165824, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'original weighted GDP XLSX and original sheet-index CSV fallback source review; actual full cold pending'}

    if task_id=='shock-analysis-demand':

        return {'format': 'ordinary multi-file data', 'output': '/root/test_demand.xlsx', 'kind': 'files', 'outputs': [{'path': '/root/test_demand.xlsx', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/sheet.csv.0', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 2, 'maximumBytes': 16777216, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'original XLSX and exact original sheet-index CSV fallback paths; actual full cold controls still required'}

    if task_id=='reserves-at-risk-calc':

        return {'format': 'ordinary multi-file data', 'output': '/root/output/rar_result.xlsx', 'kind': 'files', 'outputs': [{'path': '/root/output/rar_result.xlsx', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/output/sheet.csv.0', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/output/sheet.csv.1', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/output/sheet.csv.2', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/output/sheet.csv.3', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/output/sheet.csv.4', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 6, 'maximumBytes': 50331648, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'original XLSX and exact original sheet-index CSV fallback paths; actual full cold controls still required'}

    if task_id=='paper-anonymizer':

        return {'format': 'ordinary multi-file PDF data', 'output': '/root/redacted/paper1.pdf', 'kind': 'files', 'outputs': [{'path': '/root/redacted/paper1.pdf', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/redacted/paper2.pdf', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/redacted/paper3.pdf', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 3, 'maximumBytes': 25165824, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'original three output PDFs, original fixed private-image pdftotext/pdfinfo parser commands; full actual controls pending'}

    if task_id=='threejs-to-obj':

        return {'format': 'TXT', 'output': '/root/output/object.obj', 'inputs': [], 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608, 'approvedDataOnly': True, 'origin': 'bounded opaque OBJ text; private ground truth generated solely from original immutable scene and original official generator; full cold required'}

    if task_id=='jax-computing-basics':
        return {'format': 'ordinary multi-file numeric NPY data', 'output': '/app/basic_reduce.npy', 'kind': 'files', 'outputs': [{'path': '/app/basic_reduce.npy', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/app/map_square.npy', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/app/grad_logistic.npy', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/app/scan_rnn.npy', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/app/jit_mlp.npy', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 5, 'maximumBytes': 41943040, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'original problem.json five exact outputs; original np.load default allow_pickle=False; independent private NumPy2.4.1; full cold required'}
    if task_id=='video-silence-remover':
        return {'format':'ordinary MP4 and JSON data','output':'/root/compressed_video.mp4','kind':'files','outputs':[{'path':'/root/compressed_video.mp4','kind':'file','maximumFiles':1,'maximumBytes':64*1024**2},{'path':'/root/compression_report.json','kind':'file','maximumFiles':1,'maximumBytes':8*1024**2}],'maximumFiles':2,'maximumBytes':72*1024**2,'maximumSingleFileBytes':64*1024**2,'approvedDataOnly':True,'inputs':[],'origin':'original two output paths; original pristine ffmpeg/ffprobe and scipy private dependencies; full cold required'}

    from multi_policies import policy as multi_policy

    return multi_policy(task_id)



def runner_name(task_id):

    p=policy(task_id)

    if task_id=='civ6-adjacency-optimizer':return 'private_eval_score.py'

    if task_id=='lab-unit-harmonization':return 'private_eval_multi.py'

    if p and p['kind'] in ('files','directory'):return 'private_eval_multi.py'

    return 'private_eval.py' if task_id=='3d-scan-calc' else 'private_eval_v2.py'

