"""Explicit ordinary multi-output plans. Actual original controls are mandatory."""
FILES = {
    'pddl-airport-planning': ['/app/task01.txt', '/app/task02.txt'],
    'pddl-tpp-planning': ['/app/task01.txt', '/app/task02.txt'],

    'dynamic-object-aware-egomotion': ['/root/pred_instructions.json','/root/pred_dyn_masks.npz'],
    'hvac-control': ['/root/calibration_log.json','/root/estimated_params.json','/root/tuned_gains.json','/root/control_log.json','/root/metrics.json'],
    'r2r-mpc-control': ['/root/controller_params.json','/root/control_log.json','/root/metrics.json'],
    'manufacturing-equipment-maintenance': ['/app/output/q01.json','/app/output/q02.json','/app/output/q03.json','/app/output/q04.json','/app/output/q05.json'],
    'manufacturing-fjsp-optimization': ['/app/output/solution.json','/app/output/schedule.csv'],
    'lake-warming-attribution': ['/root/output/dominant_factor.csv','/root/output/trend_result.csv'],
    'dialogue-parser': ['/app/dialogue.json','/app/dialogue.dot','/root/dialogue.json','/root/dialogue.dot'],
    'quantum-numerical-simulation': ['/root/1.csv','/root/2.csv','/root/3.csv','/root/4.csv','/app/1.csv','/app/2.csv','/app/3.csv','/app/4.csv'],
}
DIRECTORIES = {
    'ada-bathroom-plan-repair': '/root/output',
    'drone-planning-control': '/root/results',
    'exam-block-sequencing': '/root/output',
    'organize-messy-files': '/root/papers',
    'threejs-structure-parser': '/root/output',
}

def policy(task_id):
    if task_id in FILES:
        paths=FILES[task_id];kind='files';outputs=[{'path':p,'kind':'file','maximumFiles':1,'maximumBytes':8*1024**2} for p in paths]
    elif task_id in DIRECTORIES:
        paths=[DIRECTORIES[task_id]];kind='directory';outputs=[{'path':paths[0],'kind':'directory','maximumFiles':1024,'maximumBytes':128*1024**2}]
    else:return None
    return {'format':'ordinary multi-file data','output':paths[0],'kind':kind,'outputs':outputs,
        'maximumFiles':sum(o['maximumFiles'] for o in outputs),'maximumBytes':sum(o['maximumBytes'] for o in outputs),
        'maximumSingleFileBytes':8*1024**2,'approvedDataOnly':True,'inputs':[],
        'origin':'explicit original verifier output paths reviewed; no candidate imports/executables; actual collection and oracle controls required'}
