export const scenarios = {
  document: { title: 'Summarize the synthetic project report', action: 'files.read', resource: 'Synthetic project report', resourceRef: 'demo-resource-report', purpose: 'Summarize synthetic report', recipient: null },
  email: { title: 'Review a synthetic summary email', action: 'email.send', resource: 'Synthetic summary metadata', resourceRef: 'demo-resource-summary', purpose: 'Share synthetic summary', recipient: 'teammate@example.test' },
  denied: { title: 'Try sharing a restricted original', action: 'email.send', resource: 'Restricted synthetic original', resourceRef: 'demo-resource-original', purpose: 'Share original attachment', recipient: 'teammate@example.test' }
} as const;
export type Scenario = keyof typeof scenarios;
export type Phase = 'EMPTY' | 'CREATED' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'REVOKED' | 'EXPIRED' | 'CANCELLED' | 'DENIED' | 'SAFE_STOPPED' | 'UNKNOWN';
export type Event = { ref: string; step: number; category: 'Task' | 'Planning' | 'Authorization' | 'Approval' | 'Workflow' | 'Operation'; title: string; detail: string };
export type State = { phase: Phase; task: { ref: string; title: string; scenario: Scenario } | null; events: Event[] };
export type Action = { type: 'CREATE'; title: string; scenario: Scenario } | { type: 'PLAN' | 'APPROVE' | 'REJECT' | 'REVOKE' | 'EXPIRE' | 'CANCEL' | 'CONTINUE' | 'UNCERTAIN' | 'RESET' };
export const initialState = (): State => ({ phase: 'EMPTY', task: null, events: [] });
export const can = (state: State, action: Action['type']) => ({
  CREATE: ['EMPTY'], PLAN: ['CREATED'], APPROVE: ['PENDING'], REJECT: ['PENDING'],
  REVOKE: ['PENDING', 'APPROVED'], EXPIRE: ['PENDING', 'APPROVED'],
  CANCEL: ['CREATED', 'PENDING', 'APPROVED'], CONTINUE: ['APPROVED'], UNCERTAIN: ['APPROVED'],
  RESET: ['EMPTY', 'CREATED', 'PENDING', 'APPROVED', 'REJECTED', 'REVOKED', 'EXPIRED', 'CANCELLED', 'DENIED', 'SAFE_STOPPED', 'UNKNOWN']
} as Record<Action['type'], Phase[]>)[action].includes(state.phase);
export function transition(state: State, action: Action): State {
  if (!can(state, action.type)) throw new Error(`Unavailable transition: ${state.phase} → ${action.type}`);
  if (action.type === 'RESET') return initialState();
  const next: State = { ...state, events: [...state.events] };
  const add = (category: Event['category'], title: string, detail: string) => {
    const step = next.events.length + 1;
    next.events.push({ ref: `demo-event-${String(step).padStart(3, '0')}`, step, category, title, detail });
  };
  switch (action.type) {
    case 'CREATE': {
      const title = action.title.trim();
      if (title.length < 3 || title.length > 100 || !Object.hasOwn(scenarios, action.scenario)) throw new Error('Use a sample title between 3 and 100 characters and an available scenario.');
      next.task = { ref: 'demo-task-001', title, scenario: action.scenario }; next.phase = 'CREATED';
      add('Task', 'Task created', 'Synthetic request recorded in this browser tab only.'); break;
    }
    case 'PLAN':
      add('Planning', 'Simulated plan generated', 'Fixed scenario rules, not live AI inference. No document content is loaded.');
      if (next.task?.scenario === 'denied') {
        next.phase = 'DENIED'; add('Authorization', 'Authorization denied', 'Synthetic rule denies sharing restricted originals. No approval or continuation is available.');
      } else {
        next.phase = 'PENDING'; add('Authorization', 'Approval required', 'Simulated authorization binds this task, operation, resource, action and purpose.');
        add('Approval', 'Human review requested', 'Synthetic 10-minute window. Time advances only through Simulate expiry; no real permission exists.');
      }
      add('Operation', 'Operation not executed', 'demo-operation-001 is a synthetic record. External effect: none.'); break;
    case 'APPROVE': next.phase = 'APPROVED'; add('Approval', 'Approval recorded', 'Synthetic scoped permission only. Continuation still requires a separate action.'); break;
    case 'REJECT': next.phase = 'REJECTED'; add('Approval', 'Approval rejected', 'Synthetic request denied. No continuation or external effect.'); break;
    case 'REVOKE': next.phase = 'REVOKED'; add('Approval', 'Permission revoked', 'Synthetic future authority removed. Nothing was executed or undone.'); break;
    case 'EXPIRE': next.phase = 'EXPIRED'; add('Approval', 'Expiry simulated', 'Demo clock advanced beyond the synthetic review window. This is not observed backend expiry.'); break;
    case 'CANCEL': next.phase = 'CANCELLED'; add('Workflow', 'Task cancelled', 'Synthetic future progression stopped. No external action occurred.'); break;
    case 'CONTINUE': next.phase = 'SAFE_STOPPED'; add('Workflow', 'SAFE_STOPPED', 'Explicit synthetic continuation reached its boundary. NOT_EXECUTED; no protected operation exists.'); break;
    case 'UNCERTAIN': next.phase = 'UNKNOWN'; add('Operation', 'UNKNOWN example', 'Simulated uncertainty requires reconciliation. No automatic retry; no real action was attempted.'); break;
  }
  return next;
}
export function records(state: State) {
  if (!state.task) return null;
  const planned = state.events.some(event => event.category === 'Planning');
  return { provenance: 'SYNTHETIC_BROWSER_DEMO', task_ref: state.task.ref, operation_ref: planned ? 'demo-operation-001' : null,
    approval_ref: planned && state.task.scenario !== 'denied' ? 'demo-approval-001' : null,
    ...scenarios[state.task.scenario], title: state.task.title, authorization_decision: !planned ? 'NOT_EVALUATED' : state.task.scenario === 'denied' ? 'DENY' : 'APPROVAL_REQUIRED', workflow_status: state.phase,
    execution_status: state.phase === 'UNKNOWN' ? 'UNKNOWN_EXAMPLE' : 'NOT_EXECUTED', external_effect: 'NONE', events: state.events.length };
}
