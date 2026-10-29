"""Run from backend: python -m app.agent.demo_plan. Synthetic planning only."""

import asyncio

from app.agent.graph import plan_task
from app.agent.mock_model_provider import MockModelProvider


async def main() -> None:
    provider = MockModelProvider()
    result = await plan_task(
        "task-demo-b21",
        "Summarize my project report and prepare an email to my teammate.",
        provider,
    )
    print("SIMULATED PLANNING — NO ACTIONS EXECUTED")
    print(f"Planning status: {result.task_state.status.value}")
    print(f"Planning outcome: {result.outcome.value}")
    print(f"Configured model tier (mock): {result.model_tier.value}")
    if result.structured_plan is not None:
        print("Proposed identifiers: " + ", ".join(result.structured_plan.proposed_actions))
    print(f"Mock inference calls: {len(provider.requests)}; tools executed: 0")


if __name__ == "__main__":
    asyncio.run(main())
