import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, transition, can, records, scenarios } from '../src/state.ts';
import type { State, Action } from '../src/state.ts';
const created = () => transition(initialState(), { type: 'CREATE', title: scenarios.document.title, scenario: 'document' });
const pending = () => transition(created(), { type: 'PLAN' });
const approved = () => transition(pending(), { type: 'APPROVE' });
test('happy path needs separate approval and explicit continuation; no execution', () => {
  const before = pending(); const next = transition(before, { type: 'APPROVE' });
  assert.equal(before.phase, 'PENDING'); assert.equal(next.phase, 'APPROVED');
  assert.equal(next.events.some(event => event.title === 'SAFE_STOPPED'), false);
  const stopped = transition(next, { type: 'CONTINUE' });
  assert.equal(stopped.phase, 'SAFE_STOPPED'); assert.equal(records(stopped)?.execution_status, 'NOT_EXECUTED');
  assert.equal(records(stopped)?.external_effect, 'NONE'); assert.equal(can(stopped, 'CONTINUE'), false);
});
test('initial state contains no invented records', () => { assert.equal(records(initialState()), null); assert.equal(initialState().events.length, 0); });
test('synthetic email is exactly bound and cannot send', () => {
  const state = transition(transition(initialState(), { type: 'CREATE', title: 'Synthetic email', scenario: 'email' }), { type: 'PLAN' });
  assert.equal(records(state)?.title, 'Synthetic email'); assert.equal(records(state)?.recipient, 'teammate@example.test'); assert.equal(records(state)?.action, 'email.send'); assert.equal(records(state)?.external_effect, 'NONE');
});
test('restricted original is denied without an approval', () => {
  const state = transition(transition(initialState(), { type: 'CREATE', title: 'Restricted original', scenario: 'denied' }), { type: 'PLAN' });
  assert.equal(state.phase, 'DENIED'); assert.equal(records(state)?.approval_ref, null); assert.equal(can(state, 'APPROVE'), false);
});
for (const [type, phase] of [['REJECT', 'REJECTED'], ['REVOKE', 'REVOKED'], ['EXPIRE', 'EXPIRED'], ['CANCEL', 'CANCELLED']] as const) test(`${type} blocks continuation without executing`, () => {
  const state = transition(pending(), { type }); assert.equal(state.phase, phase); assert.equal(can(state, 'CONTINUE'), false); assert.equal(records(state)?.execution_status, 'NOT_EXECUTED');
});
test('approved permission can expire or be revoked before continuation', () => {
  for (const type of ['EXPIRE', 'REVOKE'] as const) assert.equal(can(transition(approved(), { type }), 'CONTINUE'), false);
});
test('UNKNOWN remains explicit, non-retriable and without an actual external attempt', () => {
  const state = transition(approved(), { type: 'UNCERTAIN' }); assert.equal(state.phase, 'UNKNOWN'); assert.equal(can(state, 'CONTINUE'), false);
  assert.equal(records(state)?.execution_status, 'UNKNOWN_EXAMPLE'); assert.equal(records(state)?.external_effect, 'NONE');
});
test('all unavailable transitions reject without changing evidence', () => {
  const states: State[] = [initialState(), created(), pending(), approved(), ...(['REJECT', 'REVOKE', 'EXPIRE', 'CANCEL'] as const).map(type => transition(pending(), { type })), transition(approved(), { type: 'CONTINUE' }), transition(approved(), { type: 'UNCERTAIN' })];
  for (const state of states) for (const type of ['CREATE', 'PLAN', 'APPROVE', 'REJECT', 'REVOKE', 'EXPIRE', 'CANCEL', 'CONTINUE', 'UNCERTAIN'] as const) {
    if (!can(state, type)) { const before = JSON.stringify(state); assert.throws(() => transition(state, { type } as Action)); assert.equal(JSON.stringify(state), before); }
  }
});
test('reset clears all browser-memory references and events', () => { assert.deepEqual(transition(approved(), { type: 'RESET' }), initialState()); });
test('replaying plan, approval or continuation cannot duplicate events', () => {
  for (const [state, type] of [[pending(), 'PLAN'], [approved(), 'APPROVE'], [transition(approved(), { type: 'CONTINUE' }), 'CONTINUE']] as const) assert.throws(() => transition(state, { type }));
});
test('input boundaries reject blank, oversized and unsupported scenario values', () => {
  for (const title of [' ', 'ab', 'x'.repeat(101)]) assert.throws(() => transition(initialState(), { type: 'CREATE', title, scenario: 'document' }));
  assert.throws(() => transition(initialState(), { type: 'CREATE', title: 'Example', scenario: '__proto__' as 'document' }));
});
test('events are sequential and explicitly synthetic, with no invented wall clock', () => {
  const state = transition(approved(), { type: 'CONTINUE' }); assert.deepEqual(state.events.map(event => event.step), state.events.map((_, index) => index + 1));
  assert.equal(new Set(state.events.map(event => event.ref)).size, state.events.length); assert.equal(records(state)?.provenance, 'SYNTHETIC_BROWSER_DEMO');
});
