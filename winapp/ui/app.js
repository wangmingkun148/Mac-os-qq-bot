'use strict';

// ---------------------------------------------------------------------------------------------------------------
// helpers

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === false || value == null) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style') el.style.cssText = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const ICONS = {
  play: ['X.......', 'XX......', 'XXX.....', 'XXXX....', 'XXXX....', 'XXX.....', 'XX......', 'X.......'],
  pause: ['.XX..XX.', '.XX..XX.', '.XX..XX.', '.XX..XX.', '.XX..XX.', '.XX..XX.', '.XX..XX.', '.XX..XX.'],
  check: ['........', '.......X', '......XX', 'X....XX.', 'XX..XX..', '.XXXX...', '..XX....', '........'],
  minus: ['........', '........', '........', '.XXXXXX.', '.XXXXXX.', '........', '........', '........'],
  bang: ['...XX...', '...XX...', '...XX...', '...XX...', '...XX...', '........', '...XX...', '...XX...'],
  question: ['..XXXX..', '.XX..XX.', '.....XX.', '....XX..', '...XX...', '...XX...', '........', '...XX...'],
  x: ['XX....XX', 'XXX..XXX', '.XXXXXX.', '..XXXX..', '..XXXX..', '.XXXXXX.', 'XXX..XXX', 'XX....XX'],
  dots: ['........', '........', '........', 'XX.XX.XX', 'XX.XX.XX', '........', '........', '........'],
  chevron: ['..X.....', '...X....', '....X...', '.....X..', '.....X..', '....X...', '...X....', '..X.....'],
  sliders: ['..X.....', 'XXXXXXXX', '..X.....', '........', '.....X..', 'XXXXXXXX', '.....X..', '........'],
  window: ['XXXXXXXX', 'X......X', 'XXXXXXXX', 'X......X', 'X......X', 'X......X', 'X......X', 'XXXXXXXX'],
  grid: ['XXX.XXX.', 'XXX.XXX.', 'XXX.XXX.', '........', 'XXX.XXX.', 'XXX.XXX.', 'XXX.XXX.', '........'],
  power: ['...XX...', '.X.XX.X.', 'XX.XX.XX', 'XX.XX.XX', 'XX....XX', '.XX..XX.', '..XXXX..', '........'],
  list: ['XX.XXXXX', '........', 'XX.XXXXX', '........', 'XX.XXXXX', '........', 'XX.XXXXX', '........'],
  pin: ['..XXXX..', '..X..X..', '..X..X..', '.XXXXXX.', '...XX...', '...XX...', '...XX...', '...X....'],
  sparkle: ['...XX...', '...XX...', '.XXXXXX.', 'XXXXXXXX', '.XXXXXX.', '...XX...', '...XX...', '........'],
  bubble: ['.XXXXXX.', 'X......X', 'X......X', 'X......X', '.XXXXXX.', '..X.....', '.X......', '........'],
  globe: ['..XXXX..', '.X.XX.X.', 'X..XX..X', 'XXXXXXXX', 'X..XX..X', '.X.XX.X.', '..XXXX..', '........'],
  hourglass: ['XXXXXXXX', '.XX..XX.', '..XXXX..', '...XX...', '...XX...', '..XXXX..', '.XX..XX.', 'XXXXXXXX'],
  photo: ['XXXXXXXX', 'X......X', 'X.XX...X', 'X.XX.X.X', 'X...XXXX', 'X..XXXXX', 'X.XXXXXX', 'XXXXXXXX'],
  reply: ['...X....', '..XX....', '.XXXXXX.', 'XXXXXXXX', '.XXXXXXX', '..XX...X', '...X...X', '.....XXX'],
  moon: ['..XXXX..', '.XX.....', 'XX......', 'XX......', 'XX......', '.XX....X', '..XXXXX.', '........'],
  back: ['...X....', '..XX....', '.XXXXXXX', 'XXXXXXXX', '.XXXXXXX', '..XX....', '...X....', '........'],
  alert: ['...XX...', '..XXXX..', '..XXXX..', '.XXXXXX.', '.XX..XX.', 'XXX..XXX', 'XXXXXXXX', '........'],
  ear: ['..XXXX..', '.X....X.', 'X..XX..X', 'X.X..X.X', '..X..X..', '...XX...', '........', '........'],
  pauseCircle: ['..XXXX..', '.X....X.', 'X..X.X.X', 'X..X.X.X', 'X..X.X.X', '.X....X.', '..XXXX..', '........'],
};

function icon(name, scale = 1) {
  const rows = ICONS[name] || ICONS.dots;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 8 8');
  svg.setAttribute('width', 8 * scale * 1.5);
  svg.setAttribute('height', 8 * scale * 1.5);
  svg.setAttribute('class', 'px');
  let d = '';
  rows.forEach((row, y) => { for (let x = 0; x < row.length; x++) if (row[x] === 'X') d += `M${x} ${y}h1v1h-1z`; });
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', d);
  svg.append(path);
  return svg;
}

const WOLF = ['................', '..##........##..', '..###......###..', '..####.##.####..', '..############..', '.####......####.', '.###........###.',
  '.###........###.', '.###........###.', '.####......####.', '..####....#####.', '...##########cc.', '....########.ccc', '..............cc',
  '................', '................'];
function logo(size = 36) {
  const canvas = h('canvas', { class: 'logo logo-tile', width: 48, height: 48, style: `width:${size}px;height:${size}px` });
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#141822'; ctx.fillRect(0, 0, 48, 48);
  ctx.strokeStyle = '#2B3345'; ctx.lineWidth = 2; ctx.strokeRect(1, 1, 46, 46);
  const cell = 2.34, origin = (48 - cell * 16) / 2;
  WOLF.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === '.') return;
    ctx.fillStyle = ch === 'c' ? '#6FD3E8' : '#EEF2FA';
    ctx.fillRect(Math.round(origin + x * cell), Math.round(origin + y * cell), Math.ceil(cell), Math.ceil(cell));
  }));
  return canvas;
}

// formatting
const fmt = {
  ago(t, now = Date.now() / 1000) {
    const s = Math.max(0, now - t);
    if (s < 5) return '刚刚'; if (s < 60) return `${Math.floor(s)} 秒前`; if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
    if (s < 86400) return `${Math.floor(s / 3600)} 小时前`; return `${Math.floor(s / 86400)} 天前`;
  },
  elapsed(t, now = Date.now() / 1000) {
    const s = Math.max(0, Math.floor(now - t)); const pad = (n) => String(n).padStart(2, '0');
    return s >= 3600 ? `${Math.floor(s / 3600)}:${pad(Math.floor(s % 3600 / 60))}:${pad(s % 60)}` : `${Math.floor(s / 60)}:${pad(s % 60)}`;
  },
  clock(t) { const d = new Date(t * 1000); return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':'); },
  seconds(v) { return v == null ? null : `${Number(v).toFixed(1)}s`; },
  tokens(v) { return v >= 10000 ? `${(v / 1000).toFixed(1)}k` : String(v); },
  count(v) { return v === Math.round(v) ? String(v) : v.toFixed(1); },
  compact(v) { return v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(Math.floor(v)); },
};

// ---------------------------------------------------------------------------------------------------------------
// transport

function parseHash() {
  const raw = location.hash.replace(/^#/, '');
  const [path, query = ''] = raw.split('?');
  const params = new URLSearchParams(query);
  const parts = path.split('/').filter(Boolean);
  return { name: parts[0] || 'popover', section: parts[1] || 'general', token: params.get('t') };
}
let route = parseHash();
if (route.token) { try { sessionStorage.setItem('token', route.token); } catch (e) { /* private mode */ } }
function token() { try { return sessionStorage.getItem('token') || route.token || ''; } catch (e) { return route.token || ''; } }

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST', headers: { 'X-Token': token(), 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
const act = (name, extra = {}) => api('/api/do', { name, ...extra }).then((r) => { poll(); return r; }).catch(() => {});

// ---------------------------------------------------------------------------------------------------------------
// shared pieces

const PHASE_COLOR = { listening: 'good', thinking: 'accent', starting: 'accent', switching: 'accent', sending: 'info', waiting: 'warn',
  attention: 'bad', offline: 'bad', paused: 'faint' };
const COLOR_VAR = { good: 'var(--good)', accent: 'var(--accent)', info: 'var(--info)', warn: 'var(--warn)', bad: 'var(--bad)', faint: 'var(--text3)' };
const BUSY = new Set(['thinking', 'sending', 'starting', 'switching']);

function led(phase, size = 8) {
  return h('span', { class: 'led' + (BUSY.has(phase) ? ' blink' : ''), style: `width:${size}px;height:${size}px;background:${COLOR_VAR[PHASE_COLOR[phase] || 'faint']}` });
}
function chip(text, cls, iconName) { return h('span', { class: `chip ${cls}` }, iconName ? icon(iconName) : null, text); }
function card(props, ...kids) { return h('div', { class: 'card ' + ((props && props.cls) || ''), style: props && props.style }, ...kids); }

function stageName(t) {
  switch (t.stage) {
    case 'judging': return t.kind === 'image' ? '审核中' : '判断中';
    case 'generating': return t.kind === 'browser' ? '浏览中' : (t.kind === 'image' ? '生成图片' : '生成中');
    case 'choosing': return '待选择'; case 'ready': return '待发送'; case 'sending': return '发送中'; case 'verifying': return '确认中';
    default: return '处理中';
  }
}
function outcomeChip(t) {
  switch (t.outcome) {
    case 'replied': return { text: '已回复', icon: 'check', cls: 'good' };
    case 'silent': return { text: '未回复', icon: 'minus', cls: 'plain' };
    case 'failed': return { text: '失败', icon: 'bang', cls: 'bad' };
    case 'uncertain': return { text: '未确认', icon: 'question', cls: 'bad' };
    case 'abandoned': return { text: '已放弃', icon: 'x', cls: 'warn' };
    case 'cancelled': return { text: '已取消', icon: 'pauseCircle', cls: 'plain' };
    default: return { text: stageName(t), icon: 'dots', cls: 'accent' };
  }
}
const kindName = (k) => ({ proactive: '主动话题', browser: '浏览链接', image: '图片请求' }[k] || '新消息');
const kindIcon = (k) => ({ proactive: 'sparkle', browser: 'globe', image: 'photo' }[k] || 'bubble');

function messageLine(m, clamp = 'clamp2') {
  const body = !m.text ? (m.image ? '[图片]' : '…') : m.text + (m.image ? ' [图片]' : '');
  return h('div', { class: `msg ${clamp}` }, h('span', { class: 'who' }, m.sender || '群友'), '  ' + body);
}

const openState = new Map();
function stepper(t) {
  const labels = [t.kind === 'proactive' ? '触发' : '收到', t.kind === 'browser' ? '浏览' : '判断', '生成', '发送', '确认'];
  let current;
  if (t.outcome === 'replied') current = 5;
  else switch (t.stage) {
    case 'judging': current = 1; break; case 'generating': current = 2; break;
    case 'choosing': case 'ready': case 'sending': current = 3; break; case 'verifying': current = 4; break;
    default: current = t.outcome === 'silent' ? 2 : 5;
  }
  const skipped = t.outcome === 'silent' || t.outcome === 'cancelled';
  const broken = ['failed', 'uncertain', 'abandoned'].includes(t.outcome || '');
  const active = skipped || broken || current >= labels.length ? null : current;
  const failed = broken ? Math.min(current, labels.length - 1) : null;
  const cells = labels.map((_, i) => {
    let cls = '';
    if (i === failed) cls = 'fail'; else if (i < (skipped ? current : Math.min(current, labels.length))) cls = skipped ? 'skip' : 'on'; else if (i === active) cls = 'active';
    return h('i', { class: cls });
  });
  const state = (i) => {
    if (i === 0) return 'done';
    if (skipped) return i < current ? 'done' : 'skipped';
    if (broken) return i < current ? 'done' : (i === current ? 'failed' : 'pending');
    if (i < current) return 'done';
    return i === current ? 'active' : 'pending';
  };
  const color = { active: 'accent', failed: 'bad', pending: 'faint', skipped: 'faint', done: '' };
  return h('div', { class: 'col', style: 'gap:5px;padding:2px 0' }, h('div', { class: 'bar' }, cells),
    h('div', { class: 'steps' }, labels.map((l, i) => h('span', { class: color[state(i)] }, l))));
}

function collapsible(title, summary, key, bodyFn) {
  const open = openState.get(key) || false;
  return h('div', { class: 'thinking' },
    h('div', { class: 'toggle-line', onclick: (e) => { e.stopPropagation(); openState.set(key, !open); rerender(); } },
      h('span', { style: `display:inline-block;transform:rotate(${open ? 90 : 0}deg)` }, icon('chevron')), title,
      !open && summary ? h('span', { class: 'faint ellipsis grow' }, summary) : null),
    open ? bodyFn() : null);
}

function thinkingBlock(t) {
  const entries = [];
  if (t.decision && t.decision.reason) entries.push([t.decision.should_reply === false ? '判断：不接话' : '判断：接话', t.decision.reason]);
  if (t.reply && t.reply.reason && (!t.decision || t.reply.reason !== t.decision.reason)) entries.push(['回复思路', t.reply.reason]);
  (t.thoughts || []).forEach((x) => entries.push(['思考摘要', x]));
  if (t.error) entries.push(['错误', t.error]);
  if (!entries.length) return null;
  return collapsible('思考过程', entries[0][1], `think-${t.id}`, () => h('div', { class: 'body' },
    entries.map(([k, v]) => h('div', {}, h('div', { class: k === '错误' ? 'bad' : 'accent' }, k), h('div', { class: 'selectable' }, v)))));
}
function timelineBlock(t) {
  if (!t.timeline || t.timeline.length <= 1) return null;
  return collapsible('处理时间线', null, `tl-${t.id}`, () => h('div', { class: 'body' },
    t.timeline.map((i) => h('div', { class: 'row top', style: 'gap:8px' }, h('span', { class: 'faint' }, fmt.clock(i.t)), h('span', {}, i.text)))));
}
function metrics(t) {
  const parts = [];
  const model = (t.reply && t.reply.model) || (t.decision && t.decision.model);
  if (model) { const effort = (t.reply && t.reply.reasoning_effort) || (t.decision && t.decision.reasoning_effort); parts.push(effort ? `${model}/${effort}` : model); }
  if (t.decision && t.decision.complexity && t.decision.complexity !== 'none') parts.push(t.decision.complexity);
  if (t.tokens && t.tokens.seconds != null) parts.push(fmt.seconds(t.tokens.seconds));
  if (t.tokens && (t.tokens.input || 0) + (t.tokens.output || 0) > 0) parts.push(`↓${fmt.tokens(t.tokens.input || 0)} ↑${fmt.tokens(t.tokens.output || 0)}`);
  return parts.length ? h('div', { class: 'faint clamp2' }, parts.join(' · ')) : null;
}

function turnCard(t, { expanded = true, showTimeline = true, rating = null, onRate = null } = {}) {
  const key = `turn-${t.id}`;
  const isOpen = openState.has(key) ? openState.get(key) : expanded;
  const active = !t.outcome;
  const chipInfo = outcomeChip(t);
  const shown = isOpen ? t.messages : t.messages.slice(-1);
  const parts = [
    h('div', { class: 'row', style: 'gap:6px' }, chip(chipInfo.text, chipInfo.cls, active ? null : chipInfo.icon),
      h('span', { class: 'faint' }, icon(kindIcon(t.kind))), h('span', { class: 'dim ellipsis grow' }, t.title),
      h('span', { class: 'faint' }, active ? fmt.elapsed(t.started) : fmt.ago(t.ended || t.started))),
    active && isOpen ? stepper(t) : null,
    t.messages.length === 0 ? h('div', { class: 'dim' }, kindName(t.kind)) : h('div', { class: 'col', style: 'gap:4px' },
      shown.map((m) => messageLine(m, isOpen ? 'clamp3' : 'ellipsis')),
      t.message_count > shown.length ? h('div', { class: 'faint' }, `另有 ${t.message_count - shown.length} 条一并处理`) : null),
  ];
  if (t.reply && t.reply.text) {
    parts.push(h('div', { class: 'bubble' }, h('span', { class: 'accent', style: 'padding-top:3px' }, icon('reply')),
      h('div', { class: 'grow selectable ' + (isOpen ? 'clamp6' : 'clamp2') }, t.reply.text),
      onRate && t.outcome === 'replied' ? h('div', { class: 'row', style: 'gap:4px' },
        rateButton('👍', 'up', 'good', rating, onRate, '像真人，多这样说'), rateButton('👎', 'down', 'bad', rating, onRate, '别扭，别这样说')) : null));
  } else if (t.outcome === 'silent') {
    parts.push(h('div', { class: 'row top dim', style: 'gap:5px' }, icon('moon'), h('div', { class: isOpen ? 'clamp3' : 'clamp2' }, (t.decision && t.decision.reason) || '本轮不接话')));
  } else if (['failed', 'uncertain', 'abandoned'].includes(t.outcome || '')) {
    const last = t.timeline && t.timeline.length ? t.timeline[t.timeline.length - 1].text : '';
    parts.push(h('div', { class: 'row top bad', style: 'gap:6px;padding:8px;background:var(--bad-soft)' }, icon('alert'), h('div', {}, t.error || last || '处理没有完成')));
  }
  if (isOpen) { parts.push(thinkingBlock(t)); if (showTimeline) parts.push(timelineBlock(t)); parts.push(metrics(t)); }
  const el = card({}, h('div', { class: 'col', style: 'gap:9px' }, parts));
  el.style.cursor = 'pointer';
  el.addEventListener('click', () => { openState.set(key, !isOpen); rerender(); });
  return el;
}
function rateButton(emoji, value, cls, current, onRate, tip) {
  const on = current === value;
  return h('button', { class: 'btn compact', title: tip, style: `padding:1px 4px;${on ? `border-color:${COLOR_VAR[cls]};background:var(--${cls}-soft)` : 'opacity:.7'}`,
    onclick: (e) => { e.stopPropagation(); onRate(value); } }, emoji);
}

function waitingCard(b) {
  return card({}, h('div', { class: 'col', style: 'gap:6px' },
    h('div', { class: 'row', style: 'gap:6px' }, chip('等待合并', 'info', 'hourglass'), h('span', { class: 'dim ellipsis grow' }, b.title), h('span', { class: 'faint' }, `${b.count} 条`)),
    b.messages.slice(-3).map((m) => messageLine(m, 'ellipsis'))));
}
function unvisitedCard(chats) {
  const now = Date.now() / 1000;
  return card({ cls: 'info' }, h('div', { class: 'col', style: 'gap:5px' },
    h('div', { class: 'row info', style: 'gap:6px' }, icon('bubble'), '其他会话有新消息，等待查看'),
    chats.slice(0, 4).map((c) => h('div', { class: 'row' }, h('span', { class: 'ellipsis grow' }, c.title),
      h('span', { class: 'faint' }, `${c.count} 条 · 已等 ${Math.max(0, Math.floor(now - c.since))} 秒`)))));
}
const SHAPES = { relatable: '共鸣', callback: '接旧梗', hot_take: '小暴论', call_out: '点名', light_question: '小问题', share_link: '分享链接' };
function topicPreviewCard(p) {
  const answered = p.chosen != null;
  const seconds = Math.floor(p.expires - Date.now() / 1000);
  const remaining = answered ? '等待发送' : seconds <= 0 ? '即将作废' : seconds >= 60 ? `还剩 ${Math.floor(seconds / 60)} 分钟` : `还剩 ${seconds} 秒`;
  return card({ cls: 'accent' }, h('div', { class: 'col' },
    h('div', { class: 'row', style: 'gap:6px' }, chip(answered ? '已选好' : '待选择', 'card accent', answered ? 'check' : 'sparkle'),
      h('span', { class: 'dim ellipsis grow' }, p.title), h('span', { class: 'faint' }, remaining)),
    p.options.map((o, i) => h('div', { class: 'row top panel', style: `padding:8px;${p.chosen === i ? 'border-color:var(--accent)' : ''}`, title: o.reason },
      h('div', { class: 'grow col', style: 'gap:3px' },
        h('div', { class: 'row', style: 'gap:5px' }, h('span', { class: 'accent' }, String(i + 1)), h('span', { class: 'faint' }, SHAPES[o.shape] || '开场'), o.link ? icon('globe') : null),
        h('div', { class: 'selectable' }, o.text)),
      h('button', { class: 'btn compact' + (answered ? '' : ' prominent'), disabled: answered, onclick: () => act('choose_topic', { index: i }) }, p.chosen === i ? '已选' : '发这条'))),
    h('div', { class: 'row' }, h('span', { class: 'dim grow' }, answered ? '当前的回复发完就会发出去' : '选一条发出去，也可以都不发'),
      h('button', { class: 'btn compact', disabled: answered, onclick: () => act('choose_topic', { index: -1 }) }, '都不发'))));
}

// ---------------------------------------------------------------------------------------------------------------
// state + routing

let S = null;
let rerender = () => {};
let lastCommand = 0;

async function poll() {
  try {
    S = await api('/api/state');
    if (S.ui && S.ui.command && S.ui.command.id > lastCommand) {
      lastCommand = S.ui.command.id;
      if (route.name === 'settings' && S.ui.command.section) { route.section = S.ui.command.section; settings.pane = route.section; settings.rebuild = true; }
    }
    applyTheme();
    rerender();
  } catch (e) {
    document.title = document.title; // keep the last picture when the app is closing
  }
}
const APPEARANCE = { system: '跟随系统', light: '浅色', dark: '深色' };
const appearance = () => (S && S.prefs && S.prefs.appearance) || 'system';
function applyTheme() {
  const mode = appearance();
  if (mode === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', mode);
}
function setAppearance(mode) {
  if (S) { S.prefs = { ...(S.prefs || {}), appearance: mode }; }
  applyTheme(); settings.rebuild = true; rerender();
  act('set_pref', { key: 'appearance', value: mode });
}
function cycleAppearance() {
  const order = ['system', 'light', 'dark'];
  setAppearance(order[(order.indexOf(appearance()) + 1) % order.length]);
}
function currentTurn() { const l = S.live; return l.turns.find((t) => !t.outcome && t.id !== (l.preview && l.preview.turn)); }
const finished = () => S.live.turns.filter((t) => t.outcome);

function scrollKeeper(fn) {
  const old = document.querySelector('.scroll');
  const top = old ? old.scrollTop : 0;
  fn();
  const now = document.querySelector('.scroll');
  if (now) now.scrollTop = top;
}

// ---------------------------------------------------------------------------------------------------------------
// popover

const ui = { more: false, report: false };
function popoverView() {
  const phase = S.phase, paused = S.paused;
  const preview = paused ? null : S.live.preview;
  const turn = currentTurn();
  const waiting = S.live.waiting[0];
  const items = finished().slice(0, 4);
  const root = h('div', { class: 'scroll' }, h('div', { class: 'popover' },
    h('div', { class: 'row', style: 'gap:10px' }, logo(36),
      h('div', { class: 'grow col', style: 'gap:2px' }, h('div', { class: 't24' }, 'QQ 自动回复'),
        h('div', { class: 'row', style: 'gap:5px' }, led(phase), h('span', { class: 'dim' }, S.phaseLabel), h('span', { class: 'faint ellipsis' }, '· ' + S.modelName))),
      h('button', { class: 'btn' + (paused ? ' prominent' : ''), onclick: () => act('toggle') }, h('span', { class: 'row', style: 'gap:5px' }, icon(paused ? 'play' : 'pause'), paused ? '开始' : '暂停'))),
    h('div', { class: 'col', style: 'gap:6px' },
      h('div', { class: 'section-label' }, h('span', {}, '现在'), paused ? null : h('span', {}, `监听 ${S.live.waiting.length + (turn ? 1 : 0)} 个待处理`)),
      preview ? topicPreviewCard(preview) : null,
      !paused && turn ? turnCard(turn, { expanded: true, showTimeline: false })
        : !paused && waiting ? waitingCard(waiting)
        : !paused && S.live.unvisited && S.live.unvisited.length ? unvisitedCard(S.live.unvisited)
        : !preview ? idleCard() : null),
    stats(),
    !preview || paused ? recent(items) : null,
    h('div', { class: 'card row', style: 'gap:10px' },
      h('div', { class: 'grow col', style: 'gap:4px' }, h('div', { class: 'dim' }, S.providerName), h('div', {}, S.modelName)),
      h('span', { class: 'dim' }, '回复后缀'), toggle(S.suffix, (on) => act('suffix', { on }))),
    ui.report ? dailyReport() : ui.more ? moreMenu() : null,
    h('div', { class: 'row', style: 'gap:8px' },
      footerBtn('window', '状态窗', () => act('window', { kind: 'live' })), footerBtn('sliders', '设置', () => act('window', { kind: 'settings', section: 'general' })),
      footerBtn('grid', 'QQ 空间', () => act('window', { kind: 'settings', section: 'space' })),
      h('button', { class: 'btn icon' + (ui.more ? ' on' : ''), onclick: () => { ui.more = !ui.more; ui.report = false; rerender(); } }, icon('dots', 1.3)),
      h('button', { class: 'btn icon danger', title: '退出 QQ 自动回复', onclick: () => act('quit') }, icon('power', 1.3)))));
  return root;
}
function footerBtn(ic, text, fn) { return h('button', { class: 'btn compact grow', onclick: fn }, h('span', { class: 'row', style: 'gap:5px;justify-content:center' }, icon(ic), text)); }
function toggle(on, onChange) {
  const el = h('span', { class: 'toggle' + (on ? ' on' : ''), role: 'switch', 'aria-checked': on ? 'true' : 'false' });
  el.addEventListener('click', () => { const next = !el.classList.contains('on'); el.classList.toggle('on', next); onChange(next); });
  return el;
}
function idleCard() {
  const phase = S.phase;
  let ic = 'ear', title = '正在监听新消息', detail = (S.live.engine && S.live.engine.message) || '有新的文字消息时才会调用模型。';
  if (S.configError) { ic = 'alert'; title = '配置有误'; detail = S.configError.replace('配置有误，后台没有启动：', '后台没有启动：') + '。请在「设置」里修正后点「保存并重启后台」，或直接编辑 config.json。'; }
  else if (S.paused) { ic = 'pauseCircle'; title = '已暂停'; detail = '点击「开始」后会先记录现有消息作为基线，不会回复历史消息。'; }
  else if (phase === 'offline') { ic = 'alert'; title = '后台没有响应'; detail = '回复进程长时间没有更新状态，请检查 QQ 是否在运行、窗口是否最小化，必要时退出后重开。'; }
  else if (phase === 'attention') { ic = 'alert'; title = '需要注意'; }
  return card({}, h('div', { class: 'row top', style: 'gap:10px' }, h('span', { class: PHASE_COLOR[phase] || '', style: 'padding-top:2px' }, icon(ic, 2)),
    h('div', { class: 'col', style: 'gap:3px' }, h('div', {}, title), h('div', { class: 'dim' }, detail))));
}
function stats() {
  const st = S.live.stats, last = S.counters.lastInferenceSeconds;
  const cell = (v, l, cls) => h('div', {}, h('div', { class: `v ${cls}` }, v), h('div', { class: 'faint' }, l));
  return h('div', { class: 'stats' }, cell(st.replied, '已回复', 'good'), cell(st.silent, '选择不回', 'dim'),
    cell(st.failed, '失败', st.failed > 0 ? 'bad' : 'dim'), cell(last != null ? `${Number(last).toFixed(1)}s` : '—', '上次耗时', 'dim'));
}
function recent(items) {
  return h('div', { class: 'col', style: 'gap:4px' }, h('div', { class: 'section-label' }, h('span', {}, '最近处理')),
    items.length === 0 ? h('div', { class: 'faint', style: 'padding:6px 0' }, '本次运行还没有处理过消息')
      : h('div', { class: 'panel' }, items.map((t) => {
        const c = outcomeChip(t);
        const detail = t.outcome === 'replied' ? '→ ' + ((t.reply && t.reply.text) || '已回复') : t.outcome === 'silent' ? ((t.decision && t.decision.reason) || '选择不回复')
          : (t.error || (t.timeline.length ? t.timeline[t.timeline.length - 1].text : '') || c.text);
        const last = t.messages[t.messages.length - 1];
        return h('div', { class: 'recent-row', onclick: () => act('window', { kind: 'live' }) },
          h('span', { class: `badge ${c.cls === 'plain' ? '' : c.cls}`, style: `background:var(--${c.cls === 'plain' ? 'sunken' : c.cls + '-soft'})` }, icon(c.icon)),
          h('div', { class: 'grow col', style: 'gap:2px;min-width:0' }, last ? messageLine(last, 'ellipsis') : h('div', {}, kindName(t.kind)), h('div', { class: 'faint ellipsis' }, detail)),
          h('span', { class: 'faint' }, fmt.ago(t.ended || t.started)));
      })));
}
function moreMenu() {
  const items = [
    ['今日简报  ›', false, () => { ui.report = true; }], ['主动发起话题', S.paused, () => act('proactive')],
    [`外观：${APPEARANCE[appearance()]}（点击切换）`, false, cycleAppearance],
    [S.pet.enabled ? '隐藏桌宠' : '显示桌宠', false, () => act('pet', { on: !S.pet.enabled })],
    ['打开配置文件', false, () => act('open', { target: 'config' })],
  ];
  return h('div', { class: 'panel shadow menu' }, items.map(([text, disabled, fn]) => h('button', { disabled, onclick: () => { fn(); if (!ui.report) ui.more = false; rerender(); } }, text)));
}
function dailyReport() {
  const key = (off) => { const d = new Date(); d.setDate(d.getDate() + off); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const today = S.daily[key(0)] || {}, yest = S.daily[key(-1)] || {};
  const v = (d, n) => fmt.count(d[n] || 0);
  const avg = (d) => (d.timed_calls > 0 ? `${((d.model_seconds || 0) / d.timed_calls).toFixed(1)}s` : '—');
  const tok = (d) => `${fmt.compact(d.input_tokens || 0)} / ${fmt.compact(d.output_tokens || 0)}`;
  const rows = [['已回复', v(today, 'replied'), v(yest, 'replied')], ['选择不回', v(today, 'silent'), v(yest, 'silent')], ['模型失败', v(today, 'failed'), v(yest, 'failed')],
    ['发送不确定而暂停', v(today, 'uncertain_pauses'), v(yest, 'uncertain_pauses')], ['自动恢复', v(today, 'auto_resumes'), v(yest, 'auto_resumes')],
    ['QQ 被切到前台', v(today, 'wakes'), v(yest, 'wakes')], ['联网搜索', v(today, 'searches'), v(yest, 'searches')], ['主动话题（发出）', v(today, 'topics_sent'), v(yest, 'topics_sent')],
    ['话题有人接 / 没人理', `${v(today, 'topics_good')} / ${v(today, 'topics_ignored')}`, `${v(yest, 'topics_good')} / ${v(yest, 'topics_ignored')}`],
    ['平均耗时', avg(today), avg(yest)], ['Token 输入 / 输出', tok(today), tok(yest)]];
  return h('div', { class: 'panel shadow' }, h('div', { class: 'row', style: 'padding:7px 10px;border-bottom:1px solid var(--border)' },
    h('button', { class: 'btn ghost', style: 'width:auto;gap:4px;padding:0 4px', onclick: () => { ui.report = false; rerender(); } }, icon('back'), '返回'),
    h('span', { class: 'grow', style: 'text-align:center' }, '今日简报'), h('span', { class: 'faint' }, '今天 / 昨天')),
  rows.map(([k, a, b]) => h('div', { class: 'report-row' }, h('span', { class: 'k' }, k), h('span', {}, a), h('span', { class: 'y' }, b))));
}

// ---------------------------------------------------------------------------------------------------------------
// live window

const liveUi = { compact: false };
function liveView() {
  const phase = S.phase, turn = currentTurn(), live = S.live;
  const head = h('div', { class: 'live-head' }, led(phase, 10),
    h('div', { class: 'grow col', style: 'gap:1px;min-width:0' }, h('div', { class: 't24 ellipsis' }, turn ? stageName(turn) : S.phaseLabel),
      h('div', { class: 'faint ellipsis' }, (live.engine && live.engine.message) || S.modelName)),
    h('button', { class: 'btn ghost' + (liveUi.compact ? ' active' : ''), title: '紧凑列表', onclick: () => { liveUi.compact = !liveUi.compact; rerender(); } }, icon('list')),
    h('button', { class: 'btn ghost' + (S.ui.pinned ? ' active' : ''), title: '置顶显示', onclick: () => act('pin', { on: !S.ui.pinned }) }, icon('pin')),
    h('button', { class: 'btn ghost', title: S.paused ? '开始自动回复' : '暂停自动回复', onclick: () => act('toggle') }, icon(S.paused ? 'play' : 'pause')));
  const fin = finished();
  const body = [];
  if (S.paused) body.push(card({ cls: 'soft' }, h('div', { class: 'row dim', style: 'gap:8px' }, icon('pauseCircle'), '已暂停。开始后会先记录现有消息作为基线，不回复历史。')));
  if (live.preview && !S.paused) body.push(topicPreviewCard(live.preview));
  if (live.unvisited && live.unvisited.length && !S.paused) body.push(unvisitedCard(live.unvisited));
  live.waiting.forEach((b) => body.push(waitingCard(b)));
  if (turn) body.push(turnCard(turn, { expanded: true }));
  if (liveUi.compact) fin.forEach((t) => body.push(compactRow(t)));
  else fin.forEach((t, i) => body.push(turnCard(t, { expanded: i === 0 && !turn, rating: S.ratings[t.id], onRate: (r) => rate(t, r) })));
  if (!live.turns.length && !live.waiting.length && !S.paused) body.push(h('div', { class: 'empty col', style: 'align-items:center;gap:8px' }, logo(44), h('div', { class: 't24' }, '等待新消息'), '每条被处理的消息、是否回复、模型的判断理由都会出现在这里。'));
  const st = live.stats, act0 = live.activity && live.activity[0];
  const foot = h('div', { class: 'live-foot' }, h('span', { class: 'good' }, `回复 ${st.replied}`), h('span', { class: 'dim' }, `不回 ${st.silent}`),
    h('span', { class: st.failed > 0 ? 'bad' : 'faint' }, `失败 ${st.failed}`), h('span', { class: 'grow' }),
    act0 ? h('span', { class: 'faint ellipsis', style: 'max-width:170px' }, act0.text) : null);
  return h('div', { style: 'display:flex;flex-direction:column;height:100vh' }, head, h('div', { class: 'scroll' }, h('div', { class: 'cards' }, body)), foot);
}
function compactRow(t) {
  const c = outcomeChip(t), last = t.messages[t.messages.length - 1];
  return h('div', { class: 'card row', style: 'padding:7px 10px;gap:8px' }, h('span', { class: 'badge', style: `background:var(--${c.cls === 'plain' ? 'sunken' : c.cls + '-soft'})` }, icon(c.icon)),
    last ? messageLine(last, 'ellipsis') : null, h('span', { class: 'faint' }, fmt.ago(t.ended || t.started)));
}
function rate(turn, rating) {
  const next = S.ratings[turn.id] === rating ? null : rating;
  S.ratings[turn.id] = next; if (!next) delete S.ratings[turn.id];
  rerender(); act('rate', { turn: { id: turn.id, group: turn.group, title: turn.title, reply: turn.reply, decision: turn.decision, messages: turn.messages }, rating: next });
}

// ---------------------------------------------------------------------------------------------------------------
// settings

const SECTIONS = [['general', '常规', 'sliders'], ['providers', 'AI 供应商', 'globe'], ['vision', '图片', 'photo'], ['people', '群友备注', 'bubble'],
  ['space', 'QQ 空间', 'grid'], ['diagnostics', '诊断', 'check']];
const settings = { pane: 'general', draft: null, original: null, hasSecret: {}, secrets: {}, notice: '', problem: '', rebuild: true, people: null, peopleSaved: false, diag: null, open: {} };

const getp = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
function setp(obj, path, value) {
  const keys = path.split('.'); let cur = obj;
  keys.slice(0, -1).forEach((k) => { if (typeof cur[k] !== 'object' || cur[k] == null) cur[k] = {}; cur = cur[k]; });
  cur[keys[keys.length - 1]] = value;
}
const isDirty = () => JSON.stringify(settings.draft) !== JSON.stringify(settings.original) || Object.values(settings.secrets).some((v) => v);

async function loadConfig() {
  const res = await api('/api/config');
  settings.draft = JSON.parse(JSON.stringify(res.config)); settings.original = JSON.parse(JSON.stringify(res.config));
  settings.hasSecret = res.hasSecret; settings.secrets = {};
}
async function saveConfig(restart) {
  const config = JSON.parse(JSON.stringify(settings.draft));
  Object.entries(settings.secrets).forEach(([path, value]) => { if (value) setp(config, path, value); });
  const res = await api('/api/config', { config, restart });
  if (res.problem) { settings.notice = ''; settings.problem = res.problem; } else {
    settings.problem = ''; await loadConfig(); settings.notice = restart ? '已保存，后台正在重启' : '已保存，当前任务结束后生效';
  }
  settings.rebuild = true; rerender();
}
function refreshFooter() {
  const slot = document.getElementById('footer-chip'); if (!slot) return;
  slot.replaceChildren();
  if (settings.problem) slot.append(chip(settings.problem, 'bad', 'bang'));
  else if (isDirty()) slot.append(chip('有未保存的更改', 'warn', 'dots'));
  else if (settings.notice) slot.append(chip(settings.notice, 'good', 'check'));
  const dirty = isDirty();
  document.querySelectorAll('[data-needs-dirty]').forEach((b) => { b.disabled = !dirty; b.style.opacity = dirty ? 1 : .45; });
}
function dirtyChanged() { settings.notice = ''; settings.problem = ''; refreshFooter(); }

function formCard(title, ...rows) { return h('div', { class: 'formcard' }, title ? h('div', { class: 'ttl' }, title) : null, rows); }
function frow(label, hint, control) { return h('div', { class: 'frow' }, h('div', { class: 'lab' }, h('div', {}, label), hint ? h('div', { class: 'hint' }, hint) : null), control || null); }
function paneHeader(title, subtitle) { return h('div', { class: 'col', style: 'gap:4px' }, h('div', { class: 't24' }, title), h('div', { class: 'dim' }, subtitle)); }
function tf(path, { placeholder = '', width = 260, fallback = '', password = false } = {}) {
  const el = h('input', { class: 'field', type: password ? 'password' : 'text', placeholder, style: `width:${width}px`, value: getp(settings.draft, path) ?? fallback, spellcheck: 'false' });
  el.addEventListener('input', () => { setp(settings.draft, path, el.value); dirtyChanged(); });
  return el;
}
function secretField(path) {
  const el = h('input', { class: 'field', type: 'password', style: 'width:260px', placeholder: settings.hasSecret[path] ? '已配置，留空保持不变' : '尚未配置', autocomplete: 'off' });
  el.value = settings.secrets[path] || '';
  el.addEventListener('input', () => { settings.secrets[path] = el.value; dirtyChanged(); });
  return el;
}
function numField(path, fallback, { unit = '', min = 0, max = 100000 } = {}) {
  const value = getp(settings.draft, path); const input = h('input', { class: 'field', type: 'text', inputmode: 'numeric', value: value ?? fallback });
  const set = (n) => { n = Math.max(min, Math.min(max, n)); input.value = n; setp(settings.draft, path, n); dirtyChanged(); };
  input.addEventListener('change', () => { const n = parseInt(input.value, 10); set(Number.isNaN(n) ? fallback : n); });
  return h('span', { class: 'num' }, input, unit ? h('span', { class: 'faint' }, unit) : null,
    h('span', { class: 'stepper' }, h('button', { onclick: () => set((parseInt(input.value, 10) || 0) + 1) }, '▲'), h('button', { onclick: () => set((parseInt(input.value, 10) || 0) - 1) }, '▼')));
}
function flagField(path, fallback) { const on = getp(settings.draft, path) ?? fallback; return toggle(on, (v) => { setp(settings.draft, path, v); dirtyChanged(); }); }
function selectField(path, options, width = 110) {
  const current = getp(settings.draft, path) ?? '';
  const list = options.includes(current) ? options : [current, ...options];
  const el = h('select', { class: 'field', style: `width:${width}px` }, list.map((o) => h('option', { value: o, selected: o === current }, o || '（默认）')));
  el.addEventListener('change', () => { setp(settings.draft, path, el.value); dirtyChanged(); });
  return el;
}

function generalPane() {
  const names = h('input', { class: 'field', style: 'width:220px', placeholder: '填写本账号昵称', value: (settings.draft.self_names || []).join('、') });
  names.addEventListener('input', () => { settings.draft.self_names = names.value.split('、').map((s) => s.trim()).filter(Boolean); dirtyChanged(); });
  const group = h('input', { class: 'field', style: 'width:220px', placeholder: '填写主群完整名称', value: (settings.draft.groups || [])[0] || '' });
  group.addEventListener('input', () => { settings.draft.groups = [group.value.trim()]; dirtyChanged(); });
  const muted = () => settings.draft.muted_chats || [];
  const rows = []; const seen = new Set();
  const add = (title, kind) => { if (title && !seen.has(title)) { seen.add(title); rows.push({ title, kind }); } };
  (settings.draft.groups || []).forEach((g) => add(g, 'group')); S.chats.forEach((c) => add(c.title, c.kind)); muted().forEach((m) => add(m, 'unknown'));
  const feedbackEvery = S.feedbackEvery || 20;
  const pending = Object.entries(S.ratings).filter(([id, r]) => S.preferences.summarized[id] !== r).length;
  const viewer = (key, text, empty) => h('div', { class: 'col', style: 'align-items:flex-end;gap:6px' },
    h('button', { class: 'btn compact', onclick: () => { settings.open[key] = !settings.open[key]; settings.rebuild = true; rerender(); } }, settings.open[key] ? '收起' : '展开'),
    settings.open[key] ? h('div', { class: 'sunken selectable', style: 'width:420px;height:220px;overflow:auto;padding:8px;white-space:pre-wrap' }, text || empty) : null);
  const mode = appearance();
  return [
    paneHeader('常规与首次使用', '先配置本账号、主群和 AI，再登录并打开 QQ，最后启动监听。模型应原生支持图片输入。'),
    formCard('首次使用',
      frow('1. 登录 QQ', '打开 QQ 主窗口并登录要使用的账号；窗口不要最小化，启动时会核对昵称。'),
      frow('2. 填写 AI', '到 AI 供应商页填写 OpenAI 兼容接口和原生多模态模型。所有 AI 任务共用该配置。'),
      frow('3. 无需额外权限', 'Windows 版通过 UI Automation 读取 QQ，不需要授权；如果 QQ 是以管理员身份运行的，本程序也需要以管理员身份运行。'),
      frow('4. 保存并开始', '保存配置后点托盘面板里的“开始”。电脑需保持唤醒；切换会话和发送会占用当前桌面的键盘与鼠标。')),
    formCard('账号与主群',
      frow('本账号昵称', '填写 QQ 界面显示的昵称，用于避免错账号发送；不填群友昵称。', names),
      frow('主群完整名称', '必须与 QQ 会话列表完整名称一致。', group),
      frow('本账号 QQ 号', 'QQ 空间功能使用；不使用空间可留空。', tf('qq_account', { width: 220 })),
      frow('QQ 程序路径', '留空自动查找（QQ.exe）。', tf('qq_app', { width: 220 })),
      frow('Python 路径', '浏览器任务才用得到；留空自动查找项目 .venv 或系统 Python。', tf('python', { width: 220 }))),
    formCard('自定义设定（可选）', h('div', { class: 'pad col' }, h('div', { class: 'dim' }, '留空使用通用聊天规则。设定、风格摘要和群友记忆只保存在你自己的电脑中。'),
      (() => { const t = h('textarea', { class: 'field', rows: 5 }); t.value = settings.draft.persona || ''; t.addEventListener('input', () => { settings.draft.persona = t.value; dirtyChanged(); }); return t; })())),
    formCard('打分总结（回复偏好）',
      frow('新攒的打分', `状态窗里给回复点 👍 / 👎；所有打分都会永久保存，每攒够 ${feedbackEvery} 条新打分总结一轮，写进回复的主提示词。只总结“怎么说”（长短、语气、句式），不记聊的是什么内容、不记人名`,
        h('span', { class: 'dim' }, `${pending} / ${feedbackEvery} 条 · 已总结 ${S.preferences.rounds} 轮`)),
      frow(S.preferences.updatedAt ? `上次总结：${S.preferences.updatedAt}` : '还没有总结过', S.preferences.versions > 0 ? '觉得上一轮总结得不对，可以撤回；那一轮用到的打分会在下次重新总结' : null,
        h('button', { class: 'btn compact', disabled: S.preferences.versions === 0, onclick: () => act('revert_feedback') }, '撤回上一轮')),
      frow('查看现在的偏好', null, viewer('prefs', S.preferences.text, `（还没有偏好：攒够 ${feedbackEvery} 条打分后会自动总结）`))),
    formCard('风格总结',
      frow('长度', '群聊风格总结每攒够 100 条新消息会追加新特点；写满（约 1900 字）时自动压缩，旧版本会保存', h('span', { class: 'dim' }, `${S.styleInfo.chars} / 1999 字`)),
      frow(S.styleInfo.compressedAt ? `上次压缩：${S.styleInfo.compressedAt}` : '还没有压缩过', S.styleInfo.versions > 0 ? '觉得压缩后说话变味了，可以撤回到压缩前的版本（之后新加的特点会一起撤掉）' : null,
        h('button', { class: 'btn compact', disabled: S.styleInfo.versions === 0, onclick: () => act('revert_style') }, '撤回上次压缩')),
      frow('查看现在的总结', null, viewer('style', S.styleInfo.text, '（还没有总结）'))),
    formCard('外观', frow('界面明暗', '立即生效，只影响这台电脑，不写入配置文件', h('div', { class: 'seg', style: 'width:260px' },
      Object.entries(APPEARANCE).map(([k, label]) => h('button', { class: mode === k ? 'on' : '', onclick: () => setAppearance(k) }, label))))),
    formCard('节奏',
      frow('回复冷却', '同一会话两次回复之间至少间隔', numField('cooldown_seconds', 12, { unit: '秒' })),
      frow('消息合并等待', '消息静止这么久后再一起判断', numField('merge_seconds', 6, { unit: '秒' })),
      frow('合并等待最多次数', '连续消息每来一条就重新计时一次（第一条算第 1 次），最多这么多次，之后不再延后；0 表示不限次数', numField('max_merge_waits', 3, { unit: '次', max: 50 })),
      frow('最长合并等待', '不论次数，一批消息最多等这么久', numField('max_merge_seconds', 20, { unit: '秒' })),
      frow('其他会话最长等待', '其他群或私聊有新消息时，最多等这么久就先放下主群去查看；0 表示始终主群优先', numField('secondary_max_wait_seconds', 8, { unit: '秒', max: 120 })),
      frow('单条回复上限', null, numField('max_reply_chars', 160, { unit: '字' })),
      frow('上下文条数', '每次判断带上的最近消息数', numField('context_messages', 12, { unit: '条', min: 1, max: 60 }))),
    formCard('范围与标记',
      frow('回复其他群聊与私聊', '主群优先；其他会话有新消息才会切过去', flagField('reply_all_conversations', false)),
      frow('回复添加自定义后缀', '后缀文字在 AI 供应商页填写', flagField('ai.suffix_enabled', true))),
    formCard('静音的聊天', rows.length === 0 ? frow('还没有读到任何聊天', '机器人开始运行并看过聊天后，这里会列出群和私聊')
      : rows.map((c, i) => frow(c.title, i === 0 ? '打开后只读取记录这个聊天，不回复、不主动发话' : null, h('span', { class: 'row' }, h('span', { class: 'faint' }, c.kind === 'group' ? '群聊' : c.kind === 'private' ? '私聊' : ''),
        toggle(muted().includes(c.title), (on) => { const list = muted().filter((x) => x !== c.title); if (on) list.push(c.title); settings.draft.muted_chats = list; dirtyChanged(); }))))),
    formCard('桌宠（白色像素小狼）',
      frow('显示桌宠', '悬浮在桌面上，收到消息、思考、回复、不接话、出错时有不同表现；可拖动，点它会有动作，右键有菜单', flagField('pet.enabled', false)),
      frow('大小', '每个像素放大的倍数', numField('pet.scale', 4, { unit: '倍', min: 1, max: 12 })),
      frow('空闲时自己走动', null, flagField('pet.wander', true)),
      frow('头顶气泡', '回复时显示回复内容，不接话时显示理由，出错时显示原因', flagField('pet.bubble', true))),
    formCard('状态窗', frow('开始运行时自动显示小窗', null, flagField('live_window.auto_show', true))),
  ];
}
function providersPane() {
  return [
    paneHeader('AI 供应商', '请使用原生多模态模型，支持文字与 image_url 图片输入、中文和 JSON 输出。回复判断、聊天、总结、压缩、浏览器、主动话题与空间评论均使用此模型。'),
    formCard(null,
      frow('供应商名称', '自定义显示名称，不影响请求地址。', tf('ai.name', { width: 220 })), frow('接口地址', 'OpenAI 兼容 /v1 基础地址，或完整 /chat/completions 地址。', tf('ai.base_url', { placeholder: 'https://…/v1' })),
      frow('API Key', null, secretField('ai.api_key')), frow('模型名称', null, tf('ai.model')), frow('回复后缀', '可留空；例如 ～AI。', tf('ai.suffix', { width: 160 })),
      frow('思考强度', '留空由接口默认决定；不支持的可选参数会自动省略。', selectField('ai.reasoning_effort', ['', 'minimal', 'low', 'medium', 'high'])),
      frow('请求超时', null, numField('ai.timeout_seconds', 60, { unit: '秒', min: 5, max: 300 })), frow('超时重试', null, numField('ai.timeout_retries', 1, { unit: '次', max: 3 }))),
    formCard('网页和主动话题',
      frow('启用浏览器任务', '需先安装 requirements-browser.txt 与 Chromium；网页和视频分析仍使用此 AI。', flagField('browser.enabled', false)),
      frow('启用自动主动话题', '群内沉默后可概率开场；手动主动话题按钮仍可用。', flagField('proactive_enabled', false)),
      frow('主动话题沉默阈值', null, numField('proactive_idle_seconds', 1800, { unit: '秒', min: 60, max: 86400 }))),
  ];
}
function visionPane() {
  return [
    paneHeader('图片', '识图会临时复制群里的新图片交给模型；生图需有人 @ 并明确提出要求，审核通过后才会生成。'),
    formCard('发给模型的图片', frow('最长边上限', '群里的图片发给模型前，超过这个像素的会先等比缩小，减小上传体积；不会放大；0 表示不缩小', numField('image_max_edge', 2048, { unit: '像素', max: 8192 }))),
    formCard('图片生成', frow('启用图片生成', null, flagField('image_generation.enabled', false)), frow('接口地址', null, tf('image_generation.endpoint')),
      frow('模型', null, tf('image_generation.model', { width: 200 })), frow('输出尺寸', '格式为 宽*高，返回尺寸必须一致', tf('image_generation.size', { width: 140, fallback: '1920*1080' })),
      frow('每人 24 小时上限', null, numField('image_generation.max_per_24h', 2, { unit: '张' })), frow('API Key', null, secretField('image_generation.api_key'))),
  ];
}
function spacePane() {
  return [
    paneHeader('QQ 空间', '浏览好友动态，结合群聊风格点赞或评论；视频和不可读内容会跳过，已评论过的不会重复。沿用当前聊天模型。'),
    card({ cls: 'soft' }, h('div', { class: 'row top', style: 'gap:8px' }, icon('hourglass', 1.5), h('div', {}, h('div', {}, 'Windows 版的 QQ 空间自动浏览还在开发中。'), h('div', { class: 'dim' }, '聊天回复、识图、生图、主动话题不受影响；下面的定时设置会保留，功能上线后直接生效。')))),
    formCard('每日定时', frow('每天自动浏览一轮', null, flagField('qzone.schedule_enabled', true)), frow('开始时间', '按下面的时区，晚于该时间启动会补跑当天一轮', numField('qzone.hour', 19, { unit: '点', max: 23 })),
      frow('时区', null, tf('qzone.timezone', { width: 170, fallback: Intl.DateTimeFormat().resolvedOptions().timeZone })), frow('处理间隔', '每条动态之间的等待', numField('qzone.interval_seconds', 60, { unit: '秒', min: 10, max: 3600 }))),
  ];
}

let peopleTimer = null;
function savePeopleSoon() { clearTimeout(peopleTimer); peopleTimer = setTimeout(async () => { await api('/api/people', { people: settings.people }); settings.peopleSaved = true; const s = document.getElementById('people-saved'); if (s) s.textContent = '已保存'; }, 600); }
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
function peoplePane() {
  const people = settings.people || [];
  const knows = (name) => people.some((p) => p.names.some((n) => n.split(/\s+/).join(' ') === name.split(/\s+/).join(' ')));
  const speakers = []; const seen = new Set();
  S.live.turns.forEach((t) => [...t.messages].reverse().forEach((m) => { if (m.sender && !seen.has(m.sender)) { seen.add(m.sender); speakers.push(m.sender); } }));
  S.live.waiting.forEach((b) => b.messages.forEach((m) => { if (m.sender && !seen.has(m.sender)) { seen.add(m.sender); speakers.push(m.sender); } }));
  const unknown = speakers.slice(0, 20).filter((n) => !knows(n));
  const addPerson = (name) => { people.unshift({ id: uid(), names: name ? [name] : [], call_as: '', about: '', notes: '' }); settings.people = people; settings.rebuild = true; savePeopleSoon(); rerender(); };
  const note = (person, key) => { const t = h('textarea', { class: 'field', rows: 2, style: 'width:300px' }); t.value = person[key] || ''; t.addEventListener('input', () => { person[key] = t.value; delete person.drafted; savePeopleSoon(); }); return t; };
  const field = (person, key, placeholder) => { const i = h('input', { class: 'field', style: 'width:300px', placeholder, value: person[key] || '' }); i.addEventListener('input', () => { person[key] = i.value; delete person.drafted; savePeopleSoon(); }); return i; };
  return [
    paneHeader('群友备注', '按群里显示的昵称对上人。模型回复某人时会看到他的备注，只当背景参考，回复里不会提到备注。改动自动保存。'),
    h('div', { class: 'row' }, h('button', { class: 'btn prominent', onclick: () => addPerson('') }, '+ 新增群友'), h('span', { class: 'grow' }), h('span', { class: 'faint', id: 'people-saved' }, settings.peopleSaved ? '已保存' : '')),
    unknown.length ? formCard('最近发言、还没有备注的人', h('div', { class: 'people-chips' }, unknown.map((n) => h('button', { class: 'btn compact', onclick: () => addPerson(n) }, '+ ' + n)))) : null,
    people.length === 0 ? h('div', { class: 'faint' }, '还没有备注。点“新增群友”，或从上面最近发言的人里添加。') : null,
    people.map((person) => formCard(person.names[0] || '新群友',
      person.drafted ? frow('这张是根据聊天记录自动写的草稿', '请核对；改动任何一项后就算你自己的备注', chip('草稿', 'warn')) : null,
      frow('昵称', '群里显示的名字，可以填多个，用逗号隔开；有人改名就把新名字加上', (() => { const i = h('input', { class: 'field', style: 'width:300px', placeholder: '例如：昵称A、昵称B', value: person.names.join('，') }); i.addEventListener('input', () => { person.names = i.value.split(/[，,、\n]/).map((s) => s.trim()).filter(Boolean); delete person.drafted; savePeopleSoon(); }); return i; })()),
      frow('怎么称呼', '机器人叫他时用的称呼；留空就不特别称呼', field(person, 'call_as', '例如：朋友')), frow('他是谁', '在群里的身份、常聊的话题、和谁比较熟', note(person, 'about')),
      frow('说话注意', '他喜欢或不喜欢的玩笑、不要碰的话题', note(person, 'notes')),
      frow('删除这张备注', null, h('button', { class: 'btn compact', onclick: () => { settings.people = people.filter((p) => p.id !== person.id); settings.rebuild = true; savePeopleSoon(); rerender(); } }, '删除')))),
  ];
}
function diagnosticsPane() {
  const d = settings.diag;
  const check = (title, ok, detail) => frow(title, detail, h('span', { class: ok ? 'good' : 'bad' }, icon(ok ? 'check' : 'alert', 1.5)));
  const errors = S.counters.configErrors || [], warnings = S.counters.configWarnings || [];
  const configRows = !errors.length && !warnings.length ? [frow('config.json', '没有发现问题', h('span', { class: 'good' }, icon('check', 1.5)))]
    : [...errors.map((e) => frow(e, null, h('span', { class: 'bad' }, icon('x', 1.5)))), ...warnings.map((w) => frow(w, null, h('span', { class: 'warn' }, icon('alert', 1.5))))];
  const file = (title, path, target) => frow(title, path || null, h('button', { class: 'btn compact', onclick: () => act('open', { target }) }, '打开'));
  return [
    paneHeader('诊断', '出问题时先看这里：QQ 与后台是否正常，以及日志和配置文件的位置。'),
    formCard('配置检查', configRows),
    formCard('运行条件', d ? [
      check('QQ 正在运行', d.qqRunning, d.qqRunning ? (d.qqPath || '已检测到') : '未检测到 QQ'),
      check('QQ 主窗口可见', d.qqWindow, d.qqWindow ? '已找到' : '没有找到可见的 QQ 主窗口（最小化或收在托盘里时读不到）'),
      check('能读取 QQ 界面', d.qqReadable, d.qqReadable ? 'UI Automation 读取正常' : (d.readError || '读取失败')),
      check('权限一致', !(d.qqElevated === true && d.appElevated === false) && d.qqElevated !== null, d.qqElevated === true && d.appElevated === false ? 'QQ 以管理员身份运行而本程序不是：无法点击/输入，请以管理员身份重新运行本程序'
        : d.qqElevated === null ? '无法判断 QQ 是否以管理员身份运行（可能被更高权限保护）' : '正常'),
      frow('被其他窗口盖住时的刷新', d.qqFlags === null || d.qqFlags === undefined ? 'QQ 没有运行，无法检查' : d.qqFlags ? '已用防休眠参数启动，被盖住时也会实时刷新'
        : '没有用防休眠参数启动（可选）。测试中 QQ 被盖住时仍能读取；如果你发现被其他窗口完全盖住后机器人读到旧消息，用下面的按钮重启 QQ 即可。',
      h('span', { class: d.qqFlags ? 'good' : 'faint' }, icon(d.qqFlags ? 'check' : 'dots', 1.5))),
      check('回复后台', d.backendAlive, d.backendAlive ? '运行中' : '没有在运行'),
      check('系统通知', d.notifications, d.notifications ? '通过托盘图标发出' : '托盘不可用'),
    ] : frow('检测中…')),
    h('div', { class: 'row', style: 'flex-wrap:wrap' }, h('button', { class: 'btn', onclick: runDiagnostics }, '重新检测'), h('button', { class: 'btn', onclick: () => act('test_notification') }, '发送测试通知'), h('button', { class: 'btn', onclick: () => act('restart_backend') }, '重启后台')),
    h('div', { class: 'row', style: 'flex-wrap:wrap' },
      h('button', { class: 'btn', onclick: async () => { if (confirm('这会关闭 QQ 并重新启动（需要重新登录一次，未发送的草稿会丢失）。继续吗？')) { await api('/api/do', { name: 'restart_qq' }); runDiagnostics(); } } }, '用防休眠参数重启 QQ'),
      h('button', { class: 'btn', onclick: async () => { const r = await api('/api/do', { name: 'qq_shortcut' }); alert(r.ok ? '已在桌面创建「QQ（机器人模式）」快捷方式，以后用它启动 QQ。' : '创建失败：' + (r.error || '')); } }, '在桌面创建带参数的 QQ 快捷方式')),
    formCard('文件', file('运行日志', 'runtime/bridge.log', 'log'), file('QQ 操作日志', 'runtime/native.log', 'native_log'), file('后台错误输出', 'runtime/backend.log', 'backend_log'), file('配置文件', 'config.json', 'config'), file('项目文件夹', '', 'folder')),
    h('div', { class: 'faint' }, 'config.json 含 API Key，请不要把它或日志发给他人。'),
  ];
}
async function runDiagnostics() { settings.diag = null; settings.rebuild = true; rerender(); try { settings.diag = await api('/api/diagnostics'); } catch (e) { settings.diag = { qqRunning: false, readError: '检测失败' }; } settings.rebuild = true; rerender(); }

async function enterPane(name) {
  settings.pane = name; settings.rebuild = true;
  if (name === 'people' && settings.people == null) { settings.people = (await api('/api/people')).people || []; }
  if (name === 'diagnostics') runDiagnostics();
  rerender();
}

let settingsBuilt = false;
function settingsView() {
  const phase = S.phase;
  if (!settings.draft) { loadConfig().then(() => { settings.rebuild = true; rerender(); }); return h('div', { class: 'empty' }, '读取配置…'); }
  if (settingsBuilt && !settings.rebuild) {
    // between rebuilds only the lamp in the sidebar changes; keep every input untouched
    const lamp = document.getElementById('side-phase');
    if (lamp) lamp.replaceChildren(led(phase, 7), h('span', { class: 'faint' }, S.phaseLabel));
    refreshFooter();
    return null;
  }
  settings.rebuild = false; settingsBuilt = true;
  const panes = { general: generalPane, providers: providersPane, vision: visionPane, people: peoplePane, space: spacePane, diagnostics: diagnosticsPane };
  const wrapper = h('div', { class: 'settings' },
    h('div', { class: 'side' }, h('div', { class: 'row', style: 'gap:8px;padding:6px 10px 14px' }, logo(28), h('span', { class: 't24' }, '设置')),
      SECTIONS.map(([id, title, ic]) => h('button', { class: 'nav' + (settings.pane === id ? ' on' : ''), onclick: () => enterPane(id) }, icon(ic), title)),
      h('div', { class: 'grow' }), h('div', { class: 'row', id: 'side-phase', style: 'gap:5px;padding:0 10px 6px' }, led(phase, 7), h('span', { class: 'faint' }, S.phaseLabel))),
    h('div', { class: 'main' }, h('div', { class: 'scroll' }, h('div', { class: 'pane' }, (panes[settings.pane] || generalPane)())),
      h('div', { class: 'foot' }, h('span', { id: 'footer-chip' }), h('span', { class: 'grow' }),
        h('button', { class: 'btn', 'data-needs-dirty': true, onclick: async () => { await loadConfig(); settings.notice = ''; settings.problem = ''; settings.rebuild = true; rerender(); } }, '还原'),
        h('button', { class: 'btn', onclick: () => saveConfig(true) }, '保存并重启后台'),
        h('button', { class: 'btn prominent', 'data-needs-dirty': true, onclick: () => saveConfig(false) }, '保存并应用'))));
  setTimeout(refreshFooter, 0);
  return wrapper;
}

// ---------------------------------------------------------------------------------------------------------------
// main

const TITLES = { popover: 'QQ 自动回复', live: 'QQ 自动回复 · 状态窗', settings: 'QQ 自动回复 · 设置' };
rerender = function () {
  if (!S) return;
  document.title = TITLES[route.name] || TITLES.popover;
  const root = document.getElementById('root');
  const active = document.activeElement;
  if (route.name === 'settings') {
    const view = settingsView();
    if (view) { const keep = document.querySelector('.main .scroll'); const top = keep ? keep.scrollTop : 0; root.replaceChildren(view); const now = document.querySelector('.main .scroll'); if (now) now.scrollTop = top; }
    return;
  }
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
  scrollKeeper(() => { root.replaceChildren(route.name === 'live' ? liveView() : popoverView()); });
};
window.addEventListener('hashchange', () => { route = parseHash(); settings.pane = route.section; settings.rebuild = true; rerender(); });
settings.pane = route.section;
poll();
setInterval(poll, 1000);
