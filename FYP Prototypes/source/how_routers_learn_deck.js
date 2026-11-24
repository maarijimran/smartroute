// SmartRoute: how the implemented routers are trained, saved, used and improved.
// Run: PPTX_SKILL=<pptx skill dir> NODE_PATH=<node_modules> node learndeck.js <output.pptx>
const pptxgen = require("pptxgenjs");
const JSZip = require("jszip");
const fs = require("fs");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = process.argv[2];
const THEME = {
  name: "SmartRoute", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "262624", lt1: "FAF9F5", dk2: "3D3D3A", lt2: "F0EEE6", accent1: "3B7D55", accent2: "D97757", accent3: "AE5630", accent4: "BF4034", accent5: "73726C", accent6: "C08A2E", hlink: "D97757", folHlink: "AE5630" },
};
const HEX = { card: "FFFFFF", line: "E5E2D8", sand: "F0EEE6", ivory: "FAF9F5", ink: "262624", muted: "73726C", faint: "9C9A92", L: "3B7D55", F: "C96442", S: "AE5630", red: "BF4034", amber: "C08A2E", terra: "D97757", code: "1F1E1D", codeInk: "E8E6DC" };
const ROUTER = { rules: HEX.muted, frozen: HEX.amber, bandit: HEX.L, linucb: HEX.S };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "SmartRoute: how the routers learn";
pres.author = "Aman Malik, Muhammad Maarij, Syed Tuaha Ahmed";
pres.company = "FAST NUCES Karachi";
const C = pres.SchemeColor;
const SH = pres.shapes;

pres.defineSlideMaster({
  title: "DARK", background: { color: HEX.ink },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.9, w: 8.4, h: 1.4, fontSize: 50, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.45, w: 7.8, h: 1.4, fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "SIM", background: { color: HEX.ivory },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.36, w: 8.3, h: 0.72, fontSize: 36, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 1.08, w: 8.3, h: 0.45, fontSize: 16, color: C.text2, valign: "top", margin: 0 }, text: "" } },
    { text: { text: "SmartRoute · how the routers learn", options: { x: 0.6, y: 7.02, w: 7, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.02, w: 0.5, h: 0.3, fontSize: 10, color: "73726C", align: "right" },
});
const SECTIONS = new Set();
function addSlide(opts) {
  if (opts.sectionTitle && !SECTIONS.has(opts.sectionTitle)) { pres.addSection({ title: opts.sectionTitle }); SECTIONS.add(opts.sectionTitle); }
  return pres.addSlide(opts);
}

/* ---------------------------------------------------------------- text helpers */
function runs(str, base = {}) {
  const out = []; const re = /(\*\*[^*]+\*\*|_\{[^}]*\}|\^\{[^}]*\})/g; let last = 0, m;
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
const f = (v, d = 2) => Number(v).toFixed(d);
const T = (s, text, o) => s.addText(typeof text === "string" ? runs(text) : text, { isTextBox: true, margin: 0, fontSize: 14, color: HEX.ink, valign: "top", ...o });
function box(s, o) {
  s.addShape(o.round === false ? SH.RECTANGLE : SH.ROUNDED_RECTANGLE, { x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: o.round === false ? undefined : (o.r ?? 0.08), fill: o.fill ?? { color: HEX.card }, line: o.line ?? { color: HEX.line, width: 0.75 }, objectName: o.name });
}
function label(s, text, o) {
  s.addText(typeof text === "string" ? runs(text) : text, {
    shape: SH.ROUNDED_RECTANGLE, rectRadius: o.r ?? 0.08, x: o.x, y: o.y, w: o.w, h: o.h,
    fill: o.fill ?? { color: HEX.card }, line: o.line ?? { color: HEX.line, width: 0.75 },
    fontSize: o.fontSize ?? 14, bold: o.bold ?? false, color: o.color ?? HEX.ink, italic: o.italic ?? false, fontFace: o.fontFace,
    align: o.align ?? "center", valign: o.valign ?? "middle", margin: o.margin ?? (o.align === "left" ? 8 : 3), objectName: o.name,
  });
}
function line(s, x1, y1, x2, y2, o = {}) {
  s.addShape(SH.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.max(Math.abs(x2 - x1), 0.001), h: Math.max(Math.abs(y2 - y1), 0.001), flipH: x2 < x1, flipV: y2 < y1,
    line: { color: o.color ?? HEX.faint, width: o.width ?? 1.5, endArrowType: o.head === false ? undefined : "triangle", dashType: o.dash }, objectName: o.name });
}
function code(s, text, o) {
  label(s, text, { ...o, align: "left", valign: "top", fontSize: o.fontSize ?? 12, fontFace: "Consolas", fill: { color: HEX.code }, line: { type: "none" }, color: HEX.codeInk, margin: 10 });
}
function chip(s, text, x, y, w, o = {}) {
  label(s, text, { x, y, w, h: o.h ?? 0.42, r: 0.2, fontSize: o.fontSize ?? 12, bold: o.bold, fill: o.fill ?? { color: HEX.terra, transparency: 82 }, line: o.line ?? { type: "none" }, color: o.color ?? HEX.S, name: o.name });
}
function table(s, rows, o) {
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, color: HEX.muted, fill: { color: HEX.sand } } }));
  const body = rows.slice(1).map((r, i) => r.map((t, j) => ({ text: String(t), options: { bold: o.hl === i || (o.boldFirst && j === 0), color: o.hl === i ? HEX.S : HEX.ink, fill: { color: o.hl === i ? "F7E3D9" : HEX.card } } })));
  s.addTable([head, ...body], { x: o.x, y: o.y, w: o.w, colW: o.colW, fontSize: o.fontSize ?? 12, rowH: o.rowH ?? 0.34, valign: "middle", margin: 0.06, border: { type: "solid", pt: 0.75, color: HEX.line } });
}
function bars(s, rows, o) {
  const { x, y, w, rowH = 0.6, labelW = 1.4, max = 1, valueW = 0.8, prefix = "b" } = o;
  const trackW = w - labelW - valueW - 0.1;
  rows.forEach((r, i) => {
    const yy = y + i * rowH, bh = Math.min(0.36, rowH * 0.62);
    T(s, r.label, { x, y: yy, w: labelW - 0.1, h: bh, valign: "middle", fontSize: 13, bold: !!r.bold, color: r.dim ? HEX.faint : HEX.ink, objectName: `!!${prefix}l-${r.key}` });
    box(s, { x: x + labelW, y: yy, w: trackW, h: bh, r: 0.06, fill: { color: HEX.sand }, line: { type: "none" }, name: `!!${prefix}t-${r.key}` });
    box(s, { x: x + labelW, y: yy, w: Math.max(0.04, Math.min(r.value / max, 1) * trackW), h: bh, r: 0.06, fill: { color: r.color ?? HEX.terra, transparency: r.dim ? 60 : 0 }, line: { type: "none" }, name: `!!${prefix}f-${r.key}` });
    T(s, r.txt ?? f(r.value), { x: x + labelW + trackW + 0.1, y: yy, w: valueW, h: bh, valign: "middle", fontSize: 13, bold: !!r.bold, color: r.dim ? HEX.faint : HEX.ink, objectName: `!!${prefix}v-${r.key}` });
  });
}
const CALC = { x: 8.75, y: 1.75, w: 3.98, h: 5.0 };
function calc(s, lines, title = "In the code") {
  box(s, { ...CALC, name: "!!calc-card" });
  T(s, title, { x: CALC.x + 0.25, y: CALC.y + 0.2, w: CALC.w - 0.5, h: 0.35, fontSize: 15, bold: true, objectName: "!!calc-h" });
  T(s, para(lines, { fontSize: 14, color: HEX.ink }), { x: CALC.x + 0.25, y: CALC.y + 0.65, w: CALC.w - 0.45, h: CALC.h - 0.85, paraSpaceAfter: 4, objectName: "!!calc" });
}
const STEPS = ["Train", "Save", "Use", "Improve"];
function tracker(s, active, color) {
  const w = 0.95, g = 0.06, x0 = 12.73 - 4 * w - 3 * g;
  box(s, { x: x0 + active * (w + g), y: 0.52, w, h: 0.42, r: 0.2, fill: { color }, line: { type: "none" }, name: "!!trk-hl" });
  STEPS.forEach((t, i) => T(s, `${i + 1}  ${t}`, { x: x0 + i * (w + g), y: 0.52, w, h: 0.42, align: "center", valign: "middle", fontSize: 12, bold: i === active, color: i === active ? "FFFFFF" : HEX.muted, objectName: `!!trk-${i}` }));
}
function caption(s, text) { T(s, text, { x: 0.6, y: 6.62, w: 7.8, h: 0.32, fontSize: 11, italic: true, color: HEX.muted, objectName: "!!cap" }); }
function stepSlide(section, title, sub, step, color) {
  const s = addSlide({ masterName: "SIM", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "body" });
  tracker(s, step, color);
  return s;
}
const addDark = (section, title, body, notes) => {
  const s = addSlide({ masterName: "DARK", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (body) s.addText(body, { placeholder: "body" });
  if (notes) s.addNotes(notes);
  return s;
};

/* ---------------------------------------------------------------- shared numbers */
const W = { q: 0.5, c: 0.3, l: 0.2 };
const K = { L: 0.3 * 1.0 + 0.2 * 0.69, F: 0.3 * 0.9775 + 0.2 * 0.81, S: 0.3 * 0.1 + 0.2 * 0.38 }; // 0.3c + 0.2l from the running example
const NAME = { L: "Llama 3.1 8B", F: "Claude Haiku 5.5", S: "Claude Opus 5.5" };
const TIER = { L: "Local", F: "Fast", S: "Strong" };
const MC = { L: HEX.L, F: HEX.F, S: HEX.S };
const check = (c, m) => { if (!c) throw new Error("check failed: " + m); };

// deterministic random numbers for the simulations
function lcg(seed) { let s = seed; return () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648); }
const inv2 = (A) => { const d = A[0][0] * A[1][1] - A[0][1] * A[1][0]; return [[A[1][1] / d, -A[0][1] / d], [-A[1][0] / d, A[0][0] / d]]; };
const mv = (A, x) => [A[0][0] * x[0] + A[0][1] * x[1], A[1][0] * x[0] + A[1][1] * x[1]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
function arm2() { return { A: [[1, 0], [0, 1]], b: [0, 0] }; }
function upd(a, x, y, g = 1) {
  a.A = [[g * a.A[0][0] + (1 - g) + x[0] * x[0], g * a.A[0][1] + x[0] * x[1]], [g * a.A[1][0] + x[1] * x[0], g * a.A[1][1] + (1 - g) + x[1] * x[1]]];
  a.b = [g * a.b[0] + y * x[0], g * a.b[1] + y * x[1]];
}
const pred = (a, x) => dot(mv(inv2(a.A), a.b), x);
const unc = (a, x) => Math.sqrt(dot(x, mv(inv2(a.A), x)));

// epsilon-greedy improvement: Fast arm, cold start, batches of 50 scored events (Fast answers 30 of them)
const XH = [1, 0.73], TRUE_F = (d) => 0.90 - 0.35 * d;
const simE = (() => {
  const rnd = lcg(11), a = arm2(), out = [{ batch: 0, pred: pred(a, XH), eps: 0.10 }];
  for (let k = 1; k <= 5; k++) {
    for (let i = 0; i < 30; i++) { const d = rnd(); upd(a, [1, d], TRUE_F(d) + (rnd() - 0.5) * 0.1); }
    out.push({ batch: k, pred: pred(a, XH), eps: 0.10 - 0.08 * Math.min((50 * k) / 1000, 1) });
  }
  return out;
})();
check(Math.abs(simE[5].pred - TRUE_F(0.73)) < 0.08, "simE converges");

// LinUCB drift: Haiku answered 300 hard requests at quality 0.66, then the provider changes and quality drops to 0.45
const simD = (() => {
  const checkpoints = [0, 50, 100, 200, 400], res = {};
  for (const g of [0.995, 1.0]) {
    const a = arm2();
    for (let i = 0; i < 300; i++) upd(a, XH, 0.66, g);
    let n = 0; res[g] = [];
    for (const cp of checkpoints) { while (n < cp) { upd(a, XH, 0.45, g); n++; } res[g].push(pred(a, XH)); }
  }
  return { checkpoints, res };
})();
check(simD.res[0.995][4] < 0.5 && simD.res[1.0][4] > 0.5, "drift sim");

/* ================================================================ 1. title */
{
  const s = addDark("Overview", "How SmartRoute's routers learn", "The four routing methods we implemented: how each is trained, where it saves what it learned, how it uses it, and how it improves over time.",
    "This deck covers only the routers that exist in the SmartRoute gateway: rules, the frozen ridge router, epsilon-greedy and LinUCB. For each one we follow the same four steps: train, save, use, improve.");
  [["Rules", "fixed", ROUTER.rules], ["Frozen ridge", "learns once", ROUTER.frozen], ["Epsilon-greedy", "keeps learning · main", ROUTER.bandit], ["LinUCB", "keeps learning · stretch", ROUTER.linucb]].forEach(([t, sub, c], i) =>
    label(s, [{ text: t, options: { bold: true, fontSize: 18, breakLine: true } }, { text: sub, options: { fontSize: 13 } }], { x: 9.5, y: 1.4 + i * 1.2, w: 3.2, h: 1.0, fill: { color: c }, line: { type: "none" }, color: "FFFFFF", name: `!!t-r${i}` }));
  T(s, "Aman Malik · Muhammad Maarij · Syed Tuaha Ahmed\nSupervisor: Dr. Farrukh Salim Sheikh · FAST NUCES Karachi", { x: 0.7, y: 5.6, w: 8, h: 0.7, fontSize: 13, color: "C2C0B6" });
}

/* ================================================================ 2. overview */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Overview" });
  s.addText("Four routers, one life cycle", { placeholder: "title" });
  s.addText("Every router is described by the same four steps", { placeholder: "body" });
  const rows = [
    ["Router", "1 Train", "2 Save", "3 Use", "4 Improve"],
    ["Rules", "Not trained: thresholds set by the team", "In the code (policies.py)", "Difficulty → rule → tier → cheapest model", "Only when people edit the rules"],
    ["Frozen ridge", "Once, offline, on 360 benchmark requests", "Database: policy_states “frozen”", "Predicted quality + cost + latency → best", "Only by retraining (new version)"],
    ["Epsilon-greedy", "Starts empty or copies the frozen router", "Database: “bandit”, new version per batch", "Best utility; explores with probability ε", "Every 50 rated answers; ε shrinks"],
    ["LinUCB", "Starts empty or copies the frozen router", "Database: “linucb”, new version per batch", "Utility + uncertainty bonus − budget penalty", "Every 50 rated answers, forgetting old data"],
  ];
  const head = rows[0].map((t) => ({ text: t, options: { bold: true, color: HEX.muted, fill: { color: HEX.sand } } }));
  const cols = [ROUTER.rules, ROUTER.frozen, ROUTER.bandit, ROUTER.linucb];
  const body = rows.slice(1).map((r, i) => r.map((t, j) => ({ text: t, options: { bold: j === 0, color: j === 0 ? cols[i] : HEX.ink, fill: { color: HEX.card } } })));
  s.addTable([head, ...body], { x: 0.6, y: 1.75, w: 12.13, colW: [1.75, 2.75, 2.5, 2.7, 2.43], fontSize: 13, rowH: 0.62, valign: "middle", margin: 0.08, border: { type: "solid", pt: 0.75, color: HEX.line } });
  const cyc = ["Train", "Save", "Use", "Improve"];
  cyc.forEach((t, i) => {
    label(s, `${i + 1}  ${t}`, { x: 2.2 + i * 2.35, y: 5.45, w: 1.85, h: 0.6, r: 0.3, fill: { color: HEX.terra, transparency: 80 }, line: { color: HEX.terra, width: 1.25 }, bold: true, color: HEX.S, name: `!!ov-c${i}` });
    if (i < 3) line(s, 2.2 + i * 2.35 + 1.9, 5.75, 2.2 + (i + 1) * 2.35 - 0.05, 5.75, { color: HEX.terra, name: `!!ov-a${i}` });
  });
  line(s, 2.2 + 3 * 2.35 + 0.92, 6.08, 2.2 + 3 * 2.35 + 0.92, 6.38, { head: false, color: HEX.terra, name: "!!ov-b1" });
  line(s, 2.2 + 3 * 2.35 + 0.92, 6.38, 2.2 + 1 * 2.35 + 0.92, 6.38, { head: false, color: HEX.terra, name: "!!ov-b2" });
  line(s, 2.2 + 1 * 2.35 + 0.92, 6.38, 2.2 + 1 * 2.35 + 0.92, 6.1, { color: HEX.terra, name: "!!ov-b3" });
  T(s, "learning routers loop: improve → save a new version", { x: 4.6, y: 6.42, w: 4.6, h: 0.3, fontSize: 12, italic: true, color: HEX.muted, align: "center" });
  s.addNotes("The four routers that exist in SmartRoute. Rules never learn. The frozen router learns once from the benchmark. Epsilon-greedy and LinUCB keep learning from rated answers and save a new version after every batch, which is the loop at the bottom.");
}

/* ================================================================ 3-4. foundations */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Foundations" });
  s.addText("What the routers see", { placeholder: "title" });
  s.addText("The feature vector x: every request turned into numbers before a learned router looks at it", { placeholder: "body" });
  const groups = [
    ["Numbers (standardised)", ["log input tokens", "log expected output", "difficulty", "local GPU load", "log history tokens"], HEX.terra],
    ["Yes / no flags", ["has a document", "is a follow-up"], HEX.amber],
    ["Task (one-hot)", ["document Q&A", "summary", "explain"], HEX.L],
    ["Constant", ["1"], HEX.muted],
    ["Meaning (server, optional)", ["16 PCA numbers from the MiniLM embedding"], HEX.S],
  ];
  const ys = [1.8, 2.95, 3.65, 4.35, 5.05];
  groups.forEach(([g, items, c], i) => {
    const y = ys[i];
    T(s, g, { x: 0.6, y: y + 0.06, w: 2.2, h: 0.4, fontSize: 13, bold: true, color: c, objectName: `!!fx-g${i}` });
    let x = 2.85, yy = y;
    items.forEach((t, j) => {
      const w = Math.max(0.6, 0.085 * t.length + 0.35);
      if (x + w > 8.4) { x = 2.85; yy += 0.5; }
      chip(s, t, x, yy, w, { fill: { color: c, transparency: 82 }, color: HEX.ink, name: `!!fx-${i}-${j}` });
      x += w + 0.1;
    });
  });
  label(s, "d = 11 features (27 with the meaning block)", { x: 0.6, y: 5.85, w: 7.8, h: 0.5, fill: { color: HEX.sand }, line: { type: "none" }, bold: true, fontSize: 14, name: "!!fx-d" });
  calc(s, [
    "x = [(numbers − mean) / std, flags, task, 1, PCA(embedding)]", "",
    "mean, std and PCA are fitted on the **train split only** and saved in artifacts/features.json, with a feature version.",
    { t: "If the number of features changes, saved learner state no longer fits and the router starts empty (cold start).", gap: 6 },
    { t: "core/features.py · scripts/fit_features.py", color: HEX.muted, size: 12, gap: 6 },
  ]);
  s.addNotes("All three learning routers see the same feature vector. The scaling and the embedding projection are fitted on the training split only, so the test data never leaks into training. The chat task has no flag of its own: all three task flags are zero.");
}
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Foundations" });
  s.addText("What they learn", { placeholder: "title" });
  s.addText("One ridge “arm” per model; frozen, epsilon-greedy and LinUCB all store knowledge this way", { placeholder: "body" });
  ["L", "F", "S"].forEach((k, i) => {
    const x = 0.6 + i * 2.65;
    label(s, [{ text: NAME[k], options: { bold: true, color: MC[k], breakLine: true } }, { text: "A  d × d matrix", options: { fontSize: 13, breakLine: true } }, { text: "b  d numbers", options: { fontSize: 13, breakLine: true } }, { text: "n  answers seen", options: { fontSize: 13 } }],
      { x, y: 1.8, w: 2.45, h: 1.55, align: "left", valign: "top", margin: 10, fontSize: 14, line: { color: MC[k], width: 1.25 }, name: `!!arm-${k}` });
  });
  const rows = [
    ["Start", "A = λI,  b = 0  (λ = 1)", "knows nothing; predicts 0"],
    ["Weights", "θ = A^{−1} b", "the learned quality formula"],
    ["Predict", "Q′ = θ · x", "expected quality for this request"],
    ["Learn", "A ← A + x x^{T},  b ← b + y · x", "y = rated quality (−1 if it failed)"],
    ["Unsure?", "u = √(x^{T} A^{−1} x)", "used by LinUCB's bonus"],
  ];
  rows.forEach(([a, b, c], i) => {
    const y = 3.62 + i * 0.6;
    label(s, a, { x: 0.6, y, w: 1.3, h: 0.5, fill: { color: HEX.sand }, line: { type: "none" }, bold: true, fontSize: 13, name: `!!rr-a${i}` });
    label(s, b, { x: 2.0, y, w: 3.2, h: 0.5, fontSize: 14, name: `!!rr-b${i}` });
    T(s, c, { x: 5.35, y: y + 0.1, w: 3.0, h: 0.35, fontSize: 13, color: HEX.muted, objectName: `!!rr-c${i}` });
  });
  calc(s, [
    "class RidgeArm (core/routing/arms.py)", "",
    "θ = A^{−1}b is ridge regression, (X^{T}X + λI)^{−1}X^{T}y, built up one answer at a time.",
    { t: "The three arms are saved together as one JSON document, the router's state.", gap: 6 },
    { t: "Same arms, three behaviours: frozen never updates, epsilon-greedy updates, LinUCB updates with forgetting and uses u.", gap: 6 },
  ]);
  s.addNotes("Each model has an arm: a matrix A that summarises the requests it answered, a vector b that summarises their ratings, and a count. The weights are A inverse times b. This is ordinary ridge regression, written so that it can be updated one answer at a time.");
}

/* ================================================================ Rules */
const RULES = [["Short explanation", "explain & tokens < 300", "Local → Fast → Strong"], ["Complex", "difficulty ≥ 0.60 or tokens > 6000", "Strong → Fast → Local"], ["Summary", "summarise", "Fast → Local → Strong"], ["Default", "otherwise", "Fast → Strong → Local"]];
{
  const sec = "Rules", col = ROUTER.rules, T1 = "A1 · Rules";
  let s = stepSlide(sec, T1, "Hand-written thresholds; the baseline and the fallback", 0, col);
  label(s, "No training data, no learning", { x: 0.6, y: 1.8, w: 7.8, h: 0.6, fill: { color: HEX.sand }, line: { type: "none" }, bold: true, fontSize: 16, name: "!!r-head" });
  table(s, [["Rule", "When", "Tier order"], ...RULES], { x: 0.6, y: 2.6, w: 7.8, colW: [2.0, 3.2, 2.6], rowH: 0.48, fontSize: 13, boldFirst: true });
  label(s, "difficulty = 0.25 + 0.12·hard words − 0.10·easy words + length + token terms", { x: 0.6, y: 5.25, w: 7.8, h: 0.55, fontSize: 13, name: "!!r-diff" });
  calc(s, ["Thresholds and word lists were chosen by the team from the proposal.", "", "Nothing is fitted to data, so there is nothing to train.", { t: "core/routing/policies.py · RulesPolicy", color: HEX.muted, size: 12, gap: 8 }]);
  s.addNotes("The rules router is not trained. Its thresholds and its keyword lists were chosen by hand. That is its weakness, because it never learns, and its strength, because it is predictable and easy to explain.");

  s = stepSlide(sec, T1, "Hand-written thresholds; the baseline and the fallback", 1, col);
  code(s, "# core/routing/policies.py\nRULE_SHORT_TOKENS    = 300\nRULE_LONG_TOKENS     = 6000\nRULE_HARD_COMPLEXITY = 0.60\n\nclass RulesPolicy:\n    if explain and tokens < 300:   order = [local, cheap, strong]\n    elif difficulty >= 0.60 ...:   order = [strong, cheap, local]\n    elif summary:                  order = [cheap, local, strong]\n    else:                          order = [cheap, strong, local]", { x: 0.6, y: 1.8, w: 7.8, h: 3.3, name: "!!r-code" });
  label(s, "Saved in the database: only the choice  routing_policy = “rules”  (with change history)", { x: 0.6, y: 5.3, w: 7.8, h: 0.6, fontSize: 13, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!r-db" });
  calc(s, ["The “knowledge” is the code itself, kept in git.", "", "No learner state, no versions, nothing to roll back.", "", "Every server running the same code makes exactly the same decisions."]);
  s.addNotes("Because nothing is learned, nothing is saved except the superadmin's choice of the rules router. The rules live in the source code, so they are versioned by git, not by the database.");

  s = stepSlide(sec, T1, "Hand-written thresholds; the baseline and the fallback", 2, col);
  const flow = [["Request", "difficulty 0.73 · 200 tokens · chat"], ["Rule", "Complex (0.73 ≥ 0.60)"], ["Tier order", "Strong → Fast → Local"], ["Pick", "first eligible tier, cheapest model in it"]];
  flow.forEach(([h, t], i) => {
    label(s, [{ text: h, options: { bold: true, breakLine: true } }, { text: t, options: { fontSize: 12, color: HEX.muted } }], { x: 0.6 + i * 1.98, y: 1.85, w: 1.8, h: 1.2, fontSize: 14, name: `!!r-f${i}` });
    if (i < 3) line(s, 0.6 + i * 1.98 + 1.82, 2.45, 0.6 + (i + 1) * 1.98 - 0.02, 2.45, { name: `!!r-fa${i}` });
  });
  label(s, [{ text: "Normal request → ", options: {} }, { text: "Claude Opus 5.5", options: { bold: true, color: HEX.S } }], { x: 0.6, y: 3.4, w: 7.8, h: 0.6, align: "left", name: "!!r-o1" });
  label(s, [{ text: "Same request with a CNIC → Opus and Haiku removed by the privacy gate → ", options: {} }, { text: "Llama 3.1 8B", options: { bold: true, color: HEX.L } }], { x: 0.6, y: 4.15, w: 7.8, h: 0.6, align: "left", name: "!!r-o2" });
  label(s, "The rules only choose among models the hard limits left. The order is a preference, never a way around a filter.", { x: 0.6, y: 4.95, w: 7.8, h: 0.75, fontSize: 13, italic: true, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!r-o3" });
  calc(s, ["1. compute difficulty from words and length", "2. first matching rule gives a tier order", "3. walk the order; first tier with an eligible model wins", "4. inside that tier, the cheapest model", "", { t: "Propensity logged = 1 (deterministic).", color: HEX.muted, size: 13 }]);
  s.addNotes("Using the rules is a short walk: compute the difficulty, find the first rule that matches, and take the cheapest eligible model in the first tier that has one. If privacy removed the cloud models, the walk ends at the local model.");

  s = stepSlide(sec, T1, "Hand-written thresholds; the baseline and the fallback", 3, col);
  ["Month 1", "Month 2", "Month 3"].forEach((m, i) => {
    label(s, [{ text: m, options: { bold: true, breakLine: true } }, { text: "same request → Claude Opus 5.5", options: { fontSize: 12 } }], { x: 0.6 + i * 2.65, y: 1.85, w: 2.45, h: 1.0, fontSize: 14, name: `!!r-m${i}` });
  });
  T(s, "It never changes by itself: the same request always gets the same model.", { x: 0.6, y: 3.05, w: 7.8, h: 0.4, fontSize: 14, bold: true, objectName: "!!r-same" });
  [["How it improves", "People read the evaluation (where rules lose to the oracle), change thresholds or word lists, and deploy new code."], ["Why we keep it", "Explainable baseline for the thesis, default policy for a new install, and the rollback target if learning misbehaves."]].forEach(([h, t], i) =>
    label(s, [{ text: h, options: { bold: true, breakLine: true, color: HEX.S } }, { text: t, options: { fontSize: 13 } }], { x: 0.6, y: 3.65 + i * 1.3, w: 7.8, h: 1.15, align: "left", valign: "top", margin: 10, fontSize: 14, name: `!!r-i${i}` }));
  calc(s, ["No feedback loop.", "", "Ratings of its answers are still logged, and both bandits learn from them (see the bandit slides).", "", { t: "So running the rules router still trains the learners in the background.", color: HEX.S }]);
  s.addNotes("The rules router does not improve over time. A person has to change it. But its answers are still rated and logged, and the two bandits learn from every scored answer whichever router chose the model, so time spent on rules is not wasted.");
}

/* ================================================================ Frozen */
{
  const sec = "Frozen ridge", col = ROUTER.frozen, T1 = "A5 · Frozen ridge router";
  const sub = "Learns once from the benchmark, then stays fixed";
  let s = stepSlide(sec, T1, sub, 0, col);
  const pipe = [["build_workload.py", "600 QASPER requests · split 60/20/20 by paper"], ["fit_features.py", "scaling + PCA on the train split"], ["collect_outcomes.py", "every model answers every train request"], ["scores", "Q = 0.7·human + 0.3·automatic"], ["train_frozen.py", "one ridge per model"]];
  pipe.forEach(([h, t], i) => {
    label(s, [{ text: h, options: { bold: true, fontSize: 13, breakLine: true } }, { text: t, options: { fontSize: 12, color: HEX.muted } }], { x: 0.6, y: 1.8 + i * 0.72, w: 4.6, h: 0.62, align: "left", margin: 8, name: `!!f-p${i}` });
    if (i < 4) line(s, 2.9, 1.8 + i * 0.72 + 0.63, 2.9, 1.8 + (i + 1) * 0.72 - 0.01, { width: 1.25, name: `!!f-pa${i}` });
  });
  label(s, [{ text: "X", options: { bold: true, fontSize: 20, breakLine: true } }, { text: "360 × d features", options: { fontSize: 12 } }], { x: 5.55, y: 2.0, w: 1.3, h: 1.6, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!f-X" });
  label(s, [{ text: "Y", options: { bold: true, fontSize: 20, breakLine: true } }, { text: "360 × 3 qualities", options: { fontSize: 12 } }], { x: 7.05, y: 2.0, w: 1.3, h: 1.6, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!f-Y" });
  T(s, "Full information: we know how every model did on every training request, so no exploration is needed.", { x: 5.55, y: 3.8, w: 2.8, h: 1.6, fontSize: 13, color: HEX.muted, objectName: "!!f-full" });
  calc(s, ["θ_{a} = (X^{T}X + λI)^{−1} X^{T} y_{a}", "λ = 1, one θ per model", "", "y = quality Q (“split” mode)", "y = −1 if the answer failed", "", { t: "Set the reward weights, C_ref and L_ref from the pilot first; they are frozen with the model.", size: 13, color: HEX.muted }]);
  s.addNotes("The frozen router is trained once, offline, on the server. The benchmark gives full information: every model answered every training request, so each model's ridge regression can be fitted directly. Training happens on the train split only.");

  s = stepSlide(sec, T1, sub, 1, col);
  code(s, 'table policy_states\n  name     "frozen"\n  version  1          active  true\n  note     "trained on 360 train requests, reward_mode=split"\n  state    {\n    "d": 11, "lam": 1.0, "feature_version": "v1",\n    "arms": {\n      "local-default": { "A": [11×11], "b": [11], "n": 360 },\n      "claude-haiku":  { "A": [11×11], "b": [11], "n": 360 },\n      "claude-opus":   { "A": [11×11], "b": [11], "n": 360 } } }', { x: 0.6, y: 1.8, w: 7.8, h: 3.45, name: "!!f-code" });
  label(s, "+ artifacts/features.json: the mean, std and PCA the features need", { x: 0.6, y: 5.45, w: 7.8, h: 0.55, fontSize: 13, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!f-art" });
  calc(s, ["save_arms() writes a new row:", "version = latest + 1, active = true", "older versions → active = false, but kept", "", "The JSON holds A, b and n for every model.", { t: "core/routing/state.py · models.py (PolicyState)", color: HEX.muted, size: 12, gap: 8 }]);
  s.addNotes("What the frozen router learned is saved in the database as a versioned row: the matrices and vectors of all three arms in one JSON document. The feature scaling it depends on is saved next to it as an artifact file.");

  s = stepSlide(sec, T1, sub, 2, col);
  const steps = ["Request → features x (saved scaling + PCA)", "Load the active “frozen” version (cached in memory)", "Q′ = θ · x for every eligible model", "U = 0.5·Q′ + 0.3·c + 0.2·l  →  highest U"];
  steps.forEach((t, i) => label(s, `${i + 1}  ${t}`, { x: 0.6, y: 1.8 + i * 0.6, w: 7.8, h: 0.5, align: "left", fontSize: 13, name: `!!f-u${i}` }));
  const U = { L: 0.626, F: 0.788, S: 0.543 };
  bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: `U ${TIER[k]}`, value: U[k], color: MC[k], txt: f(U[k], 3), bold: k === "F", dim: k !== "F" })), { x: 0.6, y: 4.35, w: 7.8, rowH: 0.6, prefix: "fu" });
  calc(s, ["Example (hard request):", "Q′ = L 0.38 · F 0.67 · S 0.87", "U = L 0.626 · F 0.788 · S 0.543", "→ **Claude Haiku 5.5**", "", { t: "Cost and latency are calculated, so a price change applies at once without retraining.", color: HEX.muted, size: 13 }]);
  s.addNotes("Using the frozen router is a dot product per model. The saved weights predict quality, the calculated cost and latency terms are added, and the model with the highest utility among the eligible ones is chosen.");

  s = stepSlide(sec, T1, sub, 3, col);
  [["v1", "360 requests", true], ["v2", "720 requests (retrained)", false]].forEach(([v, t, act], i) => {
    label(s, [{ text: `frozen ${v}`, options: { bold: true, breakLine: true } }, { text: t, options: { fontSize: 12 } }], { x: 0.6 + i * 3.3, y: 1.85, w: 2.9, h: 1.0, fill: { color: act ? HEX.card : HEX.sand }, line: { color: act ? col : HEX.line, width: act ? 1.75 : 0.75 }, fontSize: 14, name: `!!f-v${i}` });
  });
  line(s, 3.55, 2.35, 3.85, 2.35, { name: "!!f-va" });
  label(s, "active", { x: 0.6, y: 3.0, w: 1.0, h: 0.38, r: 0.19, fill: { color: col }, line: { type: "none" }, color: "FFFFFF", bold: true, fontSize: 12, name: "!!f-act" });
  [["Never changes while serving", "Deliberate: it is the fixed comparison for research question 2 (does learning online beat learning once?)."], ["How it improves", "Collect more outcomes and run train_frozen.py again → a new version; the old one is kept for rollback."], ["Gives the bandits a head start", "train_frozen.py --warm-start copies its arms into “bandit” and “linucb”."]].forEach(([h, t], i) =>
    label(s, [{ text: h, options: { bold: true, breakLine: true, color: HEX.S } }, { text: t, options: { fontSize: 13 } }], { x: 0.6, y: 3.6 + i * 1.0, w: 7.8, h: 0.9, align: "left", valign: "top", margin: 9, fontSize: 14, name: `!!f-i${i}` }));
  calc(s, ["No online updates.", "", "Retraining = new version:", "v1 kept → Settings → Policy → Rollback", "", { t: "Train only on the train split; the test split is for the final evaluation.", color: HEX.muted, size: 13 }]);
  s.addNotes("The frozen router does not learn from live traffic, by design. It is the yardstick for research question 2. It improves only when the team retrains it on more data, which creates a new version. It can also seed the two bandits.");
}

/* ================================================================ Epsilon-greedy */
{
  const sec = "Epsilon-greedy", col = ROUTER.bandit, T1 = "C11 · Epsilon-greedy";
  const sub = "Main method: exploits the best prediction, explores at random, learns from every batch";
  let s = stepSlide(sec, T1, sub, 0, col);
  [["Cold start", ["A = λI, b = 0 for every model", "every prediction starts at 0", "learns everything from live ratings", "more exploration at first"], HEX.muted], ["Warm start (recommended)", ["copy the frozen router's arms", "n_scored reset to 0, so ε = 0.10 again", "starts with good predictions", "then keeps adapting"], col]].forEach(([h, items, c], i) =>
    label(s, [{ text: h, options: { bold: true, fontSize: 16, color: c, breakLine: true } }, ...items.map((t, j) => ({ text: `• ${t}`, options: { fontSize: 13, breakLine: j < items.length - 1 } }))], { x: 0.6 + i * 4.0, y: 1.85, w: 3.8, h: 2.6, align: "left", valign: "top", margin: 12, line: { color: c, width: 1.5 }, name: `!!e-s${i}` }));
  label(s, "Warm start: Settings → Policy → Warm start, or  train_frozen.py --warm-start", { x: 0.6, y: 4.7, w: 7.8, h: 0.6, fontSize: 13, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!e-ws" });
  calc(s, ["No separate training phase: it trains itself while it serves.", "", "warm_start() copies the active “frozen” state into “bandit”, version + 1.", { t: "Idea from OrcaRouter: begin from a supervised router, then adapt online.", color: HEX.muted, size: 13, gap: 6 }]);
  s.addNotes("Epsilon-greedy has no separate training phase. It can start empty, or, better, from a copy of the frozen router. Starting warm avoids a period of poor decisions while it learns from scratch.");

  s = stepSlide(sec, T1, sub, 1, col);
  table(s, [["routing_events (one row per request)", "example"], ["features", "x = [0.21, −0.40, 1.65, …]"], ["chosen_model", "claude-haiku"], ["propensity", "0.955"], ["explored", "false"], ["quality · reward", `0.90 · ${f(W.q * 0.9 + K.F, 2)}`], ["reward_applied", "false  (waiting for its batch)"]], { x: 0.6, y: 1.8, w: 4.6, colW: [2.0, 2.6], rowH: 0.42, fontSize: 12, boldFirst: true });
  table(s, [["policy_states “bandit”", "note"], ["v1", "warm start from frozen v1"], ["v2", "batch update with 50 outcomes"], ["v3 (active)", "batch update with 50 outcomes"]], { x: 5.4, y: 1.8, w: 3.0, colW: [1.1, 1.9], rowH: 0.55, fontSize: 12, hl: 2 });
  label(s, "The propensity (probability of the choice) is what makes the logs usable for unbiased offline evaluation (IPS).", { x: 0.6, y: 5.05, w: 7.8, h: 0.75, fontSize: 13, italic: true, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!e-ips" });
  calc(s, ["Two kinds of saving:", "", "1. every request: its x, choice, propensity, later its rating and reward", "", "2. every batch: the arms as a new version of “bandit”", { t: "Older versions stay for rollback.", color: HEX.muted, size: 13, gap: 6 }]);
  s.addNotes("Epsilon-greedy saves two things. Every request is logged with its features, the model chosen and the probability of that choice. After every batch of fifty scored requests, the updated arms are saved as a new version.");

  s = stepSlide(sec, T1, sub, 2, col);
  const eps = 0.068, u = 0.41;
  box(s, { x: 0.6, y: 2.35, w: eps * 7.8, h: 0.5, round: false, fill: { color: HEX.amber }, line: { type: "none" }, name: "!!e-ex" });
  box(s, { x: 0.6 + eps * 7.8, y: 2.35, w: (1 - eps) * 7.8, h: 0.5, round: false, fill: { color: col, transparency: 40 }, line: { type: "none" }, name: "!!e-xp" });
  s.addShape(SH.ISOSCELES_TRIANGLE, { x: 0.6 + u * 7.8 - 0.13, y: 2.05, w: 0.26, h: 0.22, flipV: true, fill: { color: HEX.ink }, line: { type: "none" }, objectName: "!!e-u" });
  T(s, `u = ${u}`, { x: 0.6 + u * 7.8 - 0.5, y: 1.72, w: 1, h: 0.3, align: "center", fontSize: 13, bold: true, objectName: "!!e-ul" });
  T(s, `explore (u < ε = ${eps})`, { x: 0.6, y: 2.92, w: 3, h: 0.3, fontSize: 12, bold: true, color: HEX.amber, objectName: "!!e-el" });
  T(s, "exploit (u ≥ ε)", { x: 5.4, y: 2.92, w: 3, h: 0.3, align: "right", fontSize: 12, bold: true, color: col, objectName: "!!e-xl" });
  const Ue = { L: 0.625, F: 0.677, S: 0.394 };
  bars(s, ["L", "F", "S"].map((k) => ({ key: k, label: `U ${TIER[k]}`, value: Ue[k], color: MC[k], txt: `${f(Ue[k], 3)} · p ${k === "F" ? "0.955" : "0.023"}`, bold: k === "F", dim: k !== "F" })), { x: 0.6, y: 3.55, w: 7.8, rowH: 0.62, valueW: 1.5, prefix: "eu" });
  label(s, "Exploit → Claude Haiku 5.5 (highest utility)", { x: 0.6, y: 5.5, w: 7.8, h: 0.5, fill: { color: col, transparency: 85 }, line: { type: "none" }, bold: true, color: col, fontSize: 14, name: "!!e-res" });
  calc(s, ["ε = 0.10 + (0.02 − 0.10)·min(n / 1000, 1)", "n = 400 scored → **ε = 0.068**", "", "explore: any eligible model, uniformly", "exploit: highest U = 0.5·Q′ + 0.3c + 0.2l", "", "propensity: chosen (1−ε) + ε/3 = 0.955", "others ε/3 = 0.023"]);
  s.addNotes("To decide, epsilon-greedy draws a random number. Below epsilon it explores a random eligible model; otherwise it picks the highest predicted utility, exactly like the frozen router but with weights that keep changing. The probability of the choice is logged.");

  s = stepSlide(sec, T1, sub, 3, col);
  const loop = ["Answer", "Rating", "Q and R", "Wait for 50", "Update arm", "New version"];
  const pos = [[0.6, 1.8], [3.3, 1.8], [6.0, 1.8], [6.0, 3.05], [3.3, 3.05], [0.6, 3.05]];
  loop.forEach((t, i) => label(s, t, { x: pos[i][0], y: pos[i][1], w: 2.4, h: 0.62, fill: { color: col, transparency: 85 }, line: { color: col, width: 1 }, bold: true, fontSize: 13, color: HEX.ink, name: `!!e-l${i}` }));
  line(s, 3.0, 2.11, 3.3, 2.11, { color: col }); line(s, 5.7, 2.11, 6.0, 2.11, { color: col }); line(s, 7.2, 2.42, 7.2, 3.05, { color: col });
  line(s, 6.0, 3.36, 5.7, 3.36, { color: col }); line(s, 3.3, 3.36, 3.0, 3.36, { color: col }); line(s, 1.8, 3.05, 1.8, 2.42, { color: col });
  s.addChart(pres.charts.BAR, [{ name: "Prediction for a hard request", labels: simE.map((p) => `batch ${p.batch}`), values: simE.map((p) => +p.pred.toFixed(3)) }], {
    x: 0.6, y: 3.85, w: 7.8, h: 2.7, barDir: "col", chartColors: [col], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", dataLabelFontSize: 11, dataLabelColor: HEX.ink,
    showTitle: true, title: `Fast arm's predicted quality (true value ${f(TRUE_F(0.73), 2)})`, titleFontSize: 12, titleColor: HEX.ink, titleFontFace: "+mn-lt",
    catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    valAxisMinVal: 0, valAxisMaxVal: 0.8, valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
  });
  calc(s, ["Rating: H from four 1–5 scores, A automatic; Q = 0.7H + 0.3A", "Only the **chosen** model's arm learns", "A ← A + x x^{T},  b ← b + Q·x", "Every 50 scored answers → new version, n += 50, so ε shrinks", ...simE.slice(1).filter((_, i) => i % 2 === 1).map((p) => `batch ${p.batch}: ε ${f(p.eps, 3)}`), { t: "Both learners learn from every rated answer, whichever router chose it. Benchmark runs never train them.", size: 12, color: HEX.muted, gap: 4 }]);
  s.addNotes(`Improvement is a loop. Each answer can be rated; the rating becomes quality and reward. Once fifty scored answers are waiting, each one updates the arm of the model that answered it, a new version is saved and epsilon shrinks. The chart is a small simulation: starting empty, the fast arm's prediction for a hard request climbs to about ${f(simE[5].pred, 2)}, close to its true quality of ${f(TRUE_F(0.73), 2)}, within five batches.`);
}

/* ================================================================ LinUCB */
{
  const sec = "LinUCB", col = ROUTER.linucb, T1 = "C12 · LinUCB";
  const sub = "Stretch method: explores where it is unsure, forgets slowly, respects the budget";
  let s = stepSlide(sec, T1, sub, 0, col);
  [["Cold start", ["A = λI, b = 0", "large uncertainty everywhere", "explores every model early"], HEX.muted], ["Warm start (recommended)", ["copy the frozen router's arms", "uncertainty already small where the benchmark had data"], col]].forEach(([h, items, c], i) =>
    label(s, [{ text: h, options: { bold: true, fontSize: 16, color: c, breakLine: true } }, ...items.map((t, j) => ({ text: `• ${t}`, options: { fontSize: 13, breakLine: j < items.length - 1 } }))], { x: 0.6 + i * 4.0, y: 1.85, w: 3.8, h: 2.2, align: "left", valign: "top", margin: 12, line: { color: c, width: 1.5 }, name: `!!e-s${i}` }));
  [["α = 0.5", "size of the uncertainty bonus"], ["γ = 0.995", "forgetting per update"], ["λ = 1", "ridge penalty / starting A"]].forEach(([a, b], i) =>
    label(s, [{ text: a, options: { bold: true, fontSize: 16, breakLine: true } }, { text: b, options: { fontSize: 12, color: HEX.muted } }], { x: 0.6 + i * 2.65, y: 4.3, w: 2.45, h: 0.95, fill: { color: HEX.sand }, line: { type: "none" }, name: `!!l-p${i}` }));
  calc(s, ["Same start options as epsilon-greedy, but its own state: name “linucb”.", "", "No separate training phase.", { t: "Settings → Policy: α, γ and λ live in the policy (policy_config.py).", color: HEX.muted, size: 13, gap: 6 }]);
  s.addNotes("LinUCB starts like epsilon-greedy, empty or from the frozen router, but keeps its own state. Three settings control it: the bonus size alpha, the forgetting factor gamma and the ridge penalty lambda.");

  s = stepSlide(sec, T1, sub, 1, col);
  table(s, [["routing_events", "example"], ["features", "x = [0.21, −0.40, 1.65, …]"], ["chosen_model", "claude-opus"], ["propensity", "1.0  (deterministic)"], ["quality · reward", `0.90 · ${f(W.q * 0.9 + K.S, 2)}`]], { x: 0.6, y: 1.8, w: 4.6, colW: [2.0, 2.6], rowH: 0.45, fontSize: 12, boldFirst: true });
  table(s, [["policy_states “linucb”", "note"], ["v1", "warm start from frozen v1"], ["v2", "batch update with 50 outcomes"], ["v3 (active)", "batch update with 50 outcomes"]], { x: 5.4, y: 1.8, w: 3.0, colW: [1.1, 1.9], rowH: 0.55, fontSize: 12, hl: 2 });
  label(s, "Propensity is always 1, so LinUCB's own logs cannot evaluate other policies (IPS). That is why epsilon-greedy is the main method.", { x: 0.6, y: 4.6, w: 7.8, h: 0.8, fontSize: 13, italic: true, fill: { color: HEX.sand }, line: { type: "none" }, name: "!!e-ips" });
  calc(s, ["Saved exactly like epsilon-greedy:", "requests in routing_events", "arms in policy_states, new version per batch", "", "Same JSON: A, b, n per model, plus n_scored.", { t: "Rollback in Settings → Policy.", color: HEX.muted, size: 13, gap: 6 }]);
  s.addNotes("LinUCB saves its knowledge in the same way. The one difference in the logs is the propensity: LinUCB is deterministic, so its logs cannot be used for unbiased offline evaluation of other policies.");

  s = stepSlide(sec, T1, sub, 2, col);
  const Ul = { L: [0.625, 0.110], F: [0.677, 0.098], S: [0.394, 0.389] };
  const x0 = 2.0, sc = 4.6;
  ["L", "F", "S"].forEach((k, i) => {
    const y = 2.0 + i * 0.95, [base, bonus] = Ul[k], win = k === "S";
    T(s, TIER[k], { x: 0.6, y, w: 1.3, h: 0.42, valign: "middle", fontSize: 14, bold: win, objectName: `!!l-n${k}` });
    box(s, { x: x0, y, w: base * sc, h: 0.42, r: 0.06, fill: { color: MC[k] }, line: { type: "none" }, name: `!!l-b${k}` });
    box(s, { x: x0 + base * sc, y, w: bonus * sc, h: 0.42, r: 0.06, fill: { color: MC[k], transparency: 65 }, line: { color: MC[k], width: 1, dashType: "dash" }, name: `!!l-u${k}` });
    T(s, f(base + bonus, 3), { x: x0 + (base + bonus) * sc + 0.1, y, w: 0.9, h: 0.42, valign: "middle", fontSize: 14, bold: win, objectName: `!!l-v${k}` });
  });
  T(s, "solid = utility from predicted quality · light = bonus α·u", { x: 0.6, y: 4.85, w: 7.8, h: 0.3, fontSize: 12, color: HEX.muted, objectName: "!!l-key" });
  label(s, "Opus has been tried once → large bonus → LinUCB tries it (greedy would pick Haiku)", { x: 0.6, y: 5.3, w: 7.8, h: 0.6, fill: { color: col, transparency: 85 }, line: { type: "none" }, bold: true, color: col, fontSize: 13, name: "!!e-res" });
  calc(s, ["score = 0.5·Q′ + 0.3c + 0.2l", "      + α·√(x^{T}A^{−1}x)", "      − λ_{p}·min(C / C_{ref}, 1)", "", "λ_{p} = budget pacer, from platform spend on each request (0 on pace)", "", "highest score wins, no randomness"]);
  s.addNotes("To decide, LinUCB adds an uncertainty bonus to each model's utility and subtracts a budget penalty when spending runs ahead of pace. A model it has rarely tried gets a big bonus, so it is tried on purpose. Here that is the strong model.");

  s = stepSlide(sec, T1, sub, 3, col);
  s.addChart(pres.charts.LINE, [
    { name: "LinUCB (γ = 0.995)", labels: simD.checkpoints.map((c) => `${c}`), values: simD.res[0.995].map((v) => +v.toFixed(3)) },
    { name: "No forgetting (γ = 1)", labels: simD.checkpoints.map((c) => `${c}`), values: simD.res[1.0].map((v) => +v.toFixed(3)) },
  ], {
    x: 0.6, y: 1.75, w: 7.8, h: 3.3, chartColors: [col, HEX.faint], lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 7,
    showTitle: true, title: "Haiku's predicted quality after its real quality drops from 0.66 to 0.45", titleFontSize: 12, titleColor: HEX.ink, titleFontFace: "+mn-lt",
    showLegend: true, legendPos: "b", legendFontSize: 11, legendFontFace: "+mn-lt", legendColor: HEX.ink,
    catAxisTitle: "new ratings after the change", showCatAxisTitle: true, catAxisTitleFontSize: 11, catAxisTitleColor: HEX.muted,
    catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
    valAxisMinVal: 0.3, valAxisMaxVal: 0.7, valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" },
  });
  table(s, [["Rating's age (updates ago)", "0", "100", "200", "500", "1000"], ["Weight left (0.995^{age})", "1.00", f(0.995 ** 100), f(0.995 ** 200), f(0.995 ** 500), f(0.995 ** 1000, 3)]], { x: 0.6, y: 5.3, w: 7.8, colW: [2.8, 1.0, 1.0, 1.0, 1.0, 1.0], rowH: 0.42, fontSize: 12 });
  calc(s, ["Every 50 scored answers:", "A ← γA + (1−γ)λI + x x^{T}", "b ← γb + Q·x", "", "memory ≈ 1 / (1 − γ) = 200 answers", "", `after 400 new ratings: **${f(simD.res[0.995][4], 2)}** with forgetting vs ${f(simD.res[1.0][4], 2)} without`, { t: "Old evidence fades, so uncertainty grows back and the router re-checks a changed model.", color: HEX.muted, size: 13, gap: 4 }]);
  s.addNotes(`LinUCB improves in the same batches as epsilon-greedy, with one addition: every update multiplies the old evidence by gamma. A rating two hundred updates old keeps about a third of its weight. In the simulation, after a provider change the fast model's real quality drops from 0.66 to 0.45. With forgetting, the prediction follows it to ${f(simD.res[0.995][4], 2)} after 400 new ratings; without forgetting it is still at ${f(simD.res[1.0][4], 2)}.`);
}

/* ================================================================ summary */
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Summary" });
  s.addText("Side by side", { placeholder: "title" });
  s.addText("Same arms and features; different rules for learning and exploring", { placeholder: "body" });
  const rows = [
    ["", "Rules", "Frozen ridge", "Epsilon-greedy", "LinUCB"],
    ["Learns from data", "no", "once, offline", "continuously", "continuously"],
    ["Training data", "none", "360 benchmark requests × 3 models", "live ratings (and benchmark via warm start)", "live ratings (and benchmark via warm start)"],
    ["Saved in", "code", "policy_states “frozen”", "policy_states “bandit”", "policy_states “linucb”"],
    ["Versions / rollback", "git only", "yes", "yes, one per batch", "yes, one per batch"],
    ["Decides by", "thresholds → tier", "highest predicted utility", "highest utility, or random with prob. ε", "utility + bonus − budget penalty"],
    ["Exploration", "none", "none", "random, ε 0.10 → 0.02", "targeted at uncertainty"],
    ["Forgets old data", "–", "–", "no", "yes, γ = 0.995"],
    ["Propensity logged", "1", "1", "true probability (IPS)", "1"],
    ["Role", "baseline, fallback", "baseline (RQ2)", "main method", "stretch goal"],
  ];
  const cols = [HEX.ink, ROUTER.rules, ROUTER.frozen, ROUTER.bandit, ROUTER.linucb];
  const head = rows[0].map((t, j) => ({ text: t, options: { bold: true, color: j ? "FFFFFF" : HEX.muted, fill: { color: j ? cols[j] : HEX.sand } } }));
  const body = rows.slice(1).map((r) => r.map((t, j) => ({ text: t, options: { bold: j === 0, color: HEX.ink, fill: { color: j === 0 ? HEX.sand : HEX.card } } })));
  s.addTable([head, ...body], { x: 0.6, y: 1.72, w: 12.13, colW: [2.1, 1.9, 2.55, 2.8, 2.78], fontSize: 12, rowH: 0.47, valign: "middle", margin: 0.06, border: { type: "solid", pt: 0.75, color: HEX.line } });
  s.addNotes("All learning routers share the same arms and features. They differ in when they learn, how they explore and whether they forget. Only epsilon-greedy logs true propensities, which is why it is the main method.");
}
{
  const s = addSlide({ masterName: "SIM", sectionTitle: "Summary" });
  s.addText("Keeping learning safe", { placeholder: "title" });
  s.addText("Controls the superadmin has, and guards built into the code", { placeholder: "body" });
  table(s, [["Name", "Version", "State", "Scored", "Note", ""], ["bandit", "3", "active", "100", "batch update with 50 outcomes", ""], ["bandit", "2", "", "50", "batch update with 50 outcomes", "Rollback"], ["bandit", "1", "", "0", "warm start from frozen v1", "Rollback"], ["frozen", "1", "active", "0", "trained on 360 train requests", ""]], { x: 0.6, y: 1.8, w: 7.8, colW: [0.95, 0.85, 0.85, 0.85, 3.1, 1.2], rowH: 0.45, fontSize: 12, hl: 0 });
  ["Warm start", "Apply", "Rollback"].forEach((t, i) => label(s, t, { x: 0.6 + i * 1.55, y: 4.25, w: 1.4, h: 0.48, fontSize: 13, bold: true, name: `!!g-b${i}` }));
  T(s, "Settings → Policy (superadmin): switch router, warm start the bandits, apply a partial batch now, roll back to any version.", { x: 0.6, y: 4.95, w: 7.8, h: 0.7, fontSize: 13, color: HEX.muted, objectName: "!!g-t" });
  calc(s, ["• Hard limits run before every router", "• Benchmark (eval) runs never train live learners", "• Feature size changed → saved state ignored, cold start", "• New version per batch; old ones kept", "• In-memory cache reloads when the version changes", "• Rules always available as fallback", "• Failures teach the arm −1"], "Guards");
  s.addNotes("Learning is controlled. The superadmin can switch routers, warm start, force a batch, and roll back to any saved version. In the code, hard limits always run first, benchmark runs never leak into the live learners, and a change in features forces a clean start instead of using mismatched state.");
}
addDark("Summary", "Fixed, learn once, keep learning", "Rules never change · the frozen ridge router learns once from the benchmark · epsilon-greedy and LinUCB keep learning from rated answers, one saved version every 50 ratings.",
  "Closing. The rules and frozen router are the two baselines. Epsilon-greedy is the main method because it learns online and its logs support unbiased evaluation. LinUCB is the stretch goal: it explores more cleverly and forgets, but its logs cannot evaluate other policies.");

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
  const clean = new JSZip();
  for (const n of Object.keys(zip.files)) { if (zip.files[n].dir) continue; clean.file(n, await zip.file(n).async("nodebuffer"), { createFolders: false }); }
  fs.writeFileSync(OUT, await clean.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  console.log(`wrote ${OUT} with ${slides.length} slides; simE=${simE.map((p) => p.pred.toFixed(3)).join(",")} drift=${simD.res[0.995].map((v) => v.toFixed(3)).join(",")} | ${simD.res[1.0].map((v) => v.toFixed(3)).join(",")}`);
})();
