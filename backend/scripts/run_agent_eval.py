"""运行固定 Agent 任务集并把真实模型结果写入本地评测报告。"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.agents.eval import load_agent_task_cases, run_agent_task_eval


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATASET = _BACKEND_ROOT / "tests" / "eval_data" / "agent_tasks_v1.json"
_DEFAULT_REPORT_DIR = _BACKEND_ROOT / "reports"


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 NutriLens Agent 固定任务集评测")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--repeats", type=int, default=3, help="每条任务的重复执行次数")
    parser.add_argument("--case-limit", type=int, help="仅跑前 N 条，用于冒烟验证")
    parser.add_argument("--report-dir", type=Path, default=_DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    dataset = load_agent_task_cases(args.dataset)
    report = run_agent_task_eval(
        dataset, repeats=args.repeats, case_limit=args.case_limit
    )
    args.report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.report_dir / f"agent-task-eval-{timestamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"报告：{output}")
    print(f"任务完成率：{report['task_completion_rate']:.2%}")
    print(f"工具调用准确率：{report['tool_call_accuracy']:.2%}")
    print(f"样例：{report['case_count']} 条 x {report['repeats']} 次 = {report['episodes']} episodes")


if __name__ == "__main__":
    main()
