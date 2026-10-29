# Component hierarchy and design acceptance

## Shell
`AppShell`, `SideNav`, `MobileDrawer`, `TopBar`, `LocalModeBanner`, `SessionBadge`, `ConnectionStatus`.

## Tasks
`TaskComposer`, `TaskTable`, `TaskSummary`, `PlanningPanel`, `DecisionRail`, `TaskStatusBadge`, `PlanProvenanceBadge`.

## Human control
`ApprovalQueue`, `ApprovalDetail`, `ApprovalDecisionDialog`, `ApprovalExpiry`, `ConsentScopeView`, `WorkflowStatePanel`.

## Evidence
`AuditTimeline`, `AuditEvent`, `OperationHistory`, `OperationDetail`, `CopyReference`, `CatalogMetadataTable`.

## Foundations
`ErrorPanel`, `EmptyState`, `LoadingSkeleton`, `InlineFieldError`, `ConfirmDialog`, `Toast`, `Pagination`, `StatusPill`, `Timestamp`, `ActionButton`.

## Component acceptance
- Each action wired to real generated API operation; no fake hardcoded responses in connected mode.
- Each component has loading, disabled, empty, success and failure behavior.
- Support keyboard and screen readers; dialogs trap focus and restore it.
- Typed props derived from schema types; no `any` in API and workflow core.
- Avoid duplicated business logic in React components: centralize status mapping and API client.
- No claims of protected execution unless a trusted backend result confirms it.
