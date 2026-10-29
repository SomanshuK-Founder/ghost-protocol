"""Offline B2.2a demo: python -m app.agent.demo_execute from backend."""

import asyncio

from app.agent.execution_contracts import ActionBinding, AgentExecutionResult, ExecutionOutcome
from app.agent.gateway_protocol import ToolResponse
from app.agent.mock_gateway import MockToolGateway
from app.agent.mock_model_provider import MockModelProvider
from app.agent.orchestration import GatewayOrchestrator, build_tool_request


async def run_scenarios() -> tuple[AgentExecutionResult, ...]:
    results = []
    cases = (
        (
            "task-b22a-approved",
            "Prepare a project summary and draft an email.",
            ["files.read", "email.draft"],
            [
                {"resource_id": "synthetic-report-001"},
                {
                    "recipient": "teammate@example.test",
                    "subject": "Synthetic summary",
                    "body": "Explicit synthetic summary fixture; no document was read.",
                },
            ],
            "ALLOW",
            "SUCCEEDED",
            "EXPLICIT_DEMO_FIXTURE",
            None,
        ),
        (
            "task-b22a-denied",
            "Send the private tax document to an unauthorized recipient.",
            ["email.send"],
            [
                {
                    "recipient": "unauthorized@example.test",
                    "subject": "Synthetic share request",
                    "body": "Synthetic fixture only.",
                    "attachment_resource_ids": ["synthetic-tax-001"],
                }
            ],
            "DENY",
            "NOT_EXECUTED",
            "RECIPIENT_NOT_AUTHORIZED",
            None,
        ),
        (
            "task-b22a-pending",
            "Share the selected document with my teammate.",
            ["email.send"],
            [
                {
                    "recipient": "teammate@example.test",
                    "subject": "Synthetic document share",
                    "body": "Synthetic fixture only.",
                    "attachment_resource_ids": ["synthetic-selected-doc-001"],
                }
            ],
            "APPROVAL_REQUIRED",
            "NOT_EXECUTED",
            "NO_MATCHING_CONSENT",
            "approval-demo-b22a",
        ),
    )
    for reference, user_request, actions, arguments, decision, status, reason, approval in cases:
        bindings = tuple(
            ActionBinding(
                task_ref=reference, action=action, purpose="synthetic_demo", arguments=value
            )
            for action, value in zip(actions, arguments, strict=True)
        )
        fixtures = []
        for index, binding in enumerate(bindings):
            request = build_tool_request(reference, index, binding.action, binding)
            fixtures.append(
                (
                    request,
                    ToolResponse(
                        request_id=request.request_id,
                        decision=decision,
                        execution_status=status,
                        reason_code=reason,
                        approval_ref=approval,
                        result={"synthetic_result_ref": f"demo-result-{index}"}
                        if status == "SUCCEEDED"
                        else None,
                    ),
                )
            )
        model = MockModelProvider(
            output={
                "task_ref": reference,
                "intent": "summarize_and_prepare_email",
                "proposed_actions": actions,
                "requires_external_action": True,
                "clarification_required": False,
            }
        )
        service = GatewayOrchestrator(model, MockToolGateway(fixtures))
        results.append(await service.execute_task(reference, user_request, bindings))
    assert tuple(result.execution_outcome for result in results) == (
        ExecutionOutcome.ALL_ACTIONS_SUCCEEDED,
        ExecutionOutcome.DENIED,
        ExecutionOutcome.APPROVAL_REQUIRED,
    )
    return tuple(results)


async def main() -> None:
    print("SIMULATED GATEWAY EXECUTION — NO REAL SIDE EFFECTS")
    for label, result in zip(("A", "B", "C"), await run_scenarios(), strict=True):
        print(
            f"Scenario {label}: {result.execution_outcome.value}; "
            f"task status={result.task_state.status.value}; "
            f"simulated successes={result.completed_action_count}/{result.total_action_count}"
        )
        if result.action_results:
            print(
                f"  Last gateway outcome: {result.action_results[-1].execution_status.value}; "
                f"reason={result.action_results[-1].reason_code}"
            )
    print("No real files read, emails sent, or approvals granted. No approval resume performed.")


if __name__ == "__main__":
    asyncio.run(main())
