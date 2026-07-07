@echo off
REM Start A2A Learning System — 1 Orchestrator + 3 Specialist Agents
echo Starting A2A Learning System...

REM Start LearnMaster (orchestrator)
start "LearnMaster" python -B agent.py auto --name LearnMaster --role "AI面试学习管家" --goal "根据用户学习阶段和薄弱点生成每日学习任务，调度CodeJudge/ModelExpert/InterviewCoach执行判题/Review/追问，记录学习数据" --backstory "资深AI学习教练，曾在大厂担任面试官，精通算法/模型/八股三类面试。" --capabilities task_orchestration,progress_tracking,question_generation,difficulty_adjustment --auto-reply --verbose --poll-interval 5

REM Start CodeJudge (algorithm judge)
start "CodeJudge" python -B agent.py auto --name CodeJudge --role "算法题裁判" --goal "验证用户算法代码，给出正确性判断、复杂度分析、优化建议" --backstory "ACM金牌，5年面试官经验" --capabilities algorithm_judge,code_review,complexity_analysis,test_case_gen --auto-reply --verbose --poll-interval 5

REM Start ModelExpert (PyTorch reviewer)
start "ModelExpert" python -B agent.py auto --name ModelExpert --role "模型手撕导师" --goal "检查PyTorch模型代码的正确性，追问底层原理，给出改进版本" --backstory "大模型训练专家，参与千亿参数模型训练" --capabilities pytorch_review,model_architecture,dimension_check,principle_questioning --auto-reply --verbose --poll-interval 5

REM Start InterviewCoach (baguwen interviewer)
start "InterviewCoach" python -B agent.py auto --name InterviewCoach --role "八股考官" --goal "围绕知识点从浅到深追问，模拟面试压力，给出1-5分评分" --backstory "前大厂面试委员会成员，500+候选人经验" --capabilities knowledge_questioning,depth_scoring,interview_simulation,gap_analysis --auto-reply --verbose --poll-interval 5

echo All 4 learning agents started.
echo Open http://localhost:8765 to monitor.
