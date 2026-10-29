export type Child = Node | string | number | null;
export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string | boolean> = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (typeof value === 'boolean') { if (value) element.setAttribute(key, ''); }
    else element.setAttribute(key, value);
  }
  for (const child of children) if (child !== null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return element;
}
export function button(label: string, action: () => void, variant = '', disabled = false) {
  const element = h('button', { type: 'button', class: `button ${variant}`, disabled }, label);
  element.addEventListener('click', action); return element;
}
export function badge(label: string, tone = 'neutral') { return h('span', { class: `badge ${tone}` }, label); }
export function heading(eyebrow: string, title: string, detail: string) {
  return h('div', { class: 'page-heading' }, h('p', { class: 'eyebrow' }, eyebrow), h('h1', {}, title), h('p', { class: 'muted' }, detail));
}
export function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab') return;
  const dialog = event.currentTarget as HTMLDialogElement;
  const controls = [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, select, textarea, summary, [tabindex="0"]')].filter(element => element.getClientRects().length > 0);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first && last) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last && first) { event.preventDefault(); first.focus(); }
}
export function icon(name: string) {
  const paths: Record<string, string[]> = {
    overview: ['M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'],
    workspace: ['m3 6 2 2 4-4M12 6h9M3 14h6M12 14h9M3 20h6M12 20h9'],
    approvals: ['M12 3 3 7v6c0 5 9 9 9 9s9-4 9-9V7z', 'm8 12 3 3 5-6'],
    operations: ['M5 3h14v18H5zM8 8h8M8 12h8M8 16h5'],
    audit: ['M3 12h4l3-8 4 16 3-8h4'], documents: ['M4 3h10l6 6v12H4zM14 3v6h6'],
    about: ['M12 8v4m0 4h.01', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0']
  };
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(key, value);
  for (const d of paths[name] ?? paths.about) { const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', d); svg.append(path); }
  return svg;
}
export function showDialog(title: string, content: Node, confirm?: { label: string; run: () => void; danger?: boolean }) {
  const trigger = document.activeElement as HTMLElement | null;
  const dialog = h('dialog', { 'aria-labelledby': 'dialog-title', class: 'modal' });
  const close = () => dialog.close();
  const actions = h('div', { class: 'actions' }, button(confirm ? 'Go back' : 'Close record', close, 'secondary'));
  if (confirm) actions.append(button(confirm.label, () => { close(); confirm.run(); }, confirm.danger ? 'danger' : 'primary'));
  dialog.append(h('p', { class: 'eyebrow' }, 'SYNTHETIC DEMO · NO EXTERNAL EFFECT'), h('h2', { id: 'dialog-title' }, title), content, actions);
  dialog.addEventListener('close', () => { dialog.remove(); if (trigger?.isConnected) trigger.focus(); else document.querySelector<HTMLElement>('h1')?.focus(); });
  dialog.addEventListener('keydown', trapFocus);
  document.body.append(dialog); dialog.showModal();
  (dialog.querySelector('button') as HTMLButtonElement).focus();
}
