"""Shared limits for research rounds; model reservations remain in BudgetGovernor."""
def stop_reason(task, budget, completed, reserve=0):
    usage = budget.snapshot()
    if budget.stop_requested():
        return "用户已停止研究"
    if budget.remaining_time() <= 0:
        return "运行时间已用完"
    if usage["cpu_seconds"] >= task.budget.max_cpu_seconds:
        return "CPU 预算已用完"
    if completed >= task.max_delegations:
        return "已达到研究轮数上限"
    if usage["experiment_count"] + reserve >= task.budget.max_experiments:
        return "可用于候选的实验额度已用完" if reserve else "实验额度已用完"
    return ""
