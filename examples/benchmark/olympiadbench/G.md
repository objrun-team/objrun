# OlympiadBench Physics EN Text 236

Uses all 236 questions from `OE_TO_physics_en_COMP` in Hothan/OlympiadBench revision `91184b52131e7fc9455fef848035173aea8cc01a`. Public inputs retain the official English prompt, nonempty context, and question; gold answers, solutions, and errors are not published.

G is present → correct. present checks only for a nonempty candidate. correct follows inference/judge.py and MathJudger from OpenBMB/OlympiadBench commit `ba5b26a7e2849940b598a9159c1190daa2b9175f`, including official answer extraction, argument order, final_answer[0], and per-question tolerances. There is no additional mandatory boxed-format gate, SciBench numerical tolerance, or LLM grading.

Feedback contains only value and note; the correctness node's note is empty. Format guidance contains no gold answer, error magnitude, component result, or solution. Grading-process exceptions remain unknown rather than being counted as wrong answers.

Native c5, 600 seconds, four branches, and 12 units each for ask/act; c5 uses native attempt counting. Only submit, verify, task_tree, and node_load are exposed. Only an actual submit counts as the final candidate; candidates are not recovered from verify or reasoning_content.
