'use strict';

/* All text that came from a receipt is untrusted. It is only ever put on the
   page with textContent / text nodes (see h()), never with innerHTML. */

const state = {
  config: { categories: [], extraction_enabled: false, max_files: 5, max_upload_mb: 5 },
  expenses: [],   // {id, vendor, amount, date, category, language?, confidence?}
  budgets: {},    // category -> number
  month: null,    // 'YYYY-MM'
  monthChosen: false, // true once the person picks a month by hand
  nextId: 1,
  analysisSeq: 0,
};

const $ = (id) => document.getElementById(id);

/* ---------- small helpers ---------- */

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style') Object.assign(el.style, value); // CSSOM is allowed by our CSP; style="" attributes are not
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function formatInr(value) {
  const whole = Number.isInteger(value);
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR',
    minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2,
  }).format(value);
}

function monthLabel(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1));
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

function setStatus(message, isError = false) {
  const el = $('status');
  el.textContent = message;
  el.classList.toggle('error', isError);
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function readError(response, fallback) {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return body.detail;
  } catch (_) { /* not JSON */ }
  return fallback;
}

/* ---------- expenses ---------- */

function addExpense(data) {
  state.expenses.push({
    id: state.nextId++,
    vendor: String(data.vendor || '').trim(),
    amount: Number(data.amount),
    date: data.date || '',
    category: data.category || 'Other',
    language: data.language || null,
    confidence: typeof data.confidence === 'number' ? data.confidence : null,
  });
}

function isValid(expense) {
  return expense.vendor.length > 0 && Number.isFinite(expense.amount) && expense.amount > 0
    && state.config.categories.includes(expense.category);
}

function renderRows() {
  const list = $('rows');
  list.replaceChildren();
  $('empty').hidden = state.expenses.length > 0;

  state.expenses.forEach((expense, index) => {
    const n = index + 1;
    const suffix = h('span', { class: 'sr-only' }, ` for expense ${n}`);

    const vendor = h('input', {
      type: 'text', maxlength: 80, value: expense.vendor, autocomplete: 'off',
      oninput: (e) => { expense.vendor = e.target.value; refresh(); },
    });
    const amount = h('input', {
      type: 'number', min: '0.01', step: '0.01', inputmode: 'decimal', value: expense.amount,
      oninput: (e) => { expense.amount = parseFloat(e.target.value); refresh(); },
    });
    const date = h('input', {
      type: 'date', value: expense.date,
      oninput: (e) => { expense.date = e.target.value; renderMonths(); refresh(); },
    });
    const category = h('select', {
      'data-cat-for': expense.id,
      onchange: (e) => { setCategory(expense, e.target.value); },
    }, state.config.categories.map((c) => h('option', { value: c, selected: c === expense.category }, c)));

    const hints = [];
    if (expense.confidence !== null && expense.confidence < 0.7) {
      hints.push('The app was not sure about this one. Please check the vendor and amount against your receipt.');
    }
    if (expense.language && !/^english$/i.test(expense.language)) {
      hints.push(`Read from a ${expense.language} receipt.`);
    }

    list.append(h('li', { class: 'row' },
      h('label', { class: 'cell vendor' }, h('span', { class: 'cell-label' }, 'Vendor', suffix.cloneNode(true)), vendor),
      h('label', { class: 'cell' }, h('span', { class: 'cell-label' }, 'Amount (₹)', suffix.cloneNode(true)), amount),
      h('label', { class: 'cell' }, h('span', { class: 'cell-label' }, 'Date', suffix.cloneNode(true)), date),
      h('label', { class: 'cell' }, h('span', { class: 'cell-label' }, 'Category', suffix.cloneNode(true)), category),
      h('button', {
        class: 'btn secondary remove', type: 'button',
        'aria-label': `Remove expense ${n}, ${expense.vendor || 'no vendor'}`,
        onclick: () => { state.expenses = state.expenses.filter((x) => x.id !== expense.id); renderAll(); },
      }, 'Remove'),
      hints.length ? h('p', { class: 'hint' }, hints.join(' ')) : null,
    ));
  });
}

/* A correction teaches the rest of this session: same vendor, same category. */
function setCategory(expense, category) {
  expense.category = category;
  const key = expense.vendor.trim().toLowerCase();
  if (key) {
    for (const other of state.expenses) {
      if (other.id !== expense.id && other.vendor.trim().toLowerCase() === key && other.category !== category) {
        other.category = category;
        const select = document.querySelector(`select[data-cat-for="${other.id}"]`);
        if (select) select.value = category;
      }
    }
  }
  refresh();
}

/* ---------- budgets & months ---------- */

function renderBudgetInputs() {
  const grid = $('budget-grid');
  grid.replaceChildren();
  for (const category of state.config.categories) {
    const input = h('input', {
      type: 'number', min: '0', max: '10000000', step: '1', inputmode: 'numeric',
      value: state.budgets[category] || '',
      oninput: (e) => {
        const value = parseFloat(e.target.value);
        if (Number.isFinite(value) && value > 0) state.budgets[category] = value;
        else delete state.budgets[category];
        refresh();
      },
    });
    grid.append(h('label', { class: 'cell' }, h('span', { class: 'cell-label' }, category), input));
  }
}

function availableMonths() {
  const months = new Set(state.expenses.filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e.date)).map((e) => e.date.slice(0, 7)));
  months.add(todayIso().slice(0, 7));
  return [...months].sort().reverse();
}

function renderMonths() {
  const months = availableMonths();
  const dated = state.expenses.filter((e) => e.date).map((e) => e.date.slice(0, 7)).sort();
  if (!state.monthChosen || !months.includes(state.month)) {
    state.month = dated.length ? dated[dated.length - 1] : months[0];
  }
  const select = $('month');
  select.replaceChildren(...months.map((m) => h('option', { value: m, selected: m === state.month }, monthLabel(m))));
}

/* ---------- analysis ---------- */

const refresh = debounce(runAnalysis, 250);

async function runAnalysis() {
  const expenses = state.expenses.filter(isValid).map((e) => ({
    vendor: e.vendor, amount: e.amount, category: e.category, date: e.date || null,
  }));
  const budgets = Object.fromEntries(Object.entries(state.budgets).filter(([, v]) => v > 0));

  if (expenses.length === 0 && Object.keys(budgets).length === 0) {
    $('result').hidden = true;
    $('result-empty').hidden = false;
    return;
  }

  const seq = ++state.analysisSeq;
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expenses, budgets, month: state.month }),
    });
    if (!response.ok) throw new Error(await readError(response, 'Could not update the summary.'));
    const data = await response.json();
    if (seq === state.analysisSeq) renderResult(data); // ignore out-of-date answers
  } catch (err) {
    if (seq === state.analysisSeq) setStatus(err.message || 'Could not update the summary.', true);
  }
}

function renderResult(data) {
  $('result-empty').hidden = true;
  $('result').hidden = false;

  const stat = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));
  $('stats').replaceChildren(
    stat(`Spent in ${monthLabel(data.month)}`, formatInr(data.total_spent)),
    stat('Total budget', data.total_budget === null ? 'Not set' : formatInr(data.total_budget)),
    data.projected_total === null
      ? stat('Transactions', String(data.transaction_count))
      : stat('On track to spend', formatInr(data.projected_total)),
  );

  const maxSpent = Math.max(1, ...data.categories.map((c) => c.spent));
  $('bars').replaceChildren(...data.categories.map((c) => bar(c, maxSpent)));

  fillList('alerts', 'alerts-wrap', data.alerts.map((a) => {
    const label = { over: 'Over budget. ', warning: 'Close to the limit. ', projection: 'Pace. ' }[a.level] || '';
    return h('li', { class: `level-${a.level}` }, h('strong', {}, label), a.message);
  }));
  fillList('tips', 'tips-wrap', data.suggestions.map((t) => h('li', {}, t)));
  fillList('vendors', 'vendors-wrap', data.top_vendors.map((v) =>
    h('li', {}, `${v.vendor}: ${formatInr(v.total)} in ${v.count} ${v.count === 1 ? 'payment' : 'payments'}`)));
}

function fillList(listId, wrapId, items) {
  $(listId).replaceChildren(...items);
  $(wrapId).hidden = items.length === 0;
}

const STATUS_TEXT = { ok: 'On track', warning: 'Close to the limit', over: 'Over budget', no_budget: 'No budget set' };

function bar(c, maxSpent) {
  let fillPct; let tickPct = null;
  if (c.budget === null) {
    fillPct = (c.spent / maxSpent) * 100;
  } else if (c.spent > c.budget) {
    fillPct = 100;
    tickPct = (c.budget / c.spent) * 100;
  } else {
    fillPct = (c.spent / c.budget) * 100;
  }
  const figures = c.budget === null
    ? [h('b', {}, formatInr(c.spent)), ' spent']
    : [h('b', {}, formatInr(c.spent)), ` of ${formatInr(c.budget)}`];

  return h('li', { class: `status-${c.status}` },
    h('div', { class: 'bar-head' },
      h('span', { class: 'bar-name' }, c.category),
      h('span', { class: 'bar-figures' }, ...figures, ' ', h('span', { class: 'bar-status' }, STATUS_TEXT[c.status])),
    ),
    h('div', { class: 'track', 'aria-hidden': 'true' },
      h('div', { class: 'fill', style: { width: `${Math.min(100, Math.max(0, fillPct)).toFixed(1)}%` } }),
      tickPct === null ? null : h('div', { class: 'tick', style: { left: `${tickPct.toFixed(1)}%` } }),
    ),
  );
}

/* ---------- uploading receipts ---------- */

async function shrinkImage(file, maxSide = 1600) {
  // Smaller uploads are faster and cheaper to read. Fall back to the original on any problem.
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 800000 && file.type === 'image/jpeg') { bitmap.close(); return file; }
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch (_) {
    return file;
  }
}

async function handleFiles(fileList) {
  const files = [...fileList].filter((f) => /^image\/(jpeg|png|webp)$/.test(f.type));
  $('problems').replaceChildren();
  if (files.length === 0) { setStatus('Choose JPEG, PNG or WebP images.', true); return; }
  if (!state.config.extraction_enabled) {
    setStatus('Reading receipts is not set up on this server. Add the expenses by hand instead.', true);
    return;
  }

  let added = 0; let imageNumber = 0;
  const problems = [];
  const size = state.config.max_files;
  for (let start = 0; start < files.length; start += size) {
    const batch = files.slice(start, start + size);
    setStatus(`Reading ${files.length === 1 ? 'your image' : `images ${start + 1} to ${start + batch.length} of ${files.length}`}...`);
    try {
      const form = new FormData();
      for (const file of batch) form.append('files', await shrinkImage(file), 'receipt');
      const response = await fetch('/api/extract', { method: 'POST', body: form });
      if (!response.ok) throw new Error(await readError(response, 'Could not read the images. Please try again.'));
      const { results } = await response.json();
      for (const r of results) {
        imageNumber += 1;
        if (r.ok) { addExpense(r.expense); added += 1; } else problems.push(`Image ${imageNumber}: ${r.error}`);
      }
    } catch (err) {
      setStatus(err.message, true);
      imageNumber += batch.length;
      problems.push(`Images ${imageNumber - batch.length + 1} to ${imageNumber} were not read.`);
    }
  }

  setStatus(added ? `Added ${added} ${added === 1 ? 'expense' : 'expenses'}. Check the details below.` : 'No expenses were added.', added === 0);
  $('problems').replaceChildren(...problems.map((p) => h('li', {}, p)));
  renderAll();
}

/* ---------- manual entry, sample data, CSV ---------- */

async function handleManual(event) {
  event.preventDefault();
  const vendor = $('m-vendor').value.trim();
  const amount = parseFloat($('m-amount').value);
  if (!vendor || !Number.isFinite(amount) || amount <= 0) {
    setStatus('Enter a vendor and an amount above zero.', true);
    return;
  }
  let category = $('m-category').value;
  if (!category) {
    try {
      const response = await fetch(`/api/categorize?vendor=${encodeURIComponent(vendor)}`);
      category = response.ok ? (await response.json()).category : 'Other';
    } catch (_) { category = 'Other'; }
  }
  addExpense({ vendor, amount, date: $('m-date').value, category });
  event.target.reset();
  setStatus(`Added ${vendor}.`);
  renderAll();
}

function loadSample() {
  const now = new Date();
  const ym = todayIso().slice(0, 7);
  const day = (n) => `${ym}-${String(Math.min(n, now.getDate())).padStart(2, '0')}`;
  const rows = [
    ['Swiggy', 349, 'Food & Dining', 2], ['Zomato', 612, 'Food & Dining', 6], ['श्री बेकरी', 180, 'Food & Dining', 9],
    ['BigBasket', 1840, 'Groceries', 3], ['किराणा स्टोअर', 520, 'Groceries', 8],
    ['Uber', 260, 'Transport', 4], ['Rapido', 190, 'Transport', 7],
    ['Jio Recharge', 299, 'Bills & Utilities', 5], ['Mahavitaran Electricity', 1450, 'Bills & Utilities', 10],
    ['Apollo Pharmacy', 740, 'Health', 11], ['Netflix', 649, 'Entertainment', 1], ['Amazon', 2199, 'Shopping', 12],
  ];
  rows.forEach(([vendor, amount, category, d]) => addExpense({ vendor, amount, category, date: day(d) }));
  Object.assign(state.budgets, {
    'Food & Dining': 1500, 'Groceries': 3000, 'Transport': 800, 'Bills & Utilities': 2200,
    'Health': 1000, 'Entertainment': 500, 'Shopping': 2000,
  });
  setStatus('Sample data added. Change anything you like.');
  renderAll();
}

function csvCell(value) {
  let text = String(value ?? '');
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; // stop spreadsheet formula injection
  return `"${text.replace(/"/g, '""')}"`;
}

function exportCsv() {
  const rows = state.expenses.filter(isValid);
  if (rows.length === 0) { setStatus('There is nothing to download yet.', true); return; }
  const lines = [['Vendor', 'Amount (INR)', 'Date', 'Category'].map(csvCell).join(',')];
  rows.forEach((e) => lines.push([e.vendor, e.amount, e.date, e.category].map(csvCell).join(',')));
  const blob = new Blob(['\uFEFF' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = h('a', { href: url, download: 'expenses.csv' });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/* ---------- start-up ---------- */

function renderAll() {
  renderMonths();
  renderRows();
  runAnalysis();
}

async function init() {
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('config');
    state.config = await response.json();
  } catch (_) {
    setStatus('Could not reach the server. Please reload the page.', true);
    return;
  }

  $('limit-files').textContent = state.config.max_files;
  const manualSelect = $('m-category');
  state.config.categories.forEach((c) => manualSelect.append(h('option', { value: c }, c)));

  $('file').addEventListener('change', (e) => { handleFiles(e.target.files); e.target.value = ''; });
  const drop = $('drop');
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => handleFiles(e.dataTransfer.files));

  $('manual-form').addEventListener('submit', handleManual);
  $('sample').addEventListener('click', loadSample);
  $('export').addEventListener('click', exportCsv);
  $('clear').addEventListener('click', () => {
    if (state.expenses.length && !window.confirm('Remove all expenses from this page?')) return;
    state.expenses = [];
    state.monthChosen = false;
    setStatus('');
    $('problems').replaceChildren();
    renderAll();
  });
  $('month').addEventListener('change', (e) => { state.month = e.target.value; state.monthChosen = true; runAnalysis(); });

  if (!state.config.extraction_enabled) {
    setStatus('Receipt reading is switched off on this server. You can still add expenses by hand.');
  }
  renderBudgetInputs();
  renderAll();
}

document.addEventListener('DOMContentLoaded', init);
