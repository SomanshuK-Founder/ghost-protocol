import { h, button, badge, heading, icon, showDialog, trapFocus } from './dom.js';
import { rail, inspect } from './rail.js';
import { initialState, transition, scenarios, can, records } from './state.js';
import type { State, Action, Scenario } from './state.js';

let state: State = initialState();
const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('Demo root is missing');
const appRoot = root;
const routes = { overview: 'Overview', workspace: 'Task workspace', approvals: 'Approval Center', operations: 'Operation records', audit: 'Audit explorer', documents: 'Document catalog', about: 'About this demo' } as const;
type Route = keyof typeof routes;
const currentRoute = (): Route => { const value = location.hash.slice(1); return Object.hasOwn(routes, value) ? value as Route : 'overview'; };
const navigate = (route: Route) => { if (currentRoute() === route) render(); else location.hash = route; };
const live = h('div', { role: 'status', 'aria-live': 'polite', class: 'sr-only' });
document.body.append(live);
const phaseTone = () => state.phase === 'SAFE_STOPPED' || state.phase === 'APPROVED' ? 'success' : state.phase === 'PENDING' ? 'amber' : ['DENIED', 'REJECTED', 'REVOKED', 'CANCELLED', 'EXPIRED', 'UNKNOWN'].includes(state.phase) ? 'danger' : 'neutral';
function dispatch(action: Action, route?: Route) {
  try {
    state = transition(state, action); render(); if (route) navigate(route);
    live.textContent = action.type === 'RESET' ? 'Synthetic demo reset. All in-memory records cleared.' : `${state.events.at(-1)?.title}. Synthetic data only.`;
  } catch (error) { live.textContent = error instanceof Error ? error.message : 'That synthetic transition is unavailable.'; }
}
function confirmAction(type: Exclude<Action['type'], 'CREATE' | 'PLAN'>, label: string, detail: string, danger = false) {
  showDialog(label + '?', h('div', { class: 'record-body' }, h('p', {}, detail), scope()), { label, run: () => dispatch({ type }), danger });
}
function action(type: Exclude<Action['type'], 'CREATE' | 'PLAN'>, label: string, detail: string, variant = 'secondary') {
  return button(label, () => confirmAction(type, label, detail, variant === 'danger'), variant, !can(state, type));
}
function navigation(close?: () => void) {
  const nav = h('nav', { 'aria-label': 'Main navigation' });
  for (const [key, label] of Object.entries(routes)) {
    const link = h('a', { href: `#${key}`, class: `nav-item ${currentRoute() === key ? 'active' : ''}`, ...(currentRoute() === key ? { 'aria-current': 'page' } : {}) }, icon(key), h('span', {}, label));
    if (close) link.addEventListener('click', close); nav.append(link);
  }
  return nav;
}
function scope() {
  const record = records(state);
  return record ? h('dl', { class: 'scope' }, ...[
    ['Requested action', record.action], ['Exact resource', record.resource], ['Purpose', record.purpose],
    ['Recipient', record.recipient ?? 'Not applicable'], ['Review window', '10 synthetic minutes · use Simulate expiry to advance time']
  ].flatMap(([name, value]) => [h('dt', {}, name), h('dd', {}, value)]), h('dt', {}, 'Binding'), h('dd', {}, h('details', {}, h('summary', {}, 'Inspect synthetic references'), h('code', {}, `${record.task_ref} / ${record.operation_ref ?? 'not planned'} / ${record.approval_ref ?? 'not requested'}`)))) : h('p', { class: 'muted' }, 'No task exists.');
}
function empty(title: string, detail: string) { return h('section', { class: 'empty panel' }, icon('workspace'), h('h2', {}, title), h('p', { class: 'muted' }, detail), state.task ? button('Open task workspace →', () => navigate('workspace'), 'primary') : button('Create sample task', () => createDialog(), 'primary')); }
function createDialog() {
  const title = h('input', { id: 'task-title', name: 'title', required: true, minlength: '3', maxlength: '100', 'aria-describedby': 'title-help' });
  title.value = scenarios.document.title;
  const select = h('select', { id: 'scenario', name: 'scenario' }, ...Object.entries(scenarios).map(([key, value]) => h('option', { value: key }, value.title)));
  select.addEventListener('change', () => { title.value = scenarios[select.value as Scenario].title; });
  const error = h('p', { role: 'alert', class: 'error' });
  const form = h('form', {}, h('label', { for: 'task-title' }, 'Sample task title'), title, h('p', { id: 'title-help', class: 'muted' }, '3–100 characters. Use sample text only; nothing is saved or sent.'), h('label', { for: 'scenario' }, 'Synthetic scenario'), select,
    h('p', { class: 'callout' }, 'Plans use fixed rules. No live AI, document contents or external operation.'), error,
    h('div', { class: 'actions' }, button('Go back', () => dialog.close(), 'secondary'), h('button', { type: 'submit', class: 'button primary' }, 'Create sample task')));
  const trigger = document.activeElement as HTMLElement | null;
  const dialog = h('dialog', { class: 'modal', 'aria-labelledby': 'create-title' }, h('p', { class: 'eyebrow' }, 'SYNTHETIC TASK · BROWSER MEMORY ONLY'), h('h2', { id: 'create-title' }, 'Give your agent a boundary.'), form);
  form.addEventListener('submit', event => {
    event.preventDefault();
    try {
      const next = transition(state, { type: 'CREATE', title: title.value, scenario: select.value as Scenario });
      dialog.close(); state = next; navigate('workspace'); render(); live.textContent = 'Synthetic task created. Generate a simulated plan when ready.';
    } catch (reason) { error.textContent = reason instanceof Error ? reason.message : 'Check the sample task.'; }
  });
  dialog.addEventListener('close', () => { dialog.remove(); if (trigger?.isConnected) trigger.focus(); });
  dialog.addEventListener('keydown', trapFocus);
  document.body.append(dialog); dialog.showModal(); title.focus();
}
function taskCard() {
  return h('section', { class: 'panel focus-card' }, h('p', { class: 'eyebrow' }, 'IN FOCUS'), badge(state.phase.replaceAll('_', ' '), phaseTone()),
    h('h2', {}, state.task?.title ?? 'No task yet'), h('p', { class: 'muted' }, 'A synthetic workflow you control, one decision at a time.'),
    h('div', { class: 'facts' }, h('div', {}, h('span', { class: 'muted' }, 'Planning source'), h('strong', {}, 'Deterministic simulation')), h('div', {}, h('span', { class: 'muted' }, 'External effect'), h('strong', {}, 'None'))),
    button('Open task workspace →', () => navigate('workspace'), 'text-button'));
}
function overview() {
  const page = h('div', {}, heading('YOUR PERSONAL AI CONTROL ROOM', 'Your agent. Your call.', 'Explore the decisions. Keep the authority. Every interaction here is synthetic.'));
  if (!state.task) {
    page.append(h('section', { class: 'intro panel' }, h('div', {}, badge('A HANDS-ON SYNTHETIC WALKTHROUGH', 'cyan'), h('h2', {}, 'See where an agent stops.\nDecide what happens next.'), h('p', { class: 'muted' }, 'Create a sample task, inspect its scope and make the human decision. Approval is permission—not execution.'), button('Create sample task', () => createDialog(), 'primary')),
      h('div', { class: 'intro-steps' }, ...[['01', 'Propose', 'A fixed, simulated plan.'], ['02', 'Authorize', 'An exact scope, reviewed by you.'], ['03', 'Continue safely', 'SAFE_STOPPED. No execution.']].map(([number, title, detail]) => h('div', {}, h('span', { class: 'step-number' }, number), h('div', {}, h('h3', {}, title), h('p', { class: 'muted' }, detail)))))));
  } else {
    page.append(h('div', { class: 'overview-grid' }, taskCard(), h('section', { class: 'panel checkpoint' }, h('p', { class: 'eyebrow amber' }, 'HUMAN CHECKPOINT'), h('div', { class: 'count' }, state.phase === 'PENDING' ? '1' : '0', h('span', {}, 'awaiting\nyour review')), h('p', { class: 'muted' }, 'Count derived from this tab’s synthetic task. No real approval or permission is issued.'), button(state.phase === 'PENDING' ? 'Inspect pending request →' : 'Open Approval Center →', () => navigate('approvals'), 'secondary'))), rail(state));
  }
  page.append(h('section', { class: 'section-heading lower-note' }, h('div', {}, h('p', { class: 'eyebrow' }, 'PERSONAL AI. HUMAN AUTHORITY.'), h('h2', {}, 'The boundary is the product.')), button('What is real, and what is simulated?', () => navigate('about'), 'text-button')));
  return page;
}
function workspace() {
  const page = h('div', {}, heading('TASK WORKSPACE', state.task?.title ?? 'Start with an intention.', 'Synthetic planning and human-controlled progression. No live inference or protected execution.'));
  if (!state.task) { page.append(empty('Your workspace is ready.', 'Create a sample task to explore planning, authorization and safe continuation.')); return page; }
  page.append(h('div', { class: 'workspace-status' }, badge(state.phase, phaseTone()), badge('FIXED SIMULATION', 'cyan'), button('Inspect task record', () => inspect(state, 'Synthetic task record'), 'text-button')), rail(state));
  const controls = h('section', { class: 'panel' }, h('p', { class: 'eyebrow' }, 'NEXT HUMAN ACTION'), h('h2', {}, state.phase === 'CREATED' ? 'Plan within the boundary.' : state.phase === 'PENDING' ? 'A decision is waiting.' : state.phase === 'APPROVED' ? 'Permission recorded. Still paused.' : state.phase === 'SAFE_STOPPED' ? 'Continued safely. Nothing executed.' : state.phase === 'UNKNOWN' ? 'Uncertain example. Stop and inspect.' : 'The workflow is stopped.'), h('p', { class: 'muted' }, state.phase === 'SAFE_STOPPED' ? 'This synthetic continuation reached its safe boundary. The operation remains NOT_EXECUTED.' : state.phase === 'UNKNOWN' ? 'Reconciliation required in a real system. This example makes no real attempt and offers no resend.' : 'Only the controls available for the current synthetic state can advance it.'));
  const buttons = h('div', { class: 'actions' });
  if (state.phase === 'CREATED') buttons.append(button('Generate simulated plan', () => dispatch({ type: 'PLAN' }), 'primary'));
  if (state.phase === 'PENDING') buttons.append(button('Review pending approval', () => navigate('approvals'), 'primary'));
  if (state.phase === 'APPROVED') buttons.append(action('CONTINUE', 'Continue synthetic workflow', 'Explicitly advance this approved synthetic workflow to SAFE_STOPPED. No protected read, email or external operation is performed.', 'primary'));
  if (can(state, 'CANCEL')) buttons.append(action('CANCEL', 'Cancel task', 'Stop future synthetic progression. No operation has been executed.'));
  if (['SAFE_STOPPED', 'UNKNOWN', 'REJECTED', 'REVOKED', 'EXPIRED', 'CANCELLED', 'DENIED'].includes(state.phase)) buttons.append(button('Inspect audit evidence →', () => navigate('audit'), 'primary'));
  controls.append(buttons); page.append(controls);
  if (state.phase === 'PENDING' || state.phase === 'APPROVED') page.append(h('details', { class: 'panel examples' }, h('summary', {}, 'Explore stopping and uncertainty examples'), h('p', { class: 'muted' }, 'These controls deliberately simulate alternate states, not failures observed from a backend.'), h('div', { class: 'actions' }, action('EXPIRE', 'Simulate expiry', 'Advance the synthetic clock beyond the 10-minute review window. This is a labelled expiry example.'), action('REVOKE', 'Revoke permission', 'Remove this synthetic request’s future authority. No operation was performed.', 'danger'), action('UNCERTAIN', 'Simulate UNKNOWN', 'Show a synthetic uncertain outcome. No real operation is attempted and no retry will be available.', 'danger'))));
  return page;
}
function approvals() {
  const page = h('div', {}, heading('HUMAN AUTHORITY', 'Approval Center', 'Inspect the exact action and scope. Your synthetic decision never triggers execution.'));
  if (!records(state)?.approval_ref) { page.append(empty('No approval requested.', 'A simulated plan may request human review. A denied original-sharing scenario cannot be approved.')); return page; }
  const card = h('section', { class: 'panel approval-card' }, h('div', { class: 'section-heading' }, h('h2', {}, state.task!.title), badge(state.phase, phaseTone())), scope(), h('p', { class: 'callout' }, 'Synthetic scoped permission only. Approving does not continue the workflow, read a document or submit an email.'));
  card.append(h('div', { class: 'actions' }, action('APPROVE', 'Approve request', 'Record synthetic scoped permission only. This does not continue the workflow, read a document or submit an email.', 'primary'), action('REJECT', 'Reject request', 'Reject this exact synthetic approval request and block continuation.', 'danger'), action('REVOKE', 'Revoke permission', 'Remove this synthetic request’s future authority. Nothing has executed.')));
  if (state.phase === 'APPROVED') card.append(h('p', { class: 'success' }, 'Approved, still paused. Continue explicitly from the task workspace.'), button('Open continuation controls →', () => navigate('workspace'), 'text-button'));
  card.append(h('details', {}, h('summary', {}, 'Technical metadata · synthetic only'), h('pre', {}, JSON.stringify(records(state), null, 2))));
  page.append(card); return page;
}
function operations() {
  const page = h('div', {}, heading('OPERATION RECORDS', 'Permission is not execution.', 'Every record on this page is synthetic. No external dispatch mechanism is present.'));
  const record = records(state);
  if (!record?.operation_ref) { page.append(empty('No operation proposed.', 'Generate a simulated plan to inspect its operation metadata.')); return page; }
  page.append(h('section', { class: 'panel' }, h('div', { class: 'section-heading' }, h('h2', {}, 'Synthetic operation'), badge(record.execution_status, state.phase === 'UNKNOWN' ? 'danger' : 'cyan')), scope(), h('div', { class: 'facts' }, h('div', {}, h('span', { class: 'muted' }, 'Provenance'), h('strong', {}, 'Synthetic browser state')), h('div', {}, h('span', { class: 'muted' }, 'External effect'), h('strong', {}, 'NONE'))), button('Inspect operation record', () => inspect(state, 'Synthetic operation record'), 'secondary'))); return page;
}
function audit() {
  const select = h('select', { id: 'category', 'aria-label': 'Filter event category' }, ...['All categories', 'Task', 'Planning', 'Authorization', 'Approval', 'Workflow', 'Operation'].map(value => h('option', { value }, value)));
  const list = h('ol', { class: 'timeline' });
  const fill = () => {
    const events = state.events.filter(event => select.value === 'All categories' || event.category === select.value);
    list.replaceChildren(...events.map(event => h('li', {}, h('div', { class: 'timeline-step' }, String(event.step).padStart(2, '0')), h('div', { class: 'timeline-content' }, h('div', { class: 'section-heading' }, h('h2', {}, event.title), badge(event.category)), h('p', { class: 'muted' }, event.detail), h('div', { class: 'actions' }, h('code', {}, event.ref), button('Inspect event', () => inspect(state, event.title, event), 'text-button'))))));
    if (!events.length) list.append(h('li', {}, h('p', { class: 'muted' }, 'No synthetic events in this category.')));
  };
  select.addEventListener('change', fill); fill();
  return h('div', {}, heading('SYNTHETIC EVIDENCE', 'Audit explorer', 'Chronological browser-memory events. Step numbers are sequence, not backend timestamps.'), h('div', { class: 'filter-row' }, h('label', { for: 'category' }, 'Event category'), select, badge(`${state.events.length} synthetic events`, 'cyan')), state.events.length ? list : empty('The timeline starts with you.', 'Create a task to begin recording synthetic decisions. Reset or reload clears this timeline.'));
}
function documents() {
  return h('div', {}, heading('METADATA ONLY', 'Synthetic document catalog', 'Fixed demonstration resources. No raw document contents, filesystem paths or real ownership are present.'), h('div', { class: 'catalog' }, ...(['document', 'denied'] as Scenario[]).map(key => h('section', { class: 'panel' }, icon('documents'), h('h2', {}, scenarios[key].resource), badge(key === 'denied' ? 'Restricted example' : 'Review required', key === 'denied' ? 'danger' : 'amber'), h('dl', { class: 'scope' }, h('dt', {}, 'Type'), h('dd', {}, 'Synthetic metadata'), h('dt', {}, 'Availability'), h('dd', {}, 'Demo only · no contents'), h('dt', {}, 'Reference'), h('dd', {}, h('code', {}, scenarios[key].resourceRef)))))));
}
function about() {
  return h('div', {}, heading('CAPABILITIES & BOUNDARIES', 'Honest by design.', 'A public walkthrough of the control model, separate from the private local application.'), h('section', { class: 'panel about' }, ...[
    ['This public experience', 'Deterministic, simulated and self-contained. No live AI inference, backend connection, real identity, durable audit database or protected execution. State exists only in memory and clears on reload/reset.'],
    ['The private local application', 'Has verified real FastAPI, LangGraph, SQLite, session, CSRF, authorization, approval and audit integration. Its accepted browser workflow uses simulated planning and genuine SAFE_STOPPED records. It is not exposed by this demo.'],
    ['Nebius Token Factory + NVIDIA Nemotron', 'Live Nemotron planning was validated separately in earlier isolated model probes. This public static demo does not call Nemotron or reproduce live inference evidence. Live inference through the application API remains unverified.'],
    ['OpenShell', 'Native OpenShell enforcement remains unverified. This demo creates no sandbox and makes no claim of runtime isolation enforcement.'],
    ['External effects', 'No real document read, email, SMTP operation or external action is performed. UNKNOWN is a labelled synthetic uncertainty example, not a real delivery outcome.'],
    ['Privacy', 'No pairing, session, credentials, cookies or persistent storage. Use sample text only. No analytics or third-party requests are configured.']
  ].map(([title, detail]) => h('div', {}, h('h2', {}, title), h('p', { class: 'muted' }, detail)))), h('p', { class: 'lower-note muted' }, h('a', { href: './THIRD_PARTY_NOTICES.txt' }, 'Font attribution & third-party notices')));
}
function render(focus = true) {
  const route = currentRoute();
  document.title = `${routes[route]} · Ghost Protocol public synthetic demo`;
  const menu = button('Menu', () => { const dialog = h('dialog', { class: 'mobile-nav', 'aria-label': 'Workspace navigation' }); const close = () => dialog.close(); dialog.append(h('h2', {}, 'Workspace'), navigation(close), button('Close menu', close, 'secondary')); dialog.addEventListener('close', () => { dialog.remove(); menu.focus(); }); dialog.addEventListener('keydown', trapFocus); document.body.append(dialog); dialog.showModal(); }, 'menu-button secondary');
  const reset = button('Reset demo', () => confirmAction('RESET', 'Reset demo', 'Clear this tab’s synthetic task and event history. No backend or persistent data exists.'), 'secondary');
  const sidebar = h('aside', { class: 'sidebar' }, h('a', { href: '#overview', class: 'brand', 'aria-label': 'Ghost Protocol overview' }, h('img', { src: './ghost.svg', alt: '', width: '38', height: '38' }), h('span', {}, 'GHOST', h('small', {}, 'PROTOCOL'))), h('p', { class: 'eyebrow nav-label' }, 'WORKSPACE'), navigation(), h('div', { class: 'sidebar-footer' }, icon('approvals'), h('strong', {}, 'Human authority.\nBy design.'), h('p', { class: 'muted' }, 'Explore the boundary.\nNothing is executed.')));
  const pages = { overview, workspace, approvals, operations, audit, documents, about };
  const main = h('main', { id: 'main', tabindex: '-1' }, pages[route]());
  main.querySelector('h1')?.setAttribute('tabindex', '-1');
  const skip = h('a', { class: 'skip-link', href: '#main' }, 'Skip to content');
  skip.addEventListener('click', event => { event.preventDefault(); main.focus(); main.scrollIntoView({ block: 'start' }); });
  appRoot.replaceChildren(skip, sidebar, h('div', { class: 'app-body' },
    h('header', {}, h('div', { class: 'header-left' }, menu, h('span', { class: 'muted' }, 'Workspace'), h('span', { 'aria-hidden': 'true' }, '›'), h('strong', {}, routes[route])), reset),
    h('div', { class: 'demo-banner', role: 'note' }, h('span', { class: 'banner-dot', 'aria-hidden': 'true' }), h('strong', {}, 'PUBLIC INTERACTIVE DEMO — SYNTHETIC DATA'), h('a', { href: '#about' }, 'No live AI or execution ↗')), main,
    h('footer', {}, 'Synthetic browser state · no backend connection · refresh clears all records')));
  if (focus) main.querySelector<HTMLElement>('h1')?.focus({ preventScroll: true });
}
window.addEventListener('hashchange', () => render());
render(false);
