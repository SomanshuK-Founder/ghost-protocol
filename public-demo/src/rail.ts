import { badge, button, h, showDialog } from './dom.js';
import { records } from './state.js';
import type { State, Event } from './state.js';
export function inspect(state: State, title: string, event?: Event) {
  showDialog(title, h('div', { class: 'record-body' }, h('p', { class: 'muted' }, 'Created by this demo in browser memory. This is not a stored backend record.'), h('pre', {}, JSON.stringify(event ? { provenance: 'SYNTHETIC_BROWSER_DEMO', ...event } : records(state), null, 2))));
}
export function rail(state: State) {
  const planned = state.events.some(event => event.category === 'Planning');
  const stopped = state.phase === 'SAFE_STOPPED';
  const uncertain = state.phase === 'UNKNOWN';
  const blocked = ['REJECTED', 'REVOKED', 'EXPIRED', 'CANCELLED', 'DENIED'].includes(state.phase);
  const active = !state.task ? 0 : uncertain ? 5 : blocked ? state.phase === 'DENIED' ? 2 : state.phase === 'CANCELLED' ? 0 : 3 : !planned ? 1 : state.phase === 'PENDING' ? 3 : 4;
  const nodes = [
    { title: 'Task', label: state.phase === 'CANCELLED' ? 'CANCELLED' : state.task ? 'Request recorded' : 'Not created', detail: 'Synthetic request in this tab', category: 'Task', done: !!state.task && state.phase !== 'CANCELLED' },
    { title: 'Planning', label: planned ? 'Simulated plan' : 'Not started', detail: 'Fixed rules · no live inference', category: 'Planning', done: planned },
    { title: 'Authorization', label: !planned ? 'Not evaluated' : state.phase === 'DENIED' ? 'DENY' : 'APPROVAL_REQUIRED', detail: 'Synthetic scope check', category: 'Authorization', done: false },
    { title: 'Human decision', label: !planned || state.phase === 'DENIED' ? 'Unavailable' : state.phase === 'PENDING' ? 'Pending review' : state.phase === 'CREATED' ? 'Not requested' : state.phase === 'SAFE_STOPPED' || uncertain ? 'Approved' : state.phase, detail: 'Approval never executes', category: 'Approval', done: ['APPROVED', 'SAFE_STOPPED', 'UNKNOWN'].includes(state.phase) },
    { title: 'Safe continuation', label: stopped ? 'SAFE_STOPPED' : state.phase === 'APPROVED' ? 'Ready · explicit action' : blocked || uncertain ? 'Blocked' : 'Not requested', detail: 'No protected dispatch', category: 'Workflow', done: stopped },
    { title: 'Operation outcome', label: uncertain ? 'UNKNOWN example' : 'NOT_EXECUTED', detail: 'External effect: none', category: 'Operation', done: false }
  ];
  const list = h('ol', { class: 'decision-rail' });
  nodes.forEach((node, index) => {
    const tone = index === 5 && uncertain || index === active && blocked ? 'danger' : node.done ? 'success' : index >= 2 && index <= 4 && planned ? 'amber' : 'neutral';
    const event = state.events.filter(event => event.category === node.category).at(-1);
    const li = h('li', { class: `rail-node ${tone} ${index === active ? 'current' : ''}`, ...(index === active ? { 'aria-current': 'step' } : {}) },
      h('div', { class: 'rail-track' }, h('span', { class: 'rail-dot', 'aria-hidden': 'true' }, node.done ? '✓' : blocked && index === active ? '×' : String(index + 1).padStart(2, '0'))),
      h('h3', {}, node.title), h('strong', {}, node.label), h('p', { class: 'muted' }, node.detail),
      event ? button('Inspect record', () => inspect(state, node.title, event), 'text-button') : h('small', { class: 'muted' }, 'No synthetic record'));
    list.append(li);
  });
  return h('section', { class: 'rail-section', 'aria-labelledby': 'rail-title' },
    h('div', { class: 'section-heading' }, h('div', {}, h('p', { class: 'eyebrow' }, 'THE DECISION RAIL'), h('h2', { id: 'rail-title' }, 'From intention to evidence.')), badge('SYNTHETIC RECORDS', 'cyan')),
    list, h('p', { class: 'rail-footnote muted' }, 'Authorization, human approval and continuation are separate. No stage dispatches an external operation.'));
}
