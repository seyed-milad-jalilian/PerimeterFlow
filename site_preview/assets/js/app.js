const canvas = document.getElementById("lab-chart");
const ctx = canvas ? canvas.getContext("2d") : null;
let worker = null;

function fmtPct(x) {
  return (x * 100).toFixed(1) + "%";
}

function getParams() {
  return {
    seed: 202601,
    penetration: Number(document.getElementById("ctl-penetration").value) / 100,
    arterialBias: Number(document.getElementById("ctl-bias").value),
    spikeProb: Number(document.getElementById("ctl-spike").value) / 100,
    dropoutProb: Number(document.getElementById("ctl-dropout").value) / 100,
    delaySteps: Number(document.getElementById("ctl-delay").value),
    penetrationErrorPct: Number(document.getElementById("ctl-perr").value),
  };
}

function syncOutputs() {
  const ids = ["penetration", "bias", "spike", "dropout", "delay", "perr"];
  for (const id of ids) {
    const input = document.getElementById("ctl-" + id);
    const out = document.getElementById("out-" + id);
    if (input && out) out.value = input.value;
  }
}

function ensureWorker() {
  if (worker) return worker;
  worker = new Worker(new URL("../worker/lab_worker.js", import.meta.url), { type: "module" });
  return worker;
}

const COLORS = {
  truth: "#4fd1c5",
  uncontrolled: "#f6ad55",
  estimate: "#63b3ed",
  crit: "#f56565",
};

function drawChart(series) {
  if (!ctx) return;
  const W = canvas.width;
  const H = canvas.height;
  const pad = { l: 52, r: 16, t: 24, b: 32 };
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "rgba(0,0,0,0)";
  const vals = series.flatMap((p) => [p.truth_controlled, p.truth_uncontrolled, p.estimate, p.n_crit]);
  const vMax = Math.max(...vals) * 1.08 || 1;
  const x = (i) => pad.l + (i / Math.max(1, series.length - 1)) * (W - pad.l - pad.r);
  const y = (v) => H - pad.b - (v / vMax) * (H - pad.t - pad.b);

  ctx.strokeStyle = "rgba(120,130,150,0.35)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let g = 0; g <= 5; g++) {
    const gy = pad.t + (g / 5) * (H - pad.t - pad.b);
    ctx.moveTo(pad.l, gy);
    ctx.lineTo(W - pad.r, gy);
  }
  for (let i = 0; i <= 6; i++) {
    const gx = pad.l + (i / 6) * (W - pad.l - pad.r);
    ctx.moveTo(gx, pad.t);
    ctx.lineTo(gx, H - pad.b);
  }
  ctx.stroke();

  ctx.fillStyle = "#9aa5b5";
  ctx.font = "11px monospace";
  ctx.textAlign = "right";
  for (let g = 0; g <= 5; g++) {
    const v = vMax * (1 - g / 5);
    ctx.fillText(Math.round(v), pad.l - 6, pad.t + (g / 5) * (H - pad.t - pad.b) + 4);
  }
  ctx.textAlign = "center";
  ctx.fillText("time (min, 60 s steps)", pad.l + (W - pad.l - pad.r) / 2, H - 8);

  function line(getter, color, dash) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    series.forEach((p, i) => {
      const px = x(i);
      const py = y(getter(p));
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  line((p) => p.truth_uncontrolled, COLORS.uncontrolled, [4, 3]);
  line((p) => p.estimate, COLORS.estimate, [7, 4]);
  line((p) => p.truth_controlled, COLORS.truth, []);
  line((p) => p.n_crit, COLORS.crit, [2, 3]);

  const legend = [
    ["truth (Smith-PI closed loop)", COLORS.truth],
    ["truth (uncontrolled)", COLORS.uncontrolled],
    ["PC-AKF estimate", COLORS.estimate],
    ["N crit", COLORS.crit],
  ];
  ctx.textAlign = "left";
  legend.forEach(([label, color], i) => {
    ctx.fillStyle = color;
    ctx.fillRect(pad.l + 8 + i * 210, 6, 14, 3);
    ctx.fillStyle = "#c7d0dc";
    ctx.fillText(label, pad.l + 28 + i * 210, 12);
  });
}

function onResult(result) {
  drawChart(result.series);
  document.getElementById("m-reject").textContent = fmtPct(result.metrics.gate_rejection_rate);
  document.getElementById("m-nrmse").textContent = fmtPct(result.metrics.nrmse_estimate);
  document.getElementById("m-overshoot").textContent = fmtPct(result.metrics.overshoot_controlled);
  document.getElementById("m-overshoot-unc").textContent = fmtPct(result.metrics.overshoot_uncontrolled);
  document.getElementById("m-u").textContent = result.metrics.u_final.toFixed(3);
  document.getElementById("lab-disclaimer").textContent = result.disclaimer;
  const runBtn = document.getElementById("lab-run");
  runBtn.disabled = false;
  runBtn.textContent = "Run Dry-Run";
}

async function loadArtifactStatus() {
  const badge = document.getElementById("status-badge");
  try {
    const res = await fetch(new URL("../../data/labs/perimeterflow/ensemble.json", import.meta.url));
    const artifact = await res.json();
    const meta = artifact.meta || artifact;
    if (meta.status === "planned") {
      badge.textContent = "Pending Execution (Pre-registered in ANALYSIS_PLAN.md)";
      badge.className = "badge badge-planned";
    } else if (meta.status) {
      badge.textContent = "Artifact status: " + meta.status;
      badge.className = "badge badge-ok";
    } else {
      badge.textContent = "Artifact status: unknown";
      badge.className = "badge badge-planned";
    }
  } catch {
    badge.textContent = "Pending Execution (Pre-registered in ANALYSIS_PLAN.md)";
    badge.className = "badge badge-planned";
  }
}

function initLens() {
  const sciBtn = document.getElementById("lens-science");
  const opsBtn = document.getElementById("lens-gitops");
  const sciPanel = document.getElementById("lens-science-panel");
  const opsPanel = document.getElementById("lens-gitops-panel");
  function select(sci) {
    sciBtn.classList.toggle("lens-active", sci);
    opsBtn.classList.toggle("lens-active", !sci);
    sciBtn.setAttribute("aria-pressed", String(sci));
    opsBtn.setAttribute("aria-pressed", String(!sci));
    sciPanel.classList.toggle("lens-hidden", !sci);
    opsPanel.classList.toggle("lens-hidden", sci);
  }
  sciBtn.addEventListener("click", () => select(true));
  opsBtn.addEventListener("click", () => select(false));
}

function initTabs() {
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function select(tab) {
    for (const t of tabs) {
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      const active = t === tab;
      t.setAttribute("aria-selected", String(active));
      panel.classList.toggle("tab-hidden", !active);
    }
  }
  for (const t of tabs) t.addEventListener("click", () => select(t));
}

function initLabForm() {
  const form = document.getElementById("lab-controls");
  if (!form) return;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const runBtn = document.getElementById("lab-run");
    runBtn.disabled = true;
    runBtn.textContent = "Running…";
    const w = ensureWorker();
    w.onmessage = (e) => {
      if (e.data.type === "result") onResult(e.data.result);
      else if (e.data.type === "error") {
        document.getElementById("lab-disclaimer").textContent = "Worker error: " + e.data.message;
        runBtn.disabled = false;
        runBtn.textContent = "Run Dry-Run";
      }
    };
    w.postMessage({ type: "run", params: getParams() });
  });
  document.getElementById("lab-controls").addEventListener("input", syncOutputs);
  syncOutputs();
}

initLens();
initTabs();
initLabForm();
loadArtifactStatus();
