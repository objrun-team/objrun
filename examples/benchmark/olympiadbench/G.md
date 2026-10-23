# OlympiadBench Physics EN Text 236

固定 Hothan/OlympiadBench revision `91184b52131e7fc9455fef848035173aea8cc01a` 的 `OE_TO_physics_en_COMP`，236 道完整题。公开输入保留官方英文提示、非空 context 和 question；金标、solution 和 error 不发布。

G 为 present → correct。present 只检查非空候选；correct 按 OpenBMB/OlympiadBench commit `ba5b26a7e2849940b598a9159c1190daa2b9175f` 的 inference/judge.py 和 MathJudger 判分，包含官方答案提取、参数顺序、final_answer[0] 和逐题容差。无额外 boxed 硬门槛；不使用 SciBench 数值容差或 LLM 判卷。

反馈仅有 value、note；正确性节点 note 为空。格式说明不包含金标、误差、分量结果或解答。评分进程异常保持 unknown，不作为错误答案。

原生 c5、600 秒、4 分支、ask/act 各 12 units；c5 按原生尝试计数。只开放 submit、verify、task_tree、node_load。最终只认实际 submit，不从 verify 或 reasoning_content 补取候选。
