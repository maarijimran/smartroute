// SmartRoute: routing techniques, simulated step by step.
// Run: node techdeck.js <output.pptx>   (NODE_PATH -> deck/node_modules, PPTX_SKILL set)
const pptxgen = require("pptxgenjs");
const JSZip = require("jszip");
const fs = require("fs");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = process.argv[2];

/* ================================================================ theme (same as the jury deck) */
const THEME = {
  name: "SmartRoute",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "262624", lt1: "FAF9F5", dk2: "3D3D3A", lt2: "F0EEE6",
    accent1: "3B7D55", // local (green)
    accent2: "D97757", // terracotta, highlight, fast tier
    accent3: "AE5630", // deep terracotta, strong tier
    accent4: "BF4034", // blocked (red)
    accent5: "73726C", // muted
    accent6: "C08A2E", // amber
    hlink: "D97757", folHlink: "AE5630",
  },
};
const HEX = { card: "FFFFFF", line: "E5E2D8", sand: "F0EEE6", ivory: "FAF9F5", ink: "262624", muted: "73726C", faint: "9C9A92",
  L: "3B7D55", F: "C96442", S: "AE5630", red: "BF4034", amber: "C08A2E", terra: "D97757" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "SmartRoute: routing techniques, simulated";
pres.author = "Aman Malik, Muhammad Maarij, Syed Tuaha Ahmed";
pres.company = "FAST NUCES Karachi";
const C = pres.SchemeColor;
const SH = pres.shapes;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: HEX.ink },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.9, w: 8.6, h: 1.4, fontSize: 50, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.45, w: 7.6, h: 1.2, fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SIM",
  background: { color: HEX.ivory },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.36, w: 8.3, h: 0.72, fontSize: 36, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 1.08, w: 8.3, h: 0.45, fontSize: 16, color: C.text2, valign: "top", margin: 0 }, text: "" } },
    { text: { text: "SmartRoute · routing techniques, simulated", options: { x: 0.6, y: 7.02, w: 7, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.3, fontSize: 10, color: "73726C", align: "right" },
});

const SECTIONS = new Set();
function addSlide(opts) {
  if (opts.sectionTitle && !SECTIONS.has(opts.sectionTitle)) { pres.addSection({ title: opts.sectionTitle }); SECTIONS.add(opts.sectionTitle); }
  return pres.addSlide(opts);
}

/* ================================================================ text runs: _{sub} ^{sup} **bold** */
function runs(str, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|_\{[^}]*\}|\^\{[^}]*\})/g;
  let last = 0, m;
  while ((m = re.exec(str))) {
    if (m.index > last) out.push({ text: str.slice(last, m.index), options: { ...base } });
    const t = m[0];
    if (t.startsWith("**")) out.push({ text: t.slice(2, -2), options: { ...base, bold: true } });
    else if (t.startsWith("_")) out.push({ text: t.slice(2, -1), options: { ...base, subscript: true } });
    else out.push({ text: t.slice(2, -1), options: { ...base, superscript: true } });
    last = m.index + t.length;
  }
  if (last < str.length) out.push({ text: str.slice(last), options: { ...base } });
  return out;
}
/** lines: strings or {t, color, size, gap} → one text box of paragraphs */
function para(lines, base = {}) {
  const all = [];
  lines.forEach((ln, i) => {
    const l = typeof ln === "string" ? { t: ln } : ln;
    const opt = { ...base, ...(l.color ? { color: l.color } : {}), ...(l.size ? { fontSize: l.size } : {}), ...(l.bold ? { bold: true } : {}) };
    if (l.gap) opt.paraSpaceBefore = l.gap;
    const rs = runs(l.t === "" ? " " : l.t, opt);
    if (i < lines.length - 1) rs[rs.length - 1].options.breakLine = true;
    all.push(...rs);
  });
  return all;
}

/* ================================================================ helpers */
const f = (v, d = 2) => Number(v).toFixed(d);
const usd = (v, d = 4) => "$" + Number(v).toFixed(d);
const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top", ...o });
function box(s, o) {
  s.addShape(o.round === false ? SH.RECTANGLE : SH.ROUNDED_RECTANGLE, {
    x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: o.round === false ? undefined : (o.r ?? 0.08),
    fill: o.fill ?? { color: HEX.card }, line: o.line ?? { color: HEX.line, width: 0.75 }, objectName: o.name,
  });
}
function label(s, text, o) {
  s.addText(typeof text === "string" ? runs(text) : text, {
    shape: o.round === false ? SH.RECTANGLE : SH.ROUNDED_RECTANGLE, rectRadius: o.r ?? 0.08,
    x: o.x, y: o.y, w: o.w, h: o.h, fill: o.fill ?? { color: HEX.card }, line: o.line ?? { color: HEX.line, width: 0.75 },
    fontSize: o.fontSize ?? 14, bold: o.bold ?? false, color: o.color ?? C.text1, italic: o.italic ?? false,
    align: o.align ?? "center", valign: o.valign ?? "middle", margin: o.margin ?? (o.align === "left" ? 8 : 3), objectName: o.name,
  });
}
function line(s, x1, y1, x2, y2, o = {}) {
  s.addShape(SH.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.max(Math.abs(x2 - x1), 0.001), h: Math.max(Math.abs(y2 - y1), 0.001),
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color: o.color ?? HEX.muted, width: o.width ?? 1.5, endArrowType: o.head ? "triangle" : undefined, dashType: o.dash }, objectName: o.name,
  });
}
function dot(s, cx, cy, d, color, name, o = {}) {
  s.addShape(SH.OVAL, { x: cx - d / 2, y: cy - d / 2, w: d, h: d, fill: { color, transparency: o.transparency ?? 0 }, line: o.line ?? { type: "none" }, objectName: name });
}

/* --- frame pieces shared by every simulation slide --- */
const ZONE = { x: 0.6, y: 2.62, w: 5.0, h: 4.13 }; // technique visual
const MCX = 5.85, MCW = 2.55; // model cards
const CALC = { x: 8.75, y: 1.75, w: 3.98, h: 5.0 };

function tracker(s, labels, active) {
  const w = labels.length === 4 ? 0.95 : 1.18, g = 0.06;
  const x0 = 12.73 - labels.length * w - (labels.length - 1) * g;
  box(s, { x: x0 + active * (w + g), y: 0.52, w, h: 0.42, r: 0.2, fill: { color: HEX.terra }, line: { type: "none" }, name: "!!trk-hl" });
  labels.forEach((t, i) => {
    T(s, `${i + 1}  ${t}`, { x: x0 + i * (w + g), y: 0.52, w, h: 0.42, align: "center", valign: "middle", fontSize: 12, bold: i === active,
      color: i === active ? "FFFFFF" : HEX.muted, objectName: `!!trk-${i}` });
  });
}
function stages(s, names, active) {
  const n = names.length, gap = 0.3, w = (7.8 - (n - 1) * gap) / n, y = 1.75, h = 0.62;
  names.forEach((t, i) => {
    const x = 0.6 + i * (w + gap);
    const state = i < active ? "done" : i === active ? "on" : "todo";
    label(s, t, {
      x, y, w, h, r: 0.12, fontSize: n === 5 ? 12 : 13, bold: state === "on",
      fill: state === "on" ? { color: HEX.terra, transparency: 80 } : state === "done" ? { color: HEX.sand } : { color: HEX.card },
      line: state === "on" ? { color: HEX.terra, width: 1.5 } : { color: HEX.line, width: 0.75 },
      color: state === "todo" ? HEX.faint : state === "on" ? HEX.S : C.text1, name: `!!stg-${i}`,
    });
    if (i < n - 1) line(s, x + w + 0.04, y + h / 2, x + w + gap - 0.04, y + h / 2, { head: true, color: HEX.faint, width: 1.25, name: `!!stg-a${i}` });
  });
}
function calc(s, lines) {
  box(s, { ...CALC, name: "!!calc-card" });
  T(s, "Calculation", { x: CALC.x + 0.25, y: CALC.y + 0.2, w: CALC.w - 0.5, h: 0.35, fontSize: 15, bold: true, objectName: "!!calc-h" });
  T(s, para(lines, { fontSize: 14, color: HEX.ink }), { x: CALC.x + 0.25, y: CALC.y + 0.65, w: CALC.w - 0.45, h: CALC.h - 0.85, paraSpaceAfter: 4, objectName: "!!calc" });
}
const MODELS = {
  L: { name: "Llama 3.1 8B", tier: "Local", pin: 0, pout: 0, lat: 3.1, hex: HEX.L },
  F: { name: "Claude Haiku 5.5", tier: "Fast", pin: 0.10, pout: 0.50, lat: 1.9, hex: HEX.F },
  S: { name: "Claude Opus 5.5", tier: "Strong", pin: 4.0, pout: 20.0, lat: 6.2, hex: HEX.S },
};
/** state per model: {st: idle|chosen|excluded|done, note} */
function modelCards(s, states = {}) {
  ["L", "F", "S"].forEach((k, i) => {
    const m = MODELS[k], st = states[k] || { st: "idle" };
    const y = 2.62 + i * 1.38, h = 1.25;
    const chosen = st.st === "chosen", excl = st.st === "excluded", done = st.st === "done";
    const fill = chosen ? { color: m.hex } : excl ? { color: HEX.sand } : { color: HEX.card };
    const line_ = chosen ? { type: "none" } : done ? { color: m.hex, width: 1.5 } : { color: HEX.line, width: 0.75 };
    const ink = chosen ? "FFFFFF" : excl ? HEX.faint : HEX.ink;
    const sub = chosen ? "FFFFFF" : excl ? HEX.faint : HEX.muted;
    const noteColor = chosen ? "FFFFFF" : excl ? HEX.red : done ? m.hex : HEX.muted;
    const price = m.pin ? `$${f(m.pin, 2)}/$${f(m.pout, 2)} per M` : "free";
    s.addText([
      { text: m.name, options: { fontSize: 14, bold: true, color: ink, breakLine: true } },
      { text: `${m.tier} · ${price} · ${m.lat} s`, options: { fontSize: 11, color: sub, breakLine: true } },
      { text: st.note || " ", options: { fontSize: 12, bold: true, color: noteColor } },
    ], { shape: SH.ROUNDED_RECTANGLE, rectRadius: 0.1, x: MCX, y, w: MCW, h, fill, line: line_, align: "left", valign: "middle", margin: 9, objectName: `!!mc-${k}` });
  });
}
/** horizontal bars: rows [{key,label,value,color,txt}] */
function bars(s, rows, o) {
  const { x, y, w, rowH = 0.62, labelW = 1.35, max = 1, valueW = 0.75, prefix = "b" } = o;
  const trackW = w - labelW - valueW - 0.1;
  rows.forEach((r, i) => {
    const yy = y + i * rowH, bh = Math.min(0.36, rowH * 0.6);
    T(s, r.label, { x, y: yy, w: labelW - 0.1, h: bh, valign: "middle", fontSize: 13, bold: !!r.bold, color: r.dim ? HEX.faint : HEX.ink, objectName: `!!${prefix}l-${r.key}` });
    box(s, { x: x + labelW, y: yy, w: trackW, h: bh, r: 0.06, fill: { color: HEX.sand }, line: { type: "none" }, name: `!!${prefix}t-${r.key}` });
    const bw = Math.max(0.04, Math.min(r.value / max, 1) * trackW);
    box(s, { x: x + labelW, y: yy, w: bw, h: bh, r: 0.06, fill: { color: r.color ?? HEX.terra, transparency: r.dim ? 60 : 0 }, line: { type: "none" }, name: `!!${prefix}f-${r.key}` });
    T(s, r.txt ?? f(r.value), { x: x + labelW + trackW + 0.1, y: yy, w: valueW, h: bh, valign: "middle", fontSize: 13, bold: !!r.bold, color: r.dim ? HEX.faint : HEX.ink, objectName: `!!${prefix}v-${r.key}` });
  });
}
/** 0..1 gauge with coloured bands and a pointer */
function gauge(s, o) {
  const { x, y, w, h = 0.34, bands, value, valueTxt, marks = [], hl } = o;
  bands.forEach((b, i) => {
    const bx = x + b.from * w, bw = (b.to - b.from) * w;
    box(s, { x: bx, y, w: bw, h, round: false, fill: { color: b.color, transparency: hl === undefined || hl === i ? 35 : 80 }, line: { color: HEX.ivory, width: 1 }, name: `!!gb-${i}` });
    T(s, b.label, { x: bx, y: y + h + 0.06, w: bw, h: 0.3, align: "center", fontSize: 12, bold: hl === i, color: hl === i ? HEX.ink : HEX.muted, objectName: `!!gbl-${i}` });
  });
  marks.forEach((m, i) => {
    line(s, x + m.at * w, y - 0.12, x + m.at * w, y + h + 0.02, { color: HEX.ink, width: 1.5, dash: "dash", name: `!!gm-${i}` });
    T(s, m.label, { x: x + m.at * w - 0.7, y: y + h + 0.36, w: 1.4, h: 0.28, align: "center", fontSize: 11, color: HEX.ink, objectName: `!!gml-${i}` });
  });
  if (value !== undefined) {
    const px = x + Math.max(0, Math.min(value, 1)) * w;
    s.addShape(SH.ISOSCELES_TRIANGLE, { x: px - 0.13, y: y - 0.3, w: 0.26, h: 0.22, flipV: true, fill: { color: HEX.ink }, line: { type: "none" }, objectName: "!!gp" });
    T(s, valueTxt ?? f(value), { x: px - 0.6, y: y - 0.68, w: 1.2, h: 0.34, align: "center", fontSize: 14, bold: true, objectName: "!!gpl" });
  }
}
function chip(s, text, x, y, w, o = {}) {
  label(s, text, { x, y, w, h: o.h ?? 0.4, r: 0.2, fontSize: o.fontSize ?? 12, bold: o.bold, fill: o.fill ?? { color: HEX.terra, transparency: 82 }, line: o.line ?? { type: "none" }, color: o.color ?? HEX.S, name: o.name });
}
function caption(s, text, o = {}) {
  T(s, text, { x: o.x ?? ZONE.x, y: o.y ?? 6.62, w: o.w ?? 7.8, h: o.h ?? 0.32, fontSize: 11, italic: true, color: HEX.muted, objectName: o.name ?? "!!cap" });
}
function table(s, rows, o) {
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, color: HEX.muted, fill: { color: HEX.sand } } }));
  const body = rows.slice(1).map((r, i) => r.map((t) => ({ text: String(t), options: { bold: o.hl === i, color: o.hl === i ? HEX.S : HEX.ink, fill: { color: o.hl === i ? "F7E3D9" : HEX.card } } })));
  s.addTable([head, ...body], { x: o.x, y: o.y, w: o.w, colW: o.colW, fontSize: o.fontSize ?? 12, rowH: o.rowH ?? 0.34, valign: "middle", margin: 0.05, border: { type: "solid", pt: 0.75, color: HEX.line } });
}

/* ================================================================ the running example */
const IN = 200, OUTT = 410, C_REF = 0.01, L_REF = 10, W = { q: 0.5, c: 0.3, l: 0.2 };
const cost = (k) => (IN * MODELS[k].pin + OUTT * MODELS[k].pout) / 1e6;
const cterm = (c) => 1 - Math.min(c / C_REF, 1);
const lterm = (l) => 1 - Math.min(l / L_REF, 1);
const CT = { L: cterm(cost("L")), F: cterm(cost("F")), S: cterm(cost("S")) };
const LT = { L: lterm(3.1), F: lterm(1.9), S: lterm(6.2) };
const util = (k, q) => W.q * q + W.c * CT[k] + W.l * LT[k];
const Q_TEXT = "Compare dropout and weight decay for a small CNN, analyse the trade-offs and justify which is more robust";
const argmax = (o) => Object.keys(o).reduce((a, b) => (o[b] > o[a] ? b : a));
const NAME = (k) => MODELS[k].name;
const check = (cond, msg) => { if (!cond) throw new Error("check failed: " + msg); };

// 2x2 linear algebra for the bandit examples
const inv2 = (A) => { const d = A[0][0] * A[1][1] - A[0][1] * A[1][0]; return [[A[1][1] / d, -A[0][1] / d], [-A[1][0] / d, A[0][0] / d]]; };
const mv = (A, x) => [A[0][0] * x[0] + A[0][1] * x[1], A[1][0] * x[0] + A[1][1] * x[1]];
const dotv = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const outer = (x) => [[x[0] * x[0], x[0] * x[1]], [x[1] * x[0], x[1] * x[1]]];
const addM = (A, B, k = 1) => [[A[0][0] + k * B[0][0], A[0][1] + k * B[0][1]], [A[1][0] + k * B[1][0], A[1][1] + k * B[1][1]]];
const fm = (A, d = 2) => `[[${f(A[0][0], d)}, ${f(A[0][1], d)}], [${f(A[1][0], d)}, ${f(A[1][1], d)}]]`;
const fv = (v, d = 2) => `[${v.map((x) => f(x, d)).join(", ")}]`;

/* ================================================================ slide builders */
const addDark = (section, title, body, notes) => {
  const s = addSlide({ masterName: "DARK", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (body) s.addText(body, { placeholder: "body" });
  if (notes) s.addNotes(notes);
  return s;
};

/** One technique = several step slides that share names, so Morph animates the change. */
function technique(section, t) {
  t.steps.forEach((st, i) => {
    const s = addSlide({ masterName: "SIM", sectionTitle: section });
    s.addText(t.title, { placeholder: "title" });
    s.addText(t.sub, { placeholder: "body" });
    tracker(s, t.steps.map((x) => x.tab), i);
    stages(s, t.stages, st.stage);
    if (st.models !== false) modelCards(s, st.models || {});
    st.draw(s);
    calc(s, st.calc);
    if (st.cap || t.cap) caption(s, st.cap || t.cap);
    s.addNotes(st.notes);
  });
}

/* ================================================================ 1. title */
{
  const s = addDark("Introduction", "Routing techniques, simulated", "How each routing method reaches its decision, step by step, on one shared example. SmartRoute FYP-I.",
    "This deck walks through every technique on the routing map. Each technique is simulated on the same request and the same three models, so the numbers can be compared. Use the slide-show mode: Morph transitions animate each step.");
  const nodes = [["Local", HEX.L, 1.45], ["Fast", HEX.F, 2.95], ["Strong", HEX.S, 4.45]];
  label(s, "Router", { x: 9.3, y: 2.75, w: 1.45, h: 1.3, fill: { color: "3D3D3A" }, line: { color: HEX.faint, width: 1 }, color: "FFFFFF", bold: true, fontSize: 15, name: "!!t-router" });
  nodes.forEach(([t, c, y], i) => {
    label(s, t, { x: 11.3, y, w: 1.45, h: 0.85, fill: { color: c }, line: { type: "none" }, color: "FFFFFF", bold: true, fontSize: 14, name: `!!t-n${i}` });
    line(s, 10.75, 3.4, 11.3, y + 0.42, { head: true, color: HEX.faint, width: 1.25 });
  });
  line(s, 8.4, 3.4, 9.3, 3.4, { head: true, color: HEX.faint, width: 1.25 });
  T(s, "Request", { x: 8.15, y: 2.95, w: 1.0, h: 0.3, fontSize: 12, color: HEX.faint });
  T(s, "Aman Malik · Muhammad Maarij · Syed Tuaha Ahmed\nSupervisor: Dr. Farrukh Salim Sheikh · FAST NUCES Karachi", { x: 0.7, y: 5.6, w: 8, h: 0.7, fontSize: 13, color: "C2C0B6" });
}

/* ================================================================ 2. running example */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Introduction" });
  s.addText("One request, three models", { placeholder: "title" });
  s.addText("Every simulation uses these numbers, so the techniques can be compared", { placeholder: "body" });
  label(s, [{ text: "Request  ", options: { bold: true, color: HEX.S } }, { text: `“${Q_TEXT}”`, options: { italic: true } }],
    { x: 0.6, y: 1.75, w: 12.13, h: 0.75, align: "left", fontSize: 15, fill: { color: HEX.card }, name: "!!ex-req" });
  T(s, `About ${IN} input tokens and ${OUTT} output tokens.`, { x: 0.6, y: 2.58, w: 6, h: 0.3, fontSize: 12, color: HEX.muted });
  const rows = [["Model", "Tier", "Price in / out (per M tokens)", "Cost of this request", "Cost term c", "Latency", "Latency term l"]];
  ["L", "F", "S"].forEach((k) => {
    const m = MODELS[k];
    rows.push([m.name, m.tier, m.pin ? `$${f(m.pin, 2)} / $${f(m.pout, 2)}` : "free (our GPU)", usd(cost(k), 6), f(CT[k], 3), `${m.lat} s`, f(LT[k], 2)]);
  });
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, color: HEX.muted, fill: { color: HEX.sand } } }));
  const body = rows.slice(1).map((r, i) => r.map((t, j) => ({ text: t, options: { bold: j === 0, color: j === 0 ? [HEX.L, HEX.F, HEX.S][i] : HEX.ink, fill: { color: HEX.card } } })));
  s.addTable([head, ...body], { x: 0.6, y: 3.0, w: 12.13, colW: [2.2, 0.9, 2.45, 1.85, 1.45, 1.4, 1.88], fontSize: 14, rowH: 0.45, valign: "middle", margin: 0.08, border: { type: "solid", pt: 0.75, color: HEX.line } });
  const fy = 5.05;
  box(s, { x: 0.6, y: fy, w: 12.13, h: 1.6, fill: { color: HEX.card } });
  T(s, para([
    { t: "**Reward**   R = 0.5·Q + 0.3·c + 0.2·l", size: 18 },
    { t: `c = 1 − min(C / C_{ref}, 1)    l = 1 − min(L / L_{ref}, 1)    with C_{ref} = $${f(C_REF, 2)} (calibrated near the strong model's cost) and L_{ref} = ${L_REF} s`, size: 14, gap: 6 },
    { t: "Q is answer quality in [0, 1]. Cost and latency are calculated; methods that learn only predict Q (SmartRoute's “split” mode).", size: 14, color: HEX.muted, gap: 4 },
  ]), { x: 0.85, y: fy + 0.18, w: 11.6, h: 1.3 });
  s.addNotes("This is the shared example. The request is a hard comparison question. The three models are the ones seeded in SmartRoute. Cost and latency terms are computed once here; every later slide reuses them. C_ref is set to one cent, close to the strong model's cost per request, as the calibration finding in PROGRESS.md recommends.");
}

/* ================================================================ 3. map */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Introduction" });
  s.addText("The routing map", { placeholder: "title" });
  s.addText("Four families; hard limits always run first. Each item gets its own simulation", { placeholder: "body" });
  const cols = [
    ["A · Decide before answering", HEX.S, ["1 Rules / heuristics", "2 Semantic routes", "3 kNN on past outcomes", "4 Difficulty classifier", "5 Quality + cost predictor", "6 Preference-trained", "7 Contrastive / graph", "8 LLM as router"]],
    ["B · Decide after a try", HEX.amber, ["9 Cheap first, escalate", "10 Self-verification"]],
    ["C · Keep learning online", HEX.L, ["11 Epsilon-greedy", "12 LinUCB / Thompson", "13 RL multi-step"]],
    ["D · Hard limits (filters)", HEX.red, ["Privacy gate", "Context window fit", "Hardware / health", "Budget pacing"]],
  ];
  const cw = 2.85, gap = 0.243;
  cols.forEach(([h, c, items], i) => {
    const x = 0.6 + i * (cw + gap);
    label(s, h, { x, y: 1.8, w: cw, h: 0.62, fill: { color: c }, line: { type: "none" }, color: "FFFFFF", bold: true, fontSize: 14, name: `!!map-h${i}` });
    items.forEach((t, j) => label(s, t, { x, y: 2.58 + j * 0.5, w: cw, h: 0.42, fontSize: 13, align: "left", fill: { color: HEX.card }, line: { color: c, width: 1 }, name: `!!map-${i}-${j}` }));
  });
  label(s, "SmartRoute uses D (all four limits) + A1 and A5 as baselines + C11 as the main method; C12 is the stretch goal", { x: 3.7, y: 5.25, w: 9.03, h: 0.62, fill: { color: HEX.terra, transparency: 85 }, line: { type: "none" }, bold: true, fontSize: 14, color: HEX.S });
  s.addNotes("The map from the research guide. A predicts before answering, B tries a cheap answer first and escalates, C keeps learning from feedback, and D removes models that are not allowed before any of them chooses. SmartRoute's main method is C11 behind the D filters, with A1 and A5 as baselines.");
}

/* ================================================================ A. predictive routing */
addDark("A · Before answering", "A · Decide before answering", "Predict the best model from the request alone, then send it once: 1 Rules · 2 Semantic routes · 3 kNN · 4 Difficulty classifier · 5 Quality + cost predictor · 6 Preference-trained · 7 Contrastive / graph · 8 LLM as router",
  "Predictive routers look only at the request. They are fast and make one model call, but they can only be as good as their prediction.");

/* A1 rules */
{
  const words = Q_TEXT.split(/\s+/).length;
  const hardWords = ["compare", "analyse", "trade-offs", "justify", "robust"];
  const hard = Math.min(hardWords.length, 3), easy = 0;
  const lenT = 0.10 * Math.min(Math.log1p(words) / Math.log1p(120), 1);
  const tokT = 0.10 * Math.min(Math.log1p(IN) / Math.log1p(8000), 1);
  const d = 0.25 + 0.12 * hard - 0.10 * easy + lenT + tokT;
  check(d >= 0.6, "A1 difficulty");
  const segs = [["Base", 0.25, HEX.faint], ["Hard", 0.12 * hard, HEX.terra], ["Length", lenT, HEX.amber], ["Tokens", tokT, HEX.L]];
  const drawSegs = (s, show) => {
    let x = ZONE.x;
    segs.forEach(([lab, v, c], i) => {
      const w = show ? v * 4.6 : 0.04;
      box(s, { x, y: 4.55, w, h: 0.5, round: false, fill: { color: c }, line: { color: HEX.ivory, width: 1 }, name: `!!a1-seg${i}` });
      if (show) { box(s, { x: ZONE.x + i * 1.25, y: 5.3, w: 0.2, h: 0.2, round: false, fill: { color: c }, line: { type: "none" }, name: `!!a1-sw${i}` }); T(s, `${lab} ${f(v, 3)}`, { x: ZONE.x + i * 1.25 + 0.27, y: 5.24, w: 1.0, h: 0.32, fontSize: 11, color: HEX.ink, objectName: `!!a1-sl${i}` }); }
      x += w;
    });
  };
  technique("A · Before answering", {
    title: "A1 · Rules and heuristics", sub: "Hand-written features and thresholds pick a tier; no training needed",
    stages: ["Request", "Features", "Difficulty", "Rule table", "Model"],
    cap: "SmartRoute baseline (policies.py: RulesPolicy). Same regexes as the gateway.",
    steps: [
      {
        tab: "Features", stage: 1,
        draw: (s) => {
          label(s, [{ text: `“${Q_TEXT}”`, options: { italic: true } }], { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 1.0, align: "left", fontSize: 13, name: "!!a1-req" });
          T(s, "Hard-word matches", { x: ZONE.x, y: 3.78, w: 3, h: 0.3, fontSize: 12, bold: true, color: HEX.muted });
          hardWords.forEach((w, i) => chip(s, w, ZONE.x + i * 1.0, 4.12, 0.92, { name: `!!a1-chip${i}` }));
          table(s, [["Feature", "Value"], ["Words", words], ["Hard words (cap 3)", `${hardWords.length} → ${hard}`], ["Easy words", easy], ["Input tokens", IN]], { x: ZONE.x, y: 4.7, w: 3.4, colW: [2.2, 1.2], rowH: 0.36 });
        },
        calc: [
          `words = ${words}`, `hard hits = ${hardWords.length} → min(5, 3) = ${hard}`, `easy hits = ${easy}`, `tokens_{in} = ${IN}`, "",
          { t: "Regexes look for words like compare, analyse, justify (hard) and define, list (easy).", color: HEX.muted, size: 13 },
        ],
        notes: "Step 1. The rules router only looks at surface features. Five hard words are found, capped at three so that one long question cannot dominate. The request has no easy words and about 200 input tokens.",
      },
      {
        tab: "Score", stage: 2,
        draw: (s) => {
          gauge(s, { x: ZONE.x, y: 3.5, w: 4.6, bands: [{ from: 0, to: 0.6, label: "below 0.6", color: HEX.faint }, { from: 0.6, to: 1, label: "complex", color: HEX.S }], value: d, valueTxt: `d = ${f(d)}`, marks: [{ at: 0.6, label: "threshold 0.6" }] });
          drawSegs(s, true);
        },
        calc: [
          "d = 0.25 + 0.12·min(hard, 3)", "    − 0.10·min(easy, 2)", "    + 0.10·ln(1+words) / ln 121", "    + 0.10·ln(1+tok) / ln 8001", "",
          `d = 0.25 + ${f(0.12 * hard)} − 0 + ${f(lenT, 3)} + ${f(tokT, 3)}`, `**d = ${f(d, 3)}**`,
        ],
        notes: `Step 2. The features become one difficulty score between 0 and 1. Here it is ${f(d)}, mostly because of the three capped hard words. The coloured bar shows how much each part contributes.`,
      },
      {
        tab: "Decide", stage: 4,
        models: { L: { st: "idle", note: "3rd choice" }, F: { st: "idle", note: "2nd choice" }, S: { st: "chosen", note: `Chosen · ${usd(cost("S"))}` } },
        draw: (s) => {
          table(s, [["Rule", "When", "Order"], ["Short explanation", "explain & tok < 300", "Local → Fast → Strong"], ["Complex", "d ≥ 0.6 or tok > 6000", "Strong → Fast → Local"], ["Summary", "summarise", "Fast → Local → Strong"], ["Default", "otherwise", "Fast → Strong → Local"]],
            { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.45, 1.75, 1.8], hl: 1, rowH: 0.42, fontSize: 12 });
          label(s, `d = ${f(d)} ≥ 0.6 → rule “Complex” → first eligible: Strong`, { x: ZONE.x, y: 4.95, w: ZONE.w, h: 0.62, fill: { color: HEX.terra, transparency: 85 }, line: { type: "none" }, bold: true, fontSize: 13, color: HEX.S, name: "!!a1-res" });
        },
        calc: [
          `d = ${f(d)} ≥ 0.60 → rule “Complex”`, "order: Strong → Fast → Local", "first eligible = Strong", "",
          `C = (200·4 + 410·20) / 10^{6}`, `**C = ${usd(cost("S"))}**  ·  L ≈ 6.2 s`, "",
          { t: "If Strong were blocked by a hard limit, the next tier in the order would answer.", color: HEX.muted, size: 13 },
        ],
        notes: "Step 3. The rule table is checked in order. The complex rule fires, so the strong model answers. Rules are transparent and cheap, but they never learn: a request that looks hard but is easy still pays the strong price.",
      },
    ],
  });
}

/* A2 semantic routes */
{
  const norm = (v) => Math.sqrt(dotv(v, v));
  const cos = (a, b) => dotv(a, b) / (norm(a) * norm(b));
  const q = [0.20, 0.90, 0.40];
  const routes = [
    { key: "d", name: "Definitions", model: "L", c: [0.90, 0.30, 0.10], ex: "“What is overfitting?” · “Define recall”" },
    { key: "s", name: "Summaries", model: "F", c: [0.25, 0.30, 0.90], ex: "“Summarise section 3” · “Key points”" },
    { key: "a", name: "Analysis", model: "S", c: [0.15, 0.95, 0.30], ex: "“Compare X and Y” · “Critique the method”" },
  ];
  routes.forEach((r) => (r.cos = cos(q, r.c)));
  const best = routes.reduce((a, b) => (b.cos > a.cos ? b : a));
  const TAU = 0.80;
  check(best.key === "a" && best.cos >= TAU, "A2 best route");
  const a = routes[2];
  technique("A · Before answering", {
    title: "A2 · Semantic routes", sub: "Compare the request's embedding with example requests for each route",
    stages: ["Examples", "Embed", "Cosine", "Threshold", "Model"],
    cap: "Based on embedding routers such as the semantic-router library. 3 dimensions shown; real embeddings have 384–1024.",
    steps: [
      {
        tab: "Routes", stage: 0,
        draw: (s) => routes.forEach((r, i) => {
          label(s, [{ text: `${r.name} → ${MODELS[r.model].tier}`, options: { bold: true, breakLine: true } }, { text: r.ex, options: { fontSize: 12, color: HEX.muted, breakLine: true } }, { text: `centroid c = ${fv(r.c)}`, options: { fontSize: 12 } }],
            { x: ZONE.x, y: ZONE.y + i * 1.3, w: ZONE.w, h: 1.15, align: "left", fontSize: 14, name: `!!a2-r${i}` });
        }),
        calc: ["Each route has a few example requests.", "Embed every example, then average:", "c_{route} = mean(e_{1}, …, e_{n})", "", { t: "Routes are written by people; adding a route needs only examples, no retraining.", color: HEX.muted, size: 13 }],
        notes: "Step 1. A semantic router starts from a handful of example requests per route. Each example is embedded and the embeddings are averaged into one centroid per route.",
      },
      {
        tab: "Compare", stage: 2,
        draw: (s) => {
          chip(s, `q = embed(request) = ${fv(q)}`, ZONE.x, ZONE.y, ZONE.w, { h: 0.5, fontSize: 13, name: "!!a2-q" });
          bars(s, routes.map((r) => ({ key: r.key, label: r.name, value: r.cos, color: MODELS[r.model].hex, txt: f(r.cos, 3) })), { x: ZONE.x, y: 3.55, w: ZONE.w, rowH: 0.75, prefix: "a2" });
        },
        calc: [
          "cos(q, c) = q·c / (‖q‖·‖c‖)", "", `Analysis: q·c = ${f(dotv(q, a.c), 3)}`, `‖q‖ = ${f(norm(q), 3)},  ‖c‖ = ${f(norm(a.c), 3)}`, `cos = **${f(a.cos, 3)}**`, "",
          ...routes.slice(0, 2).map((r) => `${r.name}: ${f(r.cos, 3)}`),
        ],
        notes: "Step 2. The request is embedded with the same model, and its cosine similarity to each centroid is computed. The analysis route is far closer than the others.",
      },
      {
        tab: "Decide", stage: 4,
        models: { S: { st: "chosen", note: `Route “Analysis” · ${usd(cost("S"))}` } },
        draw: (s) => {
          chip(s, `q = embed(request) = ${fv(q)}`, ZONE.x, ZONE.y, ZONE.w, { h: 0.5, fontSize: 13, name: "!!a2-q" });
          bars(s, routes.map((r) => ({ key: r.key, label: r.name, value: r.cos, color: MODELS[r.model].hex, txt: f(r.cos, 3), bold: r === best, dim: r !== best })), { x: ZONE.x, y: 3.55, w: ZONE.w, rowH: 0.75, prefix: "a2" });
          const tx = ZONE.x + 1.35 + TAU * (ZONE.w - 1.35 - 0.85);
          line(s, tx, 3.4, tx, 5.75, { color: HEX.ink, dash: "dash", name: "!!a2-tau" });
          T(s, `τ = ${TAU}`, { x: tx - 0.5, y: 5.8, w: 1, h: 0.3, align: "center", fontSize: 12, bold: true, objectName: "!!a2-taul" });
        },
        calc: [`best = Analysis (${f(best.cos, 3)})`, `${f(best.cos, 3)} ≥ τ = ${TAU} → use route`, "Analysis → Strong", "", "If no route clears τ:", "→ default route (Fast)", "", `**C = ${usd(cost("S"))}**`],
        notes: "Step 3. The best route must clear a confidence threshold. It does, so the request goes to the strong model. A request that matches no route well falls back to the default.",
      },
    ],
  });
}

/* A3 kNN */
{
  const past = [
    { id: "P1", x: 0.15, y: 0.20, t: "Define precision", q: [0.82, 0.84, 0.86] },
    { id: "P2", x: 0.28, y: 0.32, t: "What is a CNN?", q: [0.80, 0.83, 0.85] },
    { id: "P3", x: 0.25, y: 0.78, t: "Summarise the paper", q: [0.55, 0.78, 0.80] },
    { id: "P4", x: 0.72, y: 0.18, t: "List the datasets", q: [0.75, 0.80, 0.79] },
    { id: "P5", x: 0.42, y: 0.82, t: "Compare Adam and SGD", q: [0.40, 0.62, 0.74], up: true },
    { id: "P6", x: 0.86, y: 0.58, t: "Critique the ablation", q: [0.35, 0.58, 0.76] },
    { id: "P7", x: 0.80, y: 0.92, t: "Contrast BN and LN", q: [0.42, 0.64, 0.71], up: true },
    { id: "P8", x: 0.90, y: 0.38, t: "Explain the loss", q: [0.70, 0.79, 0.81] },
  ];
  const qp = { x: 0.62, y: 0.68 };
  past.forEach((p) => (p.d = Math.hypot(p.x - qp.x, p.y - qp.y)));
  const nn = [...past].sort((a, b) => a.d - b.d).slice(0, 3);
  const avg = [0, 1, 2].map((i) => nn.reduce((s, p) => s + p.q[i], 0) / 3);
  const R = { L: util("L", avg[0]), F: util("F", avg[1]), S: util("S", avg[2]) };
  const win = argmax(R);
  const PX = (x) => ZONE.x + 0.3 + x * 4.4, PY = (y) => 6.45 - y * 3.55;
  const scatter = (s, showNN) => {
    box(s, { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 4.0, fill: { color: HEX.card }, name: "!!a3-frame" });
    past.forEach((p) => {
      const isN = showNN && nn.includes(p);
      dot(s, PX(p.x), PY(p.y), isN ? 0.26 : 0.2, isN ? HEX.terra : HEX.faint, `!!a3-${p.id}`);
      T(s, p.t, { x: PX(p.x) - 0.9, y: p.up ? PY(p.y) - 0.42 : PY(p.y) + 0.14, w: 1.8, h: 0.26, align: "center", fontSize: 10, color: isN ? HEX.S : HEX.muted, bold: isN, objectName: `!!a3-l${p.id}` });
    });
  };
  technique("A · Before answering", {
    title: "A3 · kNN on past outcomes", sub: "Find the most similar past requests and copy what worked for them",
    stages: ["Request", "Embed", "k nearest", "Average", "Model"],
    cap: "Based on kNN routing over benchmark outcomes (e.g. Shnitzer et al., 2023). 2-D projection shown.",
    steps: [
      {
        tab: "Place", stage: 1,
        draw: (s) => { scatter(s, false); dot(s, PX(qp.x), PY(qp.y), 0.3, HEX.ink, "!!a3-q"); T(s, "new request", { x: PX(qp.x) - 0.65, y: PY(qp.y) + 0.18, w: 1.3, h: 0.3, align: "center", fontSize: 11, bold: true, objectName: "!!a3-ql" }); },
        calc: ["Every past request is stored with its embedding and the quality each model scored on it.", "", "The new request is embedded into the same space.", "", { t: "Grey points: logged requests (8 shown).", color: HEX.muted, size: 13 }],
        notes: "Step 1. kNN keeps a memory of past requests and the quality each model achieved. The new request is embedded into the same space as those past requests.",
      },
      {
        tab: "Neighbours", stage: 2,
        draw: (s) => {
          scatter(s, true);
          nn.forEach((p, i) => line(s, PX(qp.x), PY(qp.y), PX(p.x), PY(p.y), { color: HEX.terra, width: 1.5, dash: "dash", name: `!!a3-nn${i}` }));
          dot(s, PX(qp.x), PY(qp.y), 0.3, HEX.ink, "!!a3-q");
          T(s, "new request", { x: PX(qp.x) - 0.65, y: PY(qp.y) + 0.18, w: 1.3, h: 0.3, align: "center", fontSize: 11, bold: true, objectName: "!!a3-ql" });
        },
        calc: ["k = 3 nearest (distance in the plot):", ...nn.map((p) => `${p.t}: d = ${f(p.d, 3)}`), "", "Their observed quality (L / F / S):", ...nn.map((p) => `${p.q.map((v) => f(v)).join(" / ")}`)],
        notes: "Step 2. The three closest past requests are all comparison or critique questions. Their logged quality per model is read from the outcome table.",
      },
      {
        tab: "Decide", stage: 4,
        models: { L: { st: "idle", note: `R′ = ${f(R.L, 3)}` }, F: { st: win === "F" ? "chosen" : "idle", note: `R′ = ${f(R.F, 3)}` }, S: { st: win === "S" ? "chosen" : "idle", note: `R′ = ${f(R.S, 3)}` } },
        draw: (s) => {
          table(s, [["Neighbour", "Q_L", "Q_F", "Q_S"], ...nn.map((p) => [p.t, f(p.q[0]), f(p.q[1]), f(p.q[2])]), ["Mean", f(avg[0], 3), f(avg[1], 3), f(avg[2], 3)]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [2.3, 0.9, 0.9, 0.9], hl: 3, rowH: 0.38 });
          bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: MODELS[k].tier, value: R[k], color: MODELS[k].hex, txt: f(R[k], 3), bold: k === win, dim: k !== win })), { x: ZONE.x, y: 4.75, w: ZONE.w, rowH: 0.62, prefix: "a3" });
        },
        calc: ["Q_{avg} = mean of neighbours' quality", "R′ = 0.5·Q_{avg} + 0.3·c + 0.2·l", "", ...["L", "F", "S"].map((k, i) => `${MODELS[k].tier}: 0.5·${f(avg[i], 3)} + 0.3·${f(CT[k], 3)} + 0.2·${f(LT[k], 2)} = **${f(R[k], 3)}**`)],
        notes: `Step 3. Averaging the neighbours gives an expected quality per model. Adding the calculated cost and latency terms, the fast model has the best expected reward (${f(R.F, 3)}), because the strong model's small quality lead does not pay for its cost.`,
      },
    ],
  });
}

/* A4 difficulty classifier */
{
  const feats = [["Hard words (cap 3)", 3, 0.9], ["Words / 50", 18 / 50, 0.8], ["Comparison task", 1, 1.1], ["Extra question marks", 0, 0.3], ["Domain terms", 2, 0.4]];
  const b = -2.6;
  const z = b + feats.reduce((s, [, x, w]) => s + x * w, 0);
  const p = 1 / (1 + Math.exp(-z));
  check(p > 0.65, "A4 p");
  const bands = [{ from: 0, to: 0.35, label: "Local", color: HEX.L }, { from: 0.35, to: 0.65, label: "Fast", color: HEX.F }, { from: 0.65, to: 1, label: "Strong", color: HEX.S }];
  technique("A · Before answering", {
    title: "A4 · Difficulty classifier", sub: "A trained classifier estimates how hard the request is; bands map difficulty to a tier",
    stages: ["Request", "Features", "σ(w·x + b)", "Bands", "Model"],
    cap: "Related: Hybrid LLM (Ding et al., ICLR 2024); NVIDIA prompt task and complexity classifier.",
    steps: [
      {
        tab: "Features", stage: 1,
        draw: (s) => table(s, [["Feature", "x", "w", "w·x"], ...feats.map(([n, x, w]) => [n, f(x), f(w), f(x * w, 3)]), ["Bias b", "", "", f(b)]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [2.3, 0.85, 0.85, 1.0], rowH: 0.42 }),
        calc: ["Weights w and bias b come from training:", "label = 1 if the fast model's answer scored below 0.7 on that request", "", "loss = binary cross-entropy", { t: "Training data: the benchmark outcomes (360 train requests).", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. A difficulty classifier is a small supervised model. Here it is logistic regression over five features. It was trained on past requests labelled hard when the cheaper model failed on them.",
      },
      {
        tab: "Score", stage: 2,
        draw: (s) => {
          table(s, [["Feature", "x", "w", "w·x"], ...feats.map(([n, x, w]) => [n, f(x), f(w), f(x * w, 3)]), ["Bias b", "", "", f(b)]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [2.3, 0.85, 0.85, 1.0], rowH: 0.3, fontSize: 11 });
          gauge(s, { x: ZONE.x, y: 5.55, w: ZONE.w, bands, value: p, valueTxt: `p = ${f(p, 3)}` });
        },
        calc: [`z = b + Σ w_{i}x_{i}`, `z = ${f(b)} + ${feats.map(([, x, w]) => f(x * w, 2)).join(" + ")}`, `**z = ${f(z, 3)}**`, "", "p(hard) = σ(z) = 1 / (1 + e^{−z})", `**p = ${f(p, 3)}**`],
        notes: `Step 2. The weighted sum gives z = ${f(z, 2)}, and the sigmoid turns it into a probability that the request is hard: ${f(p, 2)}.`,
      },
      {
        tab: "Decide", stage: 4,
        models: { S: { st: "chosen", note: `p = ${f(p, 2)} · ${usd(cost("S"))}` } },
        draw: (s) => {
          T(s, `p(hard) = ${f(p, 3)}`, { x: ZONE.x, y: ZONE.y + 0.1, w: ZONE.w, h: 0.9, fontSize: 40, bold: true, color: HEX.S, objectName: "!!a4-big" });
          gauge(s, { x: ZONE.x, y: 5.55, w: ZONE.w, bands, value: p, valueTxt: `p = ${f(p, 3)}`, hl: 2 });
        },
        calc: ["Bands:", "p < 0.35 → Local", "0.35 ≤ p < 0.65 → Fast", "p ≥ 0.65 → Strong", "", `${f(p, 3)} ≥ 0.65 → **Strong**`, `C = ${usd(cost("S"))}`, "", { t: "Moving the band edges trades quality for cost.", color: HEX.muted, size: 13 }],
        notes: "Step 3. Fixed bands turn the probability into a tier. Moving the band edges is how an operator trades quality for cost without retraining.",
      },
    ],
  });
}

/* A5 quality + cost predictor (frozen ridge) */
{
  const x = [1, 0.73, 1, 0.36, 0, 0];
  const xl = ["bias", "difficulty", "analysis", "length", "doc", "follow"];
  const th = { L: [0.70, -0.35, -0.05, -0.05, 0.02, 0.00], F: [0.78, -0.12, -0.02, -0.02, 0.03, 0.01], S: [0.85, 0.02, 0.01, 0.00, 0.02, 0.00] };
  const Qh = { L: dotv(th.L, x), F: dotv(th.F, x), S: dotv(th.S, x) };
  const R = { L: util("L", Qh.L), F: util("F", Qh.F), S: util("S", Qh.S) };
  const win = argmax(R);
  const xChips = (s) => x.forEach((v, i) => chip(s, `${xl[i]}\n${f(v)}`, ZONE.x + i * 0.84, ZONE.y, 0.78, { h: 0.7, fontSize: 11, name: `!!a5-x${i}` }));
  technique("A · Before answering", {
    title: "A5 · Quality and cost predictor", sub: "Predict each model's quality, then add the calculated cost and latency",
    stages: ["Request", "Features x", "Predict Q′", "Add c and l", "Model"],
    cap: "SmartRoute's frozen router baseline: ridge regression trained once on the benchmark, then frozen.",
    steps: [
      {
        tab: "Features", stage: 1,
        draw: (s) => {
          xChips(s);
          table(s, [["θ", ...xl], ...["L", "F", "S"].map((k) => [MODELS[k].tier, ...th[k].map((v) => f(v))])], { x: ZONE.x, y: 3.6, w: ZONE.w, colW: [0.8, 0.7, 0.75, 0.7, 0.65, 0.7, 0.7], rowH: 0.38, fontSize: 11 });
        },
        calc: ["x = feature vector of the request", `x = ${fv(x)}`, "", "One weight vector per model:", "θ_{a} = (X^{T}X + λI)^{−1} X^{T} y_{a}", "λ = 1, fitted on 360 train requests", { t: "y_a = the quality model a scored on each train request.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. The request becomes a feature vector. Each model has its own ridge-regression weights, fitted once on the training split of the benchmark and then frozen.",
      },
      {
        tab: "Predict", stage: 2,
        draw: (s) => { xChips(s); bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: `Q′ ${MODELS[k].tier}`, value: Qh[k], color: MODELS[k].hex, txt: f(Qh[k], 3) })), { x: ZONE.x, y: 3.75, w: ZONE.w, rowH: 0.75, prefix: "a5" }); },
        calc: ["Q′_{a} = θ_{a} · x", "", ...["L", "F", "S"].map((k) => `Q′_{${k}} = **${f(Qh[k], 3)}**`), "", { t: "The strong model is predicted to be best on quality alone.", color: HEX.muted, size: 13 }],
        notes: "Step 2. Multiplying weights by features predicts each model's quality. On quality alone, the strong model is clearly ahead.",
      },
      {
        tab: "Decide", stage: 4,
        models: { L: { st: "idle", note: `R′ = ${f(R.L, 3)}` }, F: { st: win === "F" ? "chosen" : "idle", note: `R′ = ${f(R.F, 3)}` }, S: { st: win === "S" ? "chosen" : "idle", note: `R′ = ${f(R.S, 3)}` } },
        draw: (s) => { xChips(s); bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: `R′ ${MODELS[k].tier}`, value: R[k], color: MODELS[k].hex, txt: f(R[k], 3), bold: k === win, dim: k !== win })), { x: ZONE.x, y: 3.75, w: ZONE.w, rowH: 0.75, prefix: "a5" }); },
        calc: ["R′_{a} = 0.5·Q′_{a} + 0.3·c_{a} + 0.2·l_{a}", "", ...["L", "F", "S"].map((k) => `${MODELS[k].tier}: ${f(0.5 * Qh[k], 3)} + ${f(0.3 * CT[k], 3)} + ${f(0.2 * LT[k], 3)} = **${f(R[k], 3)}**`), "", `argmax → **${MODELS[win].tier}**  ·  C = ${usd(cost(win), 6)}`],
        notes: `Step 3. Cost and latency are calculated, not learned, so a price change takes effect immediately. With the proposal's weights, the fast model wins: the strong model is better by ${f(Qh.S - Qh.F, 2)} in quality, which is not enough to pay for its cost.`,
      },
    ],
  });
}

/* A6 preference-trained */
{
  const Rs = 1180, Rf = 1090, K = 32;
  const E = 1 / (1 + Math.pow(10, (Rf - Rs) / 400));
  const Rs2 = Rs + K * (1 - E), Rf2 = Rf - K * (1 - E);
  const pv = [0.8, 0.3, 0.6], vS = [1.1, 0.2, 0.9], vW = [0.4, 0.5, 0.3];
  const sS = dotv(pv, vS), sW = dotv(pv, vW);
  const P = 1 / (1 + Math.exp(-(sS - sW)));
  const ALPHA = 0.6;
  check(P >= ALPHA, "A6 P");
  const dial = [["0.40", "55%"], ["0.50", "42%"], ["0.60", "30%"], ["0.70", "18%"]];
  const g = (s, hl) => gauge(s, { x: ZONE.x, y: 5.6, w: ZONE.w, bands: [{ from: 0, to: ALPHA, label: "Weak (Fast)", color: HEX.F }, { from: ALPHA, to: 1, label: "Strong", color: HEX.S }], value: P, valueTxt: `P = ${f(P, 3)}`, marks: hl ? [{ at: ALPHA, label: `α = ${ALPHA}` }] : [], hl: hl ? 1 : undefined });
  technique("A · Before answering", {
    title: "A6 · Preference-trained router", sub: "Learn from human preferences which model wins on which kind of request",
    stages: ["Battles", "Elo / MF", "P(strong wins)", "Threshold α", "Model"],
    cap: "Based on RouteLLM (Ong et al., 2024): matrix factorisation and Elo routers trained on Chatbot Arena preferences.",
    steps: [
      {
        tab: "Battles", stage: 1,
        draw: (s) => {
          label(s, "Battle: Strong vs Fast on a past request → people preferred Strong", { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 0.6, fontSize: 13, fill: { color: HEX.card }, name: "!!a6-battle" });
          bars(s, [{ key: "S", label: "Elo Strong", value: Rs2, color: HEX.S, txt: f(Rs2, 1) }, { key: "F", label: "Elo Fast", value: Rf2, color: HEX.F, txt: f(Rf2, 1) }], { x: ZONE.x, y: 3.55, w: ZONE.w, rowH: 0.75, max: 1300, prefix: "a6" });
          T(s, "Elo gives one global ranking, the same for every request. The matrix-factorisation router learns a score per request instead.", { x: ZONE.x, y: 5.15, w: ZONE.w, h: 0.9, fontSize: 13, color: HEX.muted, objectName: "!!a6-note" });
        },
        calc: [`Before: R_{S} = ${Rs}, R_{F} = ${Rf}`, "E_{S} = 1 / (1 + 10^{(R_F − R_S)/400})", `E_{S} = ${f(E, 3)}`, "Strong wins → score 1", `R_{S} ← ${Rs} + 32·(1 − ${f(E, 3)}) = **${f(Rs2, 1)}**`, `R_{F} ← ${Rf} − ${f(K * (1 - E), 1)} = **${f(Rf2, 1)}**`],
        notes: "Step 1. Preference routers learn from pairwise battles in which people chose the better answer. The Elo update shown here moves ratings by how surprising the result was.",
      },
      {
        tab: "Score", stage: 2,
        draw: (s) => {
          table(s, [["", "dim 1", "dim 2", "dim 3", "sum"], ["Projected request p", ...pv.map((v) => f(v)), ""], ["p × v_Strong", ...pv.map((v, i) => f(v * vS[i])), f(sS)], ["p × v_Fast", ...pv.map((v, i) => f(v * vW[i])), f(sW)]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.9, 0.75, 0.75, 0.75, 0.85], rowH: 0.42 });
          g(s, false);
        },
        calc: ["s(m, q) = w^{T}(v_{m} × p),  p = W·e_{q}", `s(Strong) = ${f(sS)},  s(Fast) = ${f(sW)}`, "", "P(Strong wins) = σ(s_{S} − s_{F})", `= σ(${f(sS - sW)}) = **${f(P, 3)}**`, { t: "× is element-wise; w = (1, 1, 1) here.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 2. The matrix-factorisation router projects the request and multiplies it, element by element, with a learned vector per model. The difference in scores gives the probability that the strong model would win on this request.",
      },
      {
        tab: "Decide", stage: 4,
        models: { F: { st: "idle", note: "Weak model" }, S: { st: "chosen", note: `P = ${f(P, 2)} ≥ α · ${usd(cost("S"))}` } },
        draw: (s) => {
          table(s, [["Threshold α", "Share sent to Strong"], ...dial], { x: ZONE.x, y: ZONE.y, w: 3.4, colW: [1.5, 1.9], rowH: 0.42, hl: 2 });
          g(s, true);
        },
        calc: [`${f(P, 3)} ≥ α = ${ALPHA} → **Strong**`, "", "α is a cost dial, set on a calibration set:", "α = 0.6 sends 30% of requests to Strong.", "", { t: "Binary router: a weak and a strong model; Local is not part of RouteLLM's setting.", color: HEX.muted, size: 13 }],
        notes: "Step 3. A single threshold alpha decides. It is calibrated so that a chosen share of traffic goes to the strong model, which makes it a simple cost dial.",
      },
    ],
  });
}

/* A7 contrastive / graph */
{
  const T_ = 0.1;
  const sims = { L: 0.31, F: 0.58, S: 0.74 };
  const ex = Object.fromEntries(Object.entries(sims).map(([k, v]) => [k, Math.exp(v / T_)]));
  const Z = ex.L + ex.F + ex.S;
  const pr = { L: ex.L / Z, F: ex.F / Z, S: ex.S / Z };
  // training-time loss for one training query whose best model was S (top-1), others negatives
  const s0 = { L: 0.30, F: 0.15, S: 0.20 };
  const loss0 = -Math.log(Math.exp(s0.S / T_) / (Math.exp(s0.S / T_) + Math.exp(s0.L / T_) + Math.exp(s0.F / T_)));
  const loss1 = -Math.log(ex.S / Z);
  const edges = { L: 0.41, F: 0.63, S: 0.58 };
  const gWin = argmax(edges);
  const space = (s, pos) => {
    box(s, { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 4.0, fill: { color: HEX.card }, name: "!!a7-frame" });
    Object.entries(pos).forEach(([k, [x, y]]) => {
      const isQ = k === "q";
      dot(s, x, y, isQ ? 0.3 : 0.42, isQ ? HEX.ink : MODELS[k].hex, `!!a7-${k}`);
      T(s, isQ ? "query" : runs(`k_{${MODELS[k].tier}}`, { color: MODELS[k].hex }), { x: x - 0.75, y: y + 0.24, w: 1.5, h: 0.3, align: "center", fontSize: 12, bold: true, color: isQ ? HEX.ink : MODELS[k].hex, objectName: `!!a7-l${k}` });
    });
  };
  const before = { q: [3.1, 4.6], L: [2.0, 3.6], F: [4.6, 3.5], S: [4.4, 5.9] };
  const after = { q: [3.1, 4.6], L: [1.2, 3.3], F: [4.3, 4.3], S: [3.75, 5.15] };
  technique("A · Before answering", {
    title: "A7 · Contrastive and graph", sub: "Learn an embedding space where requests sit close to the models that serve them well",
    stages: ["Train pairs", "Contrastive loss", "Similarity", "Graph score", "Model"],
    cap: "Based on RouterDC (Chen et al., NeurIPS 2024) and GraphRouter (Feng et al., ICLR 2025).",
    steps: [
      {
        tab: "Train", stage: 1,
        draw: (s) => {
          space(s, before);
          line(s, before.q[0], before.q[1], before.S[0], before.S[1], { color: HEX.L, head: true, width: 2, name: "!!a7-pull" });
          line(s, before.q[0], before.q[1], before.L[0], before.L[1], { color: HEX.red, head: true, width: 2, dash: "dash", name: "!!a7-push" });
          T(s, "pull to best model", { x: 3.85, y: 4.85, w: 1.9, h: 0.3, fontSize: 11, color: HEX.L, bold: true, objectName: "!!a7-pl" });
          T(s, "push from worst", { x: 0.85, y: 4.45, w: 1.6, h: 0.3, fontSize: 11, color: HEX.red, bold: true, objectName: "!!a7-ps" });
        },
        calc: ["For a training request, the best model (here Strong) is the positive; others are negatives.", "L = −log( e^{s+/T} / Σ e^{s/T} ),  T = 0.1", `Before: s = L ${s0.L}, F ${s0.F}, S ${s0.S}`, `loss = **${f(loss0, 3)}**`],
        notes: "Step 1. A contrastive router trains a request encoder and one embedding per model. The loss pulls a training request towards the model that answered it best and pushes it away from the worst.",
      },
      {
        tab: "Similarity", stage: 2,
        models: { L: { st: "idle", note: `p = ${f(pr.L, 3)}` }, F: { st: "idle", note: `p = ${f(pr.F, 3)}` }, S: { st: "chosen", note: `p = ${f(pr.S, 3)} · RouterDC` } },
        draw: (s) => space(s, after),
        calc: ["After training, for our request:", `s = cos(e_{q}, k_{m}): L ${sims.L}, F ${sims.F}, S ${sims.S}`, "p_{m} = e^{s_m/T} / Σ e^{s/T}", ...["L", "F", "S"].map((k) => `p_{${k}} = ${f(pr[k], 3)}`), `loss now = ${f(loss1, 3)}`, "→ **Strong** (highest p)"],
        notes: "Step 2. After training, the space has moved: the strong model sits next to analysis-style requests. A softmax over similarities picks the strong model with high probability.",
      },
      {
        tab: "Graph", stage: 3,
        models: { L: { st: "idle", note: `edge ${edges.L}` }, F: { st: gWin === "F" ? "chosen" : "idle", note: `edge ${edges.F} · GraphRouter` }, S: { st: gWin === "S" ? "chosen" : "idle", note: `edge ${edges.S}` } },
        draw: (s) => {
          box(s, { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 4.0, fill: { color: HEX.card }, name: "!!a7-frame" });
          const qn = [1.4, 4.6], tn = [1.4, 3.15], mn = { L: [4.4, 3.2], F: [4.4, 4.6], S: [4.4, 6.0] };
          Object.entries(mn).forEach(([k, [x, y]]) => {
            line(s, qn[0], qn[1], x, y, { color: k === gWin ? HEX.F : HEX.faint, width: k === gWin ? 3 : 1.5, name: `!!a7-e${k}` });
            T(s, f(edges[k]), { x: (qn[0] + x) / 2 - 0.3, y: (qn[1] + y) / 2 - 0.32, w: 0.6, h: 0.28, align: "center", fontSize: 12, bold: k === gWin, color: k === gWin ? HEX.F : HEX.muted, objectName: `!!a7-el${k}` });
          });
          line(s, tn[0], tn[1], qn[0], qn[1], { color: HEX.faint, width: 1.5, name: "!!a7-tq" });
          label(s, "task: analysis", { x: tn[0] - 0.85, y: tn[1] - 0.3, w: 1.7, h: 0.5, r: 0.25, fontSize: 12, fill: { color: HEX.sand }, name: "!!a7-task" });
          dot(s, qn[0], qn[1], 0.42, HEX.ink, "!!a7-q");
          T(s, "query", { x: qn[0] - 0.75, y: qn[1] + 0.26, w: 1.5, h: 0.3, align: "center", fontSize: 12, bold: true, objectName: "!!a7-lq" });
          ["L", "F", "S"].forEach((k) => { dot(s, mn[k][0], mn[k][1], 0.42, MODELS[k].hex, `!!a7-${k}`); T(s, MODELS[k].tier, { x: mn[k][0] - 0.75, y: mn[k][1] + 0.24, w: 1.5, h: 0.3, align: "center", fontSize: 12, bold: true, color: MODELS[k].hex, objectName: `!!a7-l${k}` }); });
        },
        calc: ["GraphRouter: nodes = tasks, queries, models; edges carry past effect and cost.", "h_{v} ← σ(W·mean(h_{neighbours}))", "edge score = MLP(h_{q} ⊕ h_{m})", "trained target = quality − β·cost", `scores: L ${edges.L}, F ${edges.F}, S ${edges.S}`, `→ **${MODELS[gWin].tier}** (cost is in the target)`],
        notes: "Step 3. GraphRouter builds a graph of tasks, past queries and models, and a graph neural network predicts the value of each query-to-model edge. Because cost is part of its training target, it prefers the fast model here, unlike the quality-only contrastive router.",
      },
    ],
  });
}

/* A8 LLM as router */
{
  const policies = [["definitions", "Define a term or explain a basic idea", "Local"], ["summarisation", "Summarise a paper or a section", "Fast"], ["deep_analysis", "Compare methods, critique, multi-step reasoning", "Strong"], ["other", "Anything else", "Fast"]];
  technique("A · Before answering", {
    title: "A8 · LLM as router", sub: "A small language model reads route descriptions and names the best route",
    stages: ["Policies", "Prompt", "Router model", "Route name", "Model"],
    cap: "Based on Arch-Router (Katanemo, 2025): a 1.5B model trained to match requests to written route policies.",
    steps: [
      {
        tab: "Policies", stage: 0,
        draw: (s) => table(s, [["Route", "Description", "Model"], ...policies], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.45, 2.75, 0.8], rowH: 0.5 }),
        calc: ["Routes are plain-language policies written by the operator.", "", "Adding a route = adding a row.", "No retraining, no labelled data.", "", { t: "The router model is general: it was trained once to follow such policies.", color: HEX.muted, size: 13 }],
        notes: "Step 1. Routes are described in plain words with the model each should use. This keeps the routing policy readable and editable.",
      },
      {
        tab: "Ask", stage: 2,
        draw: (s) => {
          label(s, "<routes> definitions · summarisation · deep_analysis · other … </routes>\n<conversation> user: Compare dropout and weight decay for a small CNN, analyse the trade-offs and justify which is more robust </conversation>\nReturn the best route as JSON.", { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 2.2, align: "left", valign: "top", fontSize: 12, fill: { color: "1F1E1D" }, line: { type: "none" }, color: "E8E6DC", name: "!!a8-prompt" });
          chip(s, '{ "route": "deep_analysis" }', ZONE.x, 5.05, 3.2, { h: 0.55, fontSize: 14, bold: true, name: "!!a8-out" });
        },
        calc: ["Router prompt ≈ 260 tokens", "Router output = 8 tokens", "1.5B model on our GPU", "Overhead ≈ 50 ms (estimate)", "Cost = $0 (local)", "", { t: "Runs locally, so the request never leaves the server to be routed.", color: HEX.muted, size: 13 }],
        notes: "Step 2. The router model sees the policies and the conversation and answers with a route name in JSON. It is small and runs on our own GPU, so routing adds tens of milliseconds and no API cost.",
      },
      {
        tab: "Decide", stage: 4,
        models: { S: { st: "chosen", note: `deep_analysis · ${usd(cost("S"))}` } },
        draw: (s) => {
          table(s, [["Route", "Description", "Model"], ...policies], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.45, 2.75, 0.8], rowH: 0.5, hl: 2 });
          chip(s, '{ "route": "deep_analysis" }', ZONE.x, 5.05, 3.2, { h: 0.55, fontSize: 14, bold: true, name: "!!a8-out" });
        },
        calc: ["deep_analysis → Strong", `C = ${usd(cost("S"))} + router $0`, "L ≈ 6.2 s + 0.05 s", "", { t: "Weakness: the router can be confidently wrong, and it costs one extra model call per request.", color: HEX.muted, size: 13 }],
        notes: "Step 3. The route name maps to the strong model. The extra model call is cheap here, but it is still one more step on every request.",
      },
    ],
  });
}

/* ================================================================ B. cascades */
addDark("B · After a try", "B · Decide after a try", "Answer with a cheap model first and escalate only when the answer looks weak: 9 Cheap first, escalate · 10 Self-verification",
  "Cascades spend more on hard requests and save on easy ones. Every escalation must still pass the privacy gate.");

/* B9 cascade */
{
  const TAU = 0.70;
  const sc = { L: 0.42, F: 0.64, S: 0.91 };
  const a1 = 0.55, a2 = 0.60;
  const EC = cost("L") + (1 - a1) * cost("F") + (1 - a1) * (1 - a2) * cost("S");
  const rowsUpTo = (n) => ["L", "F", "S"].slice(0, n).map((k) => ({ key: k, label: `${MODELS[k].tier} answer`, value: sc[k], color: sc[k] >= TAU ? HEX.L : HEX.red, txt: f(sc[k]) }));
  const tauLine = (s) => { const tx = ZONE.x + 1.35 + TAU * (ZONE.w - 1.35 - 0.85); line(s, tx, 2.55, tx, 4.75, { color: HEX.ink, dash: "dash", name: "!!b9-tau" }); T(s, `τ = ${TAU}`, { x: tx - 0.5, y: 4.8, w: 1, h: 0.3, align: "center", fontSize: 12, bold: true, objectName: "!!b9-taul" }); };
  technique("B · After a try", {
    title: "B9 · Cheap first, escalate", sub: "Try the cheapest model; a scorer decides whether to accept or escalate",
    stages: ["Local", "Score", "Fast", "Score", "Strong"],
    cap: "Based on FrugalGPT (Chen, Zaharia and Zou, 2023): LLM cascade with a learned answer scorer.",
    steps: [
      {
        tab: "Local", stage: 1,
        models: { L: { st: "done", note: `score ${sc.L} < τ → escalate` } },
        draw: (s) => { bars(s, rowsUpTo(1), { x: ZONE.x, y: 2.7, w: ZONE.w, rowH: 0.7, prefix: "b9" }); tauLine(s); },
        calc: ["Local answers: $0, 3.1 s", `scorer g(q, A_{L}) = **${sc.L}**`, `${sc.L} < τ = ${TAU} → escalate`, "", { t: "g is a small trained model (e.g. DistilBERT) that predicts whether an answer is correct.", color: HEX.muted, size: 13 }],
        notes: "Step 1. The free local model answers first. A scorer rates the answer at 0.42, below the threshold, so the request moves up a tier.",
      },
      {
        tab: "Fast", stage: 3,
        models: { L: { st: "done", note: `score ${sc.L} → escalate` }, F: { st: "done", note: `score ${sc.F} < τ → escalate` } },
        draw: (s) => { bars(s, rowsUpTo(2), { x: ZONE.x, y: 2.7, w: ZONE.w, rowH: 0.7, prefix: "b9" }); tauLine(s); },
        calc: [`Fast answers: ${usd(cost("F"), 6)}, 1.9 s`, `g(q, A_{F}) = **${sc.F}** < ${TAU}`, "→ escalate again", "", `spent so far: ${usd(cost("F"), 6)}`, "elapsed: 3.1 + 1.9 = 5.0 s"],
        notes: "Step 2. The fast model's answer scores 0.64, still below the threshold. The cascade has now paid for two answers.",
      },
      {
        tab: "Strong", stage: 4,
        models: { L: { st: "done", note: `score ${sc.L}` }, F: { st: "done", note: `score ${sc.F}` }, S: { st: "chosen", note: `score ${sc.S} → accept` } },
        draw: (s) => {
          bars(s, rowsUpTo(3), { x: ZONE.x, y: 2.7, w: ZONE.w, rowH: 0.7, prefix: "b9" }); tauLine(s);
          label(s, `On average: E[C] = ${usd(EC, 5)} vs Strong only ${usd(cost("S"), 4)} (−${f((1 - EC / cost("S")) * 100, 0)}%)`, { x: ZONE.x, y: 5.4, w: ZONE.w, h: 0.62, fill: { color: HEX.L, transparency: 85 }, line: { type: "none" }, bold: true, fontSize: 13, color: HEX.L, name: "!!b9-avg" });
        },
        calc: [`This request: C = ${usd(cost("F") + cost("S"), 6)}`, "L = 3.1 + 1.9 + 6.2 = 11.2 s", "", `E[C] = C_{L} + (1−a_{1})C_{F} + (1−a_{1})(1−a_{2})C_{S}`, `a_{1} = ${a1}, a_{2} = ${a2} (accept rates)`, `E[C] = **${usd(EC, 5)}**`],
        notes: "Step 3. The strong model's answer is accepted. On this hard request the cascade cost more and took longer than going straight to the strong model, but averaged over the workload, most requests stop early and the saving is large.",
      },
    ],
  });
}

/* B10 AutoMix */
{
  const votes = [1, 1, 0, 1, 0, 1, 0, 1];
  const conf = votes.reduce((a, b) => a + b, 0) / votes.length;
  const TAU = 0.75;
  const drawVotes = (s, n) => votes.forEach((v, i) => {
    const show = i < n;
    label(s, show ? (v ? "yes" : "no") : "", { x: ZONE.x + (i % 4) * 1.25, y: 3.75 + Math.floor(i / 4) * 0.65, w: 1.05, h: 0.5, r: 0.28, fontSize: 13, bold: true,
      fill: { color: show ? (v ? HEX.L : HEX.red) : HEX.sand, transparency: show ? 15 : 0 }, line: { type: "none" }, color: "FFFFFF", name: `!!b10-v${i}` });
  });
  const ans = (s) => label(s, "Local draft: “Weight decay is usually the more robust default for a small CNN: one parameter, stable training…”", { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 1.0, align: "left", fontSize: 13, italic: true, name: "!!b10-ans" });
  technique("B · After a try", {
    title: "B10 · Self-verification", sub: "The small model checks its own answer; a meta-verifier decides to keep it or escalate",
    stages: ["Small answers", "Self-verify ×k", "Confidence", "Meta-verifier", "Accept / escalate"],
    cap: "Based on AutoMix (Aggarwal et al., NeurIPS 2024): few-shot self-verification and a POMDP meta-verifier.",
    steps: [
      {
        tab: "Answer", stage: 0,
        models: { L: { st: "done", note: "draft answer, $0" } },
        draw: (s) => { ans(s); drawVotes(s, 0); },
        calc: ["Local model drafts an answer:", "$0, 3.1 s", "", "Next, the same model is asked k = 8 times:", "“Is this answer correct? yes / no”", { t: "Sampling at temperature > 0 makes the votes differ.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. The small model answers first. Then it is asked, several times, whether its own answer is correct.",
      },
      {
        tab: "Verify", stage: 2,
        models: { L: { st: "done", note: `confidence ${f(conf, 3)}` } },
        draw: (s) => { ans(s); drawVotes(s, 8); },
        calc: [`yes votes = ${votes.reduce((a, b) => a + b, 0)} of ${votes.length}`, `confidence = ${votes.reduce((a, b) => a + b, 0)} / ${votes.length} = **${f(conf, 3)}**`, "", "Verification cost: 8 short local calls", "≈ +0.6 s batched, $0", { t: "No cloud call is made to verify.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 2. Five of eight verification samples say yes, so the confidence is 0.625.",
      },
      {
        tab: "Decide", stage: 4,
        models: { L: { st: "done", note: `confidence ${f(conf, 3)} < τ` }, S: { st: "chosen", note: `escalated · ${usd(cost("S"))}` } },
        draw: (s) => { ans(s); drawVotes(s, 8); gauge(s, { x: ZONE.x, y: 5.75, w: ZONE.w, bands: [{ from: 0, to: TAU, label: "escalate", color: HEX.red }, { from: TAU, to: 1, label: "accept", color: HEX.L }], value: conf, valueTxt: f(conf, 3), hl: 0 }); },
        calc: [`${f(conf, 3)} < τ = ${TAU} → escalate to Strong`, "", `total C = $0 + ${usd(cost("S"))}`, "total L ≈ 3.1 + 0.6 + 6.2 = 9.9 s", "", { t: "AutoMix's POMDP meta-verifier learns how far to trust these noisy votes instead of using one fixed τ.", color: HEX.muted, size: 13 }],
        notes: "Step 3. The confidence is below the threshold, so the request is escalated to the strong model. Unlike FrugalGPT, no separate scorer had to be trained: the small model verifies itself.",
      },
    ],
  });
}

/* ================================================================ C. online learning */
addDark("C · Keep learning", "C · Keep learning online", "Choose, observe the outcome, update. These routers adapt when models, prices or the request mix change: 11 Epsilon-greedy · 12 LinUCB / Thompson · 13 RL multi-step",
  "Online learners use every rated answer to improve the next decision. SmartRoute's main method is C11, with C12 as a stretch goal.");

// shared bandit state (2-D context x = [1, difficulty])
const X = [1, 0.73];
const ARMS = {
  L: { A: [[25, 15], [15, 11]], b: [10.5, 5.6] },
  F: { A: [[30, 19], [19, 14]], b: [14.0, 8.4] },
  S: { A: addM([[1, 0], [0, 1]], outer(X)), b: [0.95 * X[0], 0.95 * X[1]] },
};
const est = (k) => { const Ai = inv2(ARMS[k].A); const th = mv(Ai, ARMS[k].b); return { th, mu: dotv(th, X), u: Math.sqrt(dotv(X, mv(Ai, X))) }; };
const EST = { L: est("L"), F: est("F"), S: est("S") };

/* C11 epsilon-greedy */
{
  const t = 400, eps = 0.10 + (0.02 - 0.10) * Math.min(t / 1000, 1), u = 0.41, K = 3;
  const U = { L: util("L", EST.L.mu), F: util("F", EST.F.mu), S: util("S", EST.S.mu) };
  const win = argmax(U);
  check(win === "F", "C11 greedy pick");
  const pW = (1 - eps) + eps / K, pO = eps / K;
  const y = 0.90;
  const A2 = addM(ARMS.F.A, outer(X)), b2 = [ARMS.F.b[0] + y * X[0], ARMS.F.b[1] + y * X[1]];
  const th2 = mv(inv2(A2), b2), mu2 = dotv(th2, X);
  const line01 = (s) => {
    const x0 = ZONE.x, w = ZONE.w, y0 = 3.6;
    box(s, { x: x0, y: y0, w: eps * w, h: 0.5, round: false, fill: { color: HEX.amber }, line: { type: "none" }, name: "!!c11-exp" });
    box(s, { x: x0 + eps * w, y: y0, w: (1 - eps) * w, h: 0.5, round: false, fill: { color: HEX.L, transparency: 40 }, line: { type: "none" }, name: "!!c11-expl" });
    T(s, `explore (u < ε = ${f(eps, 3)})`, { x: x0, y: y0 + 0.6, w: 2.4, h: 0.3, fontSize: 12, color: HEX.amber, bold: true, objectName: "!!c11-el" });
    T(s, "exploit (u ≥ ε)", { x: x0 + 2.6, y: y0 + 0.6, w: 2.4, h: 0.3, align: "right", fontSize: 12, color: HEX.L, bold: true, objectName: "!!c11-xl" });
    s.addShape(SH.ISOSCELES_TRIANGLE, { x: x0 + u * w - 0.13, y: y0 - 0.3, w: 0.26, h: 0.22, flipV: true, fill: { color: HEX.ink }, line: { type: "none" }, objectName: "!!c11-u" });
    T(s, `u = ${u}`, { x: x0 + u * w - 0.5, y: y0 - 0.65, w: 1, h: 0.3, align: "center", fontSize: 14, bold: true, objectName: "!!c11-ul" });
  };
  technique("C · Keep learning", {
    title: "C11 · Epsilon-greedy bandit", sub: "Usually pick the best predicted model; sometimes try another, and learn from the rating",
    stages: ["Eligible arms", "Explore?", "Best utility", "Answer + rating", "Update arm"],
    cap: "SmartRoute's main method (policies.py: EpsilonGreedyPolicy) with logged propensities for off-policy evaluation.",
    steps: [
      {
        tab: "Explore?", stage: 1,
        draw: (s) => { line01(s); T(s, "Draw u ~ Uniform(0, 1). Exploration shrinks as more answers are scored.", { x: ZONE.x, y: 4.85, w: ZONE.w, h: 0.7, fontSize: 13, color: HEX.muted, objectName: "!!c11-n" }); },
        calc: ["ε_{t} = ε_{0} + (ε_{end} − ε_{0})·min(t / T, 1)", `ε_{0} = 0.10, ε_{end} = 0.02, T = 1000`, `t = ${t} scored answers`, `ε = 0.10 − 0.08·${f(t / 1000, 1)} = **${f(eps, 3)}**`, "", `u = ${u} ≥ ε → **exploit**`],
        notes: `Step 1. Epsilon decays linearly from 0.10 to 0.02 over the first thousand scored answers. After ${t} answers it is ${f(eps, 3)}. The random draw is above it, so this time the router exploits.`,
      },
      {
        tab: "Exploit", stage: 2,
        models: { L: { st: "idle", note: `U = ${f(U.L, 3)} · p = ${f(pO, 3)}` }, F: { st: "chosen", note: `U = ${f(U.F, 3)} · p = ${f(pW, 3)}` }, S: { st: "idle", note: `U = ${f(U.S, 3)} · p = ${f(pO, 3)}` } },
        draw: (s) => bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: `U ${MODELS[k].tier}`, value: U[k], color: MODELS[k].hex, txt: f(U[k], 3), bold: k === win, dim: k !== win })), { x: ZONE.x, y: 2.85, w: ZONE.w, rowH: 0.8, prefix: "c11" }),
        calc: ["Q′_{a} = θ_{a}·x, θ_{a} = A_{a}^{−1}b_{a}, x = [1, 0.73]", ...["L", "F", "S"].map((k) => `Q′_{${k}} = ${f(EST[k].mu, 3)} → U = ${f(U[k], 3)}`), "", "Logged propensity:", `chosen: (1−ε) + ε/3 = **${f(pW, 3)}**`, `others: ε/3 = ${f(pO, 4)}`],
        notes: "Step 2. Each eligible arm predicts quality from its own ridge regression, and utility adds the calculated cost and latency. The fast model has the highest utility. The probability of this choice is logged, so the logs can later evaluate other policies without bias.",
      },
      {
        tab: "Update", stage: 4,
        models: { F: { st: "chosen", note: `rated Q = ${y}` } },
        draw: (s) => {
          table(s, [["Fast arm", "Before", "After"], ["A", fm(ARMS.F.A, 1), fm(A2, 1)], ["b", fv(ARMS.F.b), fv(b2)], ["θ = A^-1 b", fv(EST.F.th, 3), fv(th2, 3)], ["Q′(x)", f(EST.F.mu, 3), f(mu2, 3)]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.2, 1.9, 1.9], rowH: 0.5, fontSize: 11, hl: 3 });
          chip(s, `log: (x, a = Fast, p = ${f(pW, 3)}, Q = ${y})`, ZONE.x, 5.4, ZONE.w, { h: 0.5, fontSize: 13, name: "!!c11-log" });
        },
        calc: [`Observed quality Q = ${y}`, "A ← A + x x^{T}", "b ← b + Q·x", "θ ← A^{−1} b", `Q′_{F}(x): ${f(EST.F.mu, 3)} → **${f(mu2, 3)}**`, "", "Off-policy check (IPS):", `weight = 1 / p = ${f(1 / pW, 3)}`],
        notes: "Step 3. The user's rating becomes the training signal for the arm that answered. Only that arm's matrix and vector change. The logged tuple is what the inverse-propensity check uses to compare policies offline.",
      },
    ],
  });
}

/* C12 LinUCB / Thompson */
{
  const alpha = 0.5;
  const U0 = { L: util("L", EST.L.mu), F: util("F", EST.F.mu), S: util("S", EST.S.mu) };
  const U = Object.fromEntries(["L", "F", "S"].map((k) => [k, U0[k] + alpha * EST[k].u]));
  const win = argmax(U);
  check(win === "S" && argmax(U0) === "F", "C12 optimism flips the choice");
  const gamma = 0.995, y = 0.90;
  const As = addM(addM([[gamma * ARMS.S.A[0][0], gamma * ARMS.S.A[0][1]], [gamma * ARMS.S.A[1][0], gamma * ARMS.S.A[1][1]]], [[1, 0], [0, 1]], 1 - gamma), outer(X));
  const bs = [gamma * ARMS.S.b[0] + y * X[0], gamma * ARMS.S.b[1] + y * X[1]];
  const Ai = inv2(As), th = mv(Ai, bs), mu = dotv(th, X), u = Math.sqrt(dotv(X, mv(Ai, X)));
  const unc = (s, data, hlKey) => {
    const x0 = ZONE.x + 1.35, w = ZONE.w - 1.35 - 0.85, scale = (v) => x0 + Math.min(v, 1.4) / 1.4 * w;
    ["L", "F", "S"].forEach((k, i) => {
      const yy = 2.85 + i * 1.15, d = data[k];
      T(s, MODELS[k].tier, { x: ZONE.x, y: yy, w: 1.2, h: 0.36, valign: "middle", fontSize: 13, bold: k === hlKey, objectName: `!!c12-l${k}` });
      box(s, { x: x0, y: yy, w: Math.max(0.04, scale(d.base) - x0), h: 0.36, r: 0.06, fill: { color: MODELS[k].hex }, line: { type: "none" }, name: `!!c12-b${k}` });
      box(s, { x: scale(d.base), y: yy, w: Math.max(0.04, scale(d.base + d.bonus) - scale(d.base)), h: 0.36, r: 0.06, fill: { color: MODELS[k].hex, transparency: 65 }, line: { color: MODELS[k].hex, width: 1, dashType: "dash" }, name: `!!c12-u${k}` });
      T(s, d.txt, { x: scale(d.base + d.bonus) + 0.08, y: yy, w: 1.3, h: 0.36, valign: "middle", fontSize: 13, bold: k === hlKey, objectName: `!!c12-v${k}` });
    });
    T(s, "solid = predicted utility · light = uncertainty bonus α·u", { x: ZONE.x, y: 6.15, w: ZONE.w, h: 0.3, fontSize: 11, color: HEX.muted, objectName: "!!c12-key" });
  };
  technique("C · Keep learning", {
    title: "C12 · LinUCB and Thompson", sub: "Add a bonus for what the router is unsure about; rarely tried models get a chance",
    stages: ["Estimate μ", "Uncertainty u", "μ + α·u", "Answer + rating", "Update (forget)"],
    cap: "Li et al. (2010) LinUCB; bandit routers PILOT, ParetoBandit, OrcaRouter, MixLLM. SmartRoute stretch method.",
    steps: [
      {
        tab: "Estimate", stage: 1,
        draw: (s) => unc(s, Object.fromEntries(["L", "F", "S"].map((k) => [k, { base: U0[k], bonus: alpha * EST[k].u, txt: `±${f(alpha * EST[k].u, 2)}` }])), null),
        calc: ["μ_{a} = θ_{a}·x,  u_{a} = √(x^{T}A_{a}^{−1}x)", ...["L", "F", "S"].map((k) => `${MODELS[k].tier}: μ = ${f(EST[k].mu, 3)}, u = ${f(EST[k].u, 3)}`), "", { t: "Strong has been tried once, so its u is large; Fast has many observations, so its u is small.", color: HEX.muted, size: 13 }],
        notes: "Step 1. Each arm has a ridge estimate and an uncertainty. The strong arm has only one observation, so the router is very unsure about it.",
      },
      {
        tab: "Optimism", stage: 2,
        models: { L: { st: "idle", note: `score ${f(U.L, 3)}` }, F: { st: "idle", note: `score ${f(U.F, 3)} (greedy pick)` }, S: { st: "chosen", note: `score ${f(U.S, 3)} · explores` } },
        draw: (s) => unc(s, Object.fromEntries(["L", "F", "S"].map((k) => [k, { base: U0[k], bonus: alpha * EST[k].u, txt: f(U[k], 3) }])), win),
        calc: ["score = U(μ) + α·u − pacer", "α = 0.5, pacer λ = 0 here", ...["L", "F", "S"].map((k) => `${MODELS[k].tier}: ${f(U0[k], 3)} + ${f(alpha * EST[k].u, 3)} = **${f(U[k], 3)}**`), "", `Greedy would pick Fast; optimism picks **Strong**.`],
        notes: "Step 2. The optimistic score adds half the uncertainty. That lifts the barely tried strong model above the fast one, so LinUCB explores it in a targeted way instead of at random.",
      },
      {
        tab: "Update", stage: 4,
        models: { S: { st: "chosen", note: `rated Q = ${y} · u ${f(EST.S.u, 2)} → ${f(u, 2)}` } },
        draw: (s) => unc(s, { L: { base: U0.L, bonus: alpha * EST.L.u, txt: f(U.L, 3) }, F: { base: U0.F, bonus: alpha * EST.F.u, txt: f(U.F, 3) }, S: { base: util("S", mu), bonus: alpha * u, txt: f(util("S", mu) + alpha * u, 3) } }, "S"),
        calc: ["A ← γA + (1−γ)λI + x x^{T}", "b ← γb + Q·x,  γ = 0.995", `Strong: μ ${f(EST.S.mu, 3)} → ${f(mu, 3)}`, `u ${f(EST.S.u, 3)} → **${f(u, 3)}**`, "", "Thompson variant: sample θ* ~ N(θ′, ν²A^{−1}), pick the best sample.", { t: "γ < 1 forgets old data, so arms follow drifting models.", color: HEX.muted, size: 13 }],
        notes: "Step 3. After the rating, the strong arm's uncertainty shrinks, so its bonus is smaller next time. The forgetting factor gamma slowly discounts old observations, which lets the router follow a model whose quality or latency drifts.",
      },
    ],
  });
}

/* C13 RL multi-step */
{
  const group = [0.85, 0.40, 0.95, 0.10];
  const mean = group.reduce((a, b) => a + b, 0) / group.length;
  const sd = Math.sqrt(group.reduce((a, b) => a + (b - mean) ** 2, 0) / group.length);
  const adv = group.map((r) => (r - mean) / sd);
  const steps = [
    ["think", "Split: define both, then judge robustness", HEX.faint],
    ["route → Local", "“Define dropout and weight decay briefly.”", HEX.L],
    ["info", "Local returns two short definitions", HEX.sand],
    ["route → Strong", "“Which is more robust for a small CNN, and why?”", HEX.S],
    ["answer", "Router writes the final answer from both", HEX.terra],
  ];
  const traj = (s, n) => steps.forEach(([k, t, c], i) => {
    const show = i < n, yy = ZONE.y + i * 0.78;
    label(s, show ? k : "", { x: ZONE.x, y: yy, w: 1.45, h: 0.62, r: 0.12, fontSize: 12, bold: true, fill: { color: show ? c : HEX.sand, transparency: show && (c === HEX.sand || c === HEX.faint) ? 0 : show ? 15 : 0 }, line: { type: "none" }, color: show && c !== HEX.sand && c !== HEX.faint ? "FFFFFF" : HEX.ink, name: `!!c13-k${i}` });
    T(s, show ? t : "", { x: ZONE.x + 1.6, y: yy, w: 3.4, h: 0.62, valign: "middle", fontSize: 12, color: HEX.ink, objectName: `!!c13-t${i}` });
  });
  technique("C · Keep learning", {
    title: "C13 · RL multi-step router", sub: "A router model plans several calls, combines the answers, and is trained by reward",
    stages: ["Think", "Route call", "Read result", "Answer", "RL update"],
    cap: "Based on Router-R1 (2025): a reasoning model that interleaves thinking and routing, trained with reinforcement learning.",
    steps: [
      {
        tab: "Plan", stage: 1,
        models: { L: { st: "done", note: "sub-question 1" } },
        draw: (s) => traj(s, 3),
        calc: ["State = question + all results so far.", "Actions: <think>, <route model, query>, <answer>.", "", "Call 1 → Local: $0, 3.1 s", { t: "Cheap sub-questions go to cheap models.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. A multi-step router is itself a language model. It thinks, then sends a sub-question to a model as if calling a tool, and reads the result.",
      },
      {
        tab: "Call again", stage: 3,
        models: { L: { st: "done", note: "sub-question 1 · $0" }, S: { st: "done", note: `sub-question 2 · ${usd(cost("S") * 0.5, 4)}` } },
        draw: (s) => traj(s, 5),
        calc: ["Call 2 → Strong (short sub-question)", `≈ half the tokens: ${usd(cost("S") * 0.5, 4)}`, "", "Final answer combines both results.", `Total C ≈ ${usd(cost("S") * 0.5, 4)}`, "Total L ≈ 3.1 + 3.4 + 1.0 = 7.5 s"],
        notes: "Step 2. Only the hard part is sent to the strong model, so the expensive call is shorter. The router then writes the final answer.",
      },
      {
        tab: "Reward", stage: 4,
        models: false,
        draw: (s) => {
          bars(s, group.map((r, i) => ({ key: `g${i}`, label: `Rollout ${i + 1}`, value: r, color: adv[i] >= 0 ? HEX.L : HEX.red, txt: `${f(r)} (A ${adv[i] >= 0 ? "+" : ""}${f(adv[i], 2)})`, bold: i === 0 })), { x: ZONE.x, y: 2.85, w: 7.8, rowH: 0.75, labelW: 1.5, valueW: 1.7, prefix: "c13" });
          T(s, "Rollouts above the group mean are reinforced; those below are discouraged.", { x: ZONE.x, y: 5.95, w: 7.8, h: 0.4, fontSize: 13, color: HEX.muted, objectName: "!!c13-n" });
        },
        calc: ["R = R_{format} + R_{outcome} − β·C_{norm}", "Rollout 1: 0 + 1.0 − 0.5·0.30 = **0.85**", "", "GRPO, group of 4 rollouts:", `mean = ${f(mean, 3)}, sd = ${f(sd, 3)}`, "A_{i} = (R_{i} − mean) / sd", `A_{1} = **${f(adv[0], 2)}**`],
        notes: "Step 3. Training samples several trajectories for the same question. Each gets a reward for format, correctness and low cost. The advantage compares each trajectory with the group, and the policy gradient makes better trajectories more likely. This needs GPU training time, which is why it is an optional add-on for SmartRoute.",
      },
    ],
  });
}

/* ================================================================ D. hard limits */
addDark("D · Hard limits", "D · Hard limits", "Filters that remove models before any router chooses: privacy · context window · health · budget. A router can only pick from what is left.",
  "Hard limits run first, in this order in the pipeline: privacy, credentials, health, context window, budget. Nothing a router learns can override them.");

/* D1 privacy */
{
  const REQ = "Draft a short reply to the student about her grade appeal. Her CNIC is 42101-1234567-1.";
  const ladder = [["Cloud switched off?", "no"], ["Local-only chat or key?", "no"], ["Detector failed?", "no"], ["Nothing confidential?", "no: CNIC found"], ["User not permitted?", "yes → block cloud"], ["No consent?", "not reached"], ["Permitted + consent", "not reached"]];
  technique("D · Hard limits", {
    title: "D1 · Privacy gate", sub: "Detect confidential content, decide if cloud is allowed, filter, check again, audit",
    stages: ["Detect", "Decide", "Filter", "Final check", "Audit"],
    cap: "SmartRoute: core/privacy/scanner.py and gate.py. Related work: PRISM, Dual-Vault (research guide).",
    steps: [
      {
        tab: "Detect", stage: 0,
        draw: (s) => {
          label(s, [{ text: "“Draft a short reply to the student about her grade appeal. Her CNIC is ", options: { italic: true } }, { text: "42101-1234567-1", options: { bold: true, color: HEX.red, highlight: "F7E3D9" } }, { text: ".”", options: { italic: true } }], { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 0.95, align: "left", fontSize: 13, name: "!!d1-req" });
          table(s, [["Detector", "Result"], ["CNIC pattern", "match → NATIONAL_ID"], ["PK phone", "—"], ["Email", "—"], ["Card (Luhn check)", "—"], ["IBAN (checksum)", "—"], ["Presidio + GLiNER", "names (on server)"]], { x: ZONE.x, y: 3.75, w: ZONE.w, colW: [2.2, 2.8], rowH: 0.36, hl: 0 });
        },
        calc: ["All detectors run locally; their union counts.", "", "Findings: NATIONAL_ID", "Triggers: pii_detected", "", { t: "Detection is separate from enforcement, so each is tested on its own.", color: HEX.muted, size: 13 }],
        notes: "Step 1. A different request: it contains a CNIC. Every detector runs on our server and the findings are combined. The CNIC pattern matches, so the request is confidential.",
      },
      {
        tab: "Decide", stage: 1,
        draw: (s) => table(s, [["Check (in order)", "Result"], ...ladder], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [2.6, 2.4], rowH: 0.45, hl: 4 }),
        calc: ["decide_cloud(user, mode, sensitive, consent)", "", "Strictest rule wins:", "user = Ayesha, permission = inherit", "org default = deny", "→ cloud_blocked", "reason: confidential_not_permitted", { t: "A detector error also blocks the cloud (fail closed).", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 2. The checks run in a fixed order and the strictest one wins. The superadmin has not permitted this user, so cloud is blocked before consent is even considered.",
      },
      {
        tab: "Filter + audit", stage: 4,
        models: { L: { st: "chosen", note: "only eligible model" }, F: { st: "excluded", note: "✕ not permitted" }, S: { st: "excluded", note: "✕ not permitted" } },
        draw: (s) => {
          table(s, [["Audit field", "Value"], ["user", "ayesha@university.example"], ["triggers", "pii_detected · NATIONAL_ID"], ["decision", "cloud_blocked (not permitted)"], ["destination", "local-default · stayed local"], ["preview", "…Her CNIC is [NATIONAL_ID]."], ["hash", "SHA-256 8f595bbeae…"]], { x: ZONE.x, y: ZONE.y, w: ZONE.w, colW: [1.35, 3.65], rowH: 0.42 });
        },
        calc: ["Eligible = {Local}", "Router chooses only from this set.", "", "Final outbound check: re-scans the exact payload before any cloud call (none here).", "", "Audit row written before dispatch.", { t: "The query text itself is never stored.", color: HEX.muted, size: 13 }],
        notes: "Step 3. Both cloud models are removed before routing, so no learner or retry can reach them. An audit row with a masked preview and a hash is written before the local model is called.",
      },
    ],
  });
}

/* D2 context window */
{
  const parts0 = [["Pasted text", 3300, HEX.faint], ["History", 2000, HEX.amber], ["Passages 5×270", 1350, HEX.terra], ["System", 60, HEX.muted]];
  const total = (ps) => Math.round(ps.reduce((a, [, v]) => a + v, 0) * 1.1);
  const RES = 1024;
  const in0 = total(parts0), need0 = in0 + RES;
  const parts1 = parts0.map(([n, v, c]) => (n === "History" ? ["History (summary)", 600, c] : [n, v, c]));
  const in1 = total(parts1), need1 = in1 + RES;
  const WIN = { L: 8192, F: 100000, S: 1000000 };
  check(need0 > WIN.L && need1 <= WIN.L, "D2 fit");
  const stack = (s, ps, need) => {
    let x = ZONE.x; const sc = 4.6 / 9000;
    ps.forEach(([n, v, c], i) => { const w = v * 1.1 * sc; box(s, { x, y: ZONE.y + 0.4, w, h: 0.6, round: false, fill: { color: c }, line: { color: HEX.ivory, width: 1 }, name: `!!d2-p${i}` }); x += w; });
    box(s, { x, y: ZONE.y + 0.4, w: RES * sc, h: 0.6, round: false, fill: { color: HEX.ink, transparency: 30 }, line: { color: HEX.ivory, width: 1 }, name: "!!d2-res" });
    const wx = ZONE.x + WIN.L * sc;
    line(s, wx, ZONE.y + 0.15, wx, ZONE.y + 1.25, { color: HEX.red, width: 2, dash: "dash", name: "!!d2-win" });
    T(s, "Local window 8,192", { x: wx - 1.0, y: ZONE.y - 0.12, w: 2.0, h: 0.28, align: "center", fontSize: 11, bold: true, color: HEX.red, objectName: "!!d2-winl" });
    T(s, `${need.toLocaleString("en-US")} tokens needed (incl. 1,024 reserved output)`, { x: ZONE.x, y: ZONE.y + 1.1, w: ZONE.w, h: 0.3, fontSize: 12, bold: true, objectName: "!!d2-need" });
    T(s, ps.map(([n, v]) => `${n} ${v.toLocaleString("en-US")}`).join(" · "), { x: ZONE.x, y: ZONE.y + 1.45, w: ZONE.w, h: 0.5, fontSize: 11, color: HEX.muted, objectName: "!!d2-parts" });
  };
  const fits = (need) => ["L", "F", "S"].map((k) => ({ key: k, label: MODELS[k].tier, value: Math.min(need / WIN[k], 1.2), max: 1.2, color: need <= WIN[k] ? HEX.L : HEX.red, txt: `${f((need / WIN[k]) * 100, need / WIN[k] < 0.1 ? 2 : 0)}%` }));
  technique("D · Hard limits", {
    title: "D2 · Context window fit", sub: "Remove any model whose window cannot hold the prompt plus the reserved answer",
    stages: ["Count tokens", "Reserve output", "Compare windows", "Exclude", "Eligible set"],
    cap: "SmartRoute pipeline: in_tokens + min(output cap, max_output) ≤ context_window, checked per model.",
    steps: [
      {
        tab: "Count", stage: 1,
        draw: (s) => stack(s, parts0, need0),
        calc: ["A long pasted section plus chat history.", "in = (pasted + history + passages + system)·1.1", `in = ${in0.toLocaleString("en-US")} tokens`, "reserve = min(cap 1024, max_out) = 1,024", `need = **${need0.toLocaleString("en-US")}**`, { t: "×1.1 is a safety margin over the token estimate.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. A different request with a long pasted section. The gateway estimates input tokens with a safety margin and reserves room for the answer.",
      },
      {
        tab: "Compare", stage: 3,
        models: { L: { st: "excluded", note: "✕ context window" }, F: { st: "idle", note: "fits" }, S: { st: "idle", note: "fits" } },
        draw: (s) => { stack(s, parts0, need0); bars(s, fits(need0), { x: ZONE.x, y: 4.75, w: ZONE.w, rowH: 0.6, max: 1.2, prefix: "d2" }); },
        calc: [`Local: ${need0.toLocaleString("en-US")} > 8,192 → **excluded**`, `Fast: ${f((need0 / WIN.F) * 100, 1)}% of 100,000 → ok`, `Strong: ${f((need0 / WIN.S) * 100, 2)}% of 1,000,000 → ok`, "", { t: "Ollama would otherwise cut the prompt silently, so the limit must be enforced before routing.", color: HEX.muted, size: 13 }],
        notes: "Step 2. The local model's window is too small for this prompt, so it is removed. Without this check Ollama truncates the prompt without an error and the answer silently loses context.",
      },
      {
        tab: "If shorter", stage: 4,
        models: { L: { st: "idle", note: "fits again" }, F: { st: "idle", note: "fits" }, S: { st: "idle", note: "fits" } },
        draw: (s) => { stack(s, parts1, need1); bars(s, fits(need1), { x: ZONE.x, y: 4.75, w: ZONE.w, rowH: 0.6, max: 1.2, prefix: "d2" }); },
        calc: ["If the history were a 600-token summary:", `in = ${in1.toLocaleString("en-US")}`, `need = **${need1.toLocaleString("en-US")}** ≤ 8,192`, "→ Local is eligible again", "", { t: "Context handling decides what is sent; this limit only checks that it fits.", color: HEX.muted, size: 13 }],
        notes: "Step 3. If the older turns are replaced by the local summary, the same request fits the local window again. The limit itself does not shorten anything; it only checks.",
      },
    ],
  });
}

/* D3 health */
{
  const a = 0.2, prev = 3100, obs = 4200, ew = (1 - a) * prev + a * obs;
  const timeline = (s, nowAt) => {
    const x0 = ZONE.x, w = ZONE.w, y = 5.0;
    box(s, { x: x0, y, w, h: 0.42, round: false, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!d3-tl" });
    box(s, { x: x0 + 0.1 * w, y, w: 0.6 * w, h: 0.42, round: false, fill: { color: HEX.red, transparency: 55 }, line: { type: "none" }, name: "!!d3-bad" });
    T(s, "Fast excluded for 60 s", { x: x0 + 0.1 * w, y: y + 0.05, w: 0.6 * w, h: 0.32, align: "center", fontSize: 12, bold: true, color: "FFFFFF", objectName: "!!d3-badl" });
    ["0 s", "60 s", "90 s"].forEach((t, i) => T(s, t, { x: x0 + [0.1, 0.7, 1.0][i] * w - 0.4, y: y + 0.48, w: 0.8, h: 0.28, align: "center", fontSize: 11, color: HEX.muted, objectName: `!!d3-t${i}` }));
    s.addShape(SH.ISOSCELES_TRIANGLE, { x: x0 + nowAt * w - 0.13, y: y - 0.3, w: 0.26, h: 0.22, flipV: true, fill: { color: HEX.ink }, line: { type: "none" }, objectName: "!!d3-now" });
    T(s, "now", { x: x0 + nowAt * w - 0.5, y: y - 0.62, w: 1, h: 0.3, align: "center", fontSize: 12, bold: true, objectName: "!!d3-nowl" });
  };
  technique("D · Hard limits", {
    title: "D3 · Hardware and health", sub: "Track latency, and skip a model that just failed until it has had time to recover",
    stages: ["Measure latency", "EWMA", "Error?", "Circuit breaker", "Eligible set"],
    cap: "SmartRoute pipeline: latency EWMA with α = 0.2; a failed call marks the model unhealthy for 60 s.",
    steps: [
      {
        tab: "Latency", stage: 1,
        draw: (s) => {
          bars(s, [{ key: "p", label: "Previous EWMA", value: prev, max: 6000, color: HEX.faint, txt: `${prev} ms` }, { key: "o", label: "Observed now", value: obs, max: 6000, color: HEX.amber, txt: `${obs} ms` }, { key: "n", label: "New EWMA", value: ew, max: 6000, color: HEX.L, txt: `${ew} ms`, bold: true }], { x: ZONE.x, y: 2.85, w: ZONE.w, rowH: 0.75, max: 6000, prefix: "d3" });
        },
        calc: ["L′ ← (1 − α)·L′ + α·L_{obs},  α = 0.2", `L′ = 0.8·${prev} + 0.2·${obs}`, `L′ = **${ew} ms** (Local)`, "", `latency term l = 1 − ${f(ew / 1000, 2)}/10 = ${f(1 - ew / 10000, 3)}`, { t: "Routers read the smoothed latency, not one noisy sample.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 1. Every successful call updates an exponentially weighted moving average of the model's latency. One slow call moves the estimate only a fifth of the way.",
      },
      {
        tab: "Failure", stage: 3,
        models: { F: { st: "excluded", note: "✕ HTTP 503 · unhealthy 60 s" } },
        draw: (s) => {
          label(s, "Fast returned HTTP 503 → retry once with the next eligible model", { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 0.62, fontSize: 13, fill: { color: HEX.red, transparency: 88 }, line: { type: "none" }, color: HEX.red, bold: true, name: "!!d3-err" });
          timeline(s, 0.1);
        },
        calc: ["status = failed →", "unhealthy_until = now + 60 s", "last_error = “503 Service Unavailable”", "", "Bounded retry: 1, only among eligible models.", { t: "The retry passes the same privacy and context filters.", color: HEX.muted, size: 13, gap: 6 }],
        notes: "Step 2. When a call fails, a circuit breaker marks that model unhealthy for sixty seconds, so the next requests do not keep hitting a broken endpoint. The request is retried once with another eligible model.",
      },
      {
        tab: "Recover", stage: 4,
        models: { F: { st: "idle", note: "eligible again" } },
        draw: (s) => {
          label(s, "After 60 s Fast is eligible again; its next success clears the flag", { x: ZONE.x, y: ZONE.y, w: ZONE.w, h: 0.62, fontSize: 13, fill: { color: HEX.L, transparency: 85 }, line: { type: "none" }, color: HEX.L, bold: true, name: "!!d3-err" });
          timeline(s, 0.85);
        },
        calc: ["now > unhealthy_until → eligible", "next success:", "unhealthy_until = none", "EWMA updated with that latency", "", { t: "No manual reset is needed.", color: HEX.muted, size: 13 }],
        notes: "Step 3. After the window expires the model is considered again. A successful call clears the flag and feeds the latency average.",
      },
    ],
  });
}

/* D4 budget */
{
  const B = 100, day = 18, days = 30, frac = day / days, spent = 69;
  const expected = B * Math.max(frac, 0.05), lam = Math.min(Math.max(spent / expected - 1, 0), 1);
  const before = { F: 0.775, S: 0.783 }; // LinUCB scores from C12 (rounded)
  const pen = { F: lam * Math.min(cost("F") / C_REF, 1), S: lam * Math.min(cost("S") / C_REF, 1) };
  const after = { F: before.F - pen.F, S: before.S - pen.S };
  check(after.F > after.S && before.S > before.F, "D4 flip");
  const userB = 5, userSpent = 4.995;
  technique("D · Hard limits", {
    title: "D4 · Budget pacing", sub: "Spend evenly through the month: a soft penalty first, a hard cap at the limit",
    stages: ["Spend so far", "Pace", "λ penalty", "Hard cap", "Eligible set"],
    cap: "SmartRoute: pacer_lambda() in policies.py (soft) and user / platform budget exclusions in the pipeline (hard).",
    steps: [
      {
        tab: "Pace", stage: 1,
        draw: (s) => bars(s, [{ key: "e", label: "Expected by day 18", value: expected, max: B, color: HEX.faint, txt: `$${f(expected, 0)}` }, { key: "s", label: "Spent", value: spent, max: B, color: HEX.amber, txt: `$${spent}`, bold: true }, { key: "b", label: "Monthly budget", value: B, max: B, color: HEX.sand, txt: `$${B}` }], { x: ZONE.x, y: 2.85, w: ZONE.w, rowH: 0.8, max: B, labelW: 1.7, prefix: "d4" }),
        calc: [`expected = B·max(day/30, 0.05)`, `= ${B}·${f(frac, 2)} = $${f(expected, 0)}`, `spent = $${spent}`, `overrun = ${spent}/${f(expected, 0)} − 1 = ${f(spent / expected - 1, 3)}`, `λ = clip(overrun, 0, 1) = **${f(lam, 2)}**`],
        notes: "Step 1. The platform budget is a hundred dollars a month. By day eighteen the even pace is sixty dollars, but sixty-nine has been spent, fifteen percent ahead of pace.",
      },
      {
        tab: "Penalty", stage: 2,
        models: { F: { st: "chosen", note: `${f(before.F, 3)} → ${f(after.F, 3)}` }, S: { st: "idle", note: `${f(before.S, 3)} → ${f(after.S, 3)}` } },
        draw: (s) => bars(s, [{ key: "F", label: "Fast", value: after.F, color: HEX.F, txt: f(after.F, 3), bold: true }, { key: "S", label: "Strong", value: after.S, color: HEX.S, txt: f(after.S, 3), dim: true }], { x: ZONE.x, y: 2.85, w: ZONE.w, rowH: 0.8, max: 1, labelW: 1.7, prefix: "d4" }),
        calc: ["penalty_{a} = λ·min(C_{a}/C_{ref}, 1)", `Fast: ${f(lam, 2)}·${f(cost("F") / C_REF, 4)} = ${f(pen.F, 4)}`, `Strong: ${f(lam, 2)}·${f(cost("S") / C_REF, 2)} = ${f(pen.S, 3)}`, "", `C12 scores: S ${before.S} > F ${before.F}`, `after penalty: F **${f(after.F, 3)}** > S ${f(after.S, 3)}`],
        notes: "Step 2. The pacer turns the overrun into a penalty proportional to each model's cost. The strong model was narrowly ahead in the LinUCB example; with the penalty, the fast model wins. Spending slows down without blocking anything.",
      },
      {
        tab: "Hard cap", stage: 4,
        models: { F: { st: "chosen", note: "within budget" }, S: { st: "excluded", note: "✕ user budget" } },
        draw: (s) => bars(s, [{ key: "e", label: "Ayesha's budget", value: userB, max: userB, color: HEX.sand, txt: `$${userB}` }, { key: "s", label: "Spent + Strong", value: userSpent + cost("S"), max: userB, color: HEX.red, txt: usd(userSpent + cost("S"), 4), bold: true }, { key: "b", label: "Spent + Fast", value: userSpent + cost("F"), max: userB, color: HEX.L, txt: usd(userSpent + cost("F"), 4) }], { x: ZONE.x, y: 2.85, w: ZONE.w, rowH: 0.8, max: userB * 1.01, labelW: 1.7, prefix: "d4" }),
        calc: [`user budget $${userB}, spent $${userSpent}`, `Strong: ${userSpent} + ${f(cost("S"), 4)} > ${userB} → **excluded**`, `Fast: ${userSpent} + ${f(cost("F"), 6)} ≤ ${userB} → ok`, "Local costs $0 → always within budget", "", { t: "The platform budget ($100) is checked the same way.", color: HEX.muted, size: 13 }],
        notes: "Step 3. Separately, each user can have a hard monthly budget. A model whose estimated cost would cross it is removed, just like a privacy or context exclusion. Free local models are never excluded by budget.",
      },
    ],
  });
}

/* ================================================================ summary + close */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Summary" });
  s.addText("What each technique chose", { placeholder: "title" });
  s.addText("Same request, same models; methods that weigh cost tend to pick Fast", { placeholder: "body" });
  const rows = [
    ["Technique", "Decides from", "Extra calls", "Needs training data", "Picked"],
    ["A1 Rules", "word and length features", "none", "no", "Strong"],
    ["A2 Semantic routes", "similarity to route examples", "embedding", "a few examples", "Strong"],
    ["A3 kNN", "similar past outcomes", "embedding", "outcome log", "Fast"],
    ["A4 Difficulty classifier", "p(hard)", "none", "labelled requests", "Strong"],
    ["A5 Quality + cost predictor", "Q′ + calculated cost", "none", "benchmark", "Fast"],
    ["A6 Preference-trained", "P(strong wins)", "none", "preference battles", "Strong"],
    ["A7 Contrastive / graph", "embedding similarity / graph edge", "embedding", "benchmark", "Strong / Fast"],
    ["A8 LLM as router", "route policies", "1 small model", "no (pretrained)", "Strong"],
    ["B9 Cheap first", "answer scorer", "up to 3 answers", "scored answers", "Strong (after 2)"],
    ["B10 Self-verification", "self-check votes", "k = 8 local", "no", "Strong (after 1)"],
    ["C11 Epsilon-greedy", "learned Q′ + cost", "none", "online ratings", "Fast"],
    ["C12 LinUCB", "Q′ + uncertainty bonus", "none", "online ratings", "Strong (explores)"],
    ["C13 RL multi-step", "learned plan", "several", "RL training", "Local + Strong"],
  ];
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, color: HEX.muted, fill: { color: HEX.sand } } }));
  const body = rows.slice(1).map((r) => r.map((t, j) => ({ text: t, options: { bold: j === 0 || j === 4, color: j === 4 ? (t.startsWith("Fast") ? HEX.F : t.startsWith("Local") ? HEX.L : HEX.S) : HEX.ink, fill: { color: HEX.card } } })));
  s.addTable([head, ...body], { x: 0.6, y: 1.72, w: 12.13, colW: [2.6, 3.3, 1.75, 2.3, 2.18], fontSize: 12, rowH: 0.34, valign: "middle", margin: 0.05, border: { type: "solid", pt: 0.75, color: HEX.line } });
  s.addNotes("The same request leads to different choices. Methods that judge quality alone pick the strong model; methods that add the calculated cost, as SmartRoute's reward does, mostly pick the fast model. With C_ref at one cent, the strong model wins only when it is expected to be much better in quality, which is why the reward weights and C_ref must be calibrated on the pilot before the experiments.");
}
{
  const s = addDark("Summary", "Hard limits first, then learn", "SmartRoute: D filters every request · A1 rules and A5 frozen predictor as baselines · C11 epsilon-greedy as the main method · C12 LinUCB as the stretch goal",
    "Closing. The hard limits are not optional: they decide what is allowed. Within that set, SmartRoute compares simple baselines with an online learner, and measures cost, quality and privacy on the GPU server.");
  [["D", "filters", HEX.red], ["A1 + A5", "baselines", HEX.S], ["C11", "main method", HEX.L], ["C12", "stretch", HEX.amber]].forEach(([t, sub, c], i) => {
    label(s, [{ text: t, options: { bold: true, fontSize: 20, breakLine: true } }, { text: sub, options: { fontSize: 13 } }], { x: 9.6, y: 1.5 + i * 1.2, w: 3.1, h: 1.0, fill: { color: c }, line: { type: "none" }, color: "FFFFFF", name: `!!end-${i}` });
  });
}

/* ================================================================ write, theme, morph */
const MORPH = '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"><mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" Requires="p159"><p:transition xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" spd="slow" p14:dur="1250"><p159:morph option="byObject"/></p:transition></mc:Choice><mc:Fallback><p:transition spd="slow"><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>';
(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  const zip = await JSZip.loadAsync(fs.readFileSync(OUT));
  const slides = Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n));
  for (const p of slides) {
    if (p === "ppt/slides/slide1.xml") continue;
    let xml = await zip.file(p).async("string");
    if (!xml.includes("p159:morph")) xml = xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + MORPH);
    zip.file(p, xml);
  }
  // copy file entries only, so the package has no folder entries
  const clean = new JSZip();
  for (const n of Object.keys(zip.files)) {
    if (zip.files[n].dir) continue;
    clean.file(n, await zip.file(n).async("nodebuffer"), { createFolders: false });
  }
  fs.writeFileSync(OUT, await clean.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log(`wrote ${OUT} with ${slides.length} slides`);
})();
