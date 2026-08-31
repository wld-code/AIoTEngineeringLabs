// Lab 5 — Device Twin UI. Polls GET /api/twin/sim-001 once a second and
// renders it. No build step, no framework: the point of this file is to be
// readable, not to demonstrate frontend engineering.

const DEVICE = "sim-001";
let lastArrivalTimestamp = null;
const MAX_ARRIVALS = 8;

function fmt(value, suffix = "") {
  return value === null || value === undefined ? "-" : `${value}${suffix}`;
}

function setConnStatus(ok) {
  const el = document.getElementById("conn-status");
  el.textContent = ok ? "connected" : "unreachable";
  el.className = "badge " + (ok ? "badge-ok" : "badge-bad");
}

function renderTelemetry(twin) {
  const t = twin.telemetry || {};
  document.getElementById("temp").textContent = fmt(t.temperature_c, " °C");
  document.getElementById("avg-temp").textContent = fmt(t.average_temperature_c, " °C");
  const alarmEl = document.getElementById("alarm");
  alarmEl.textContent = t.alarm === undefined ? "-" : (t.alarm ? "ON" : "off");
  alarmEl.className = t.alarm ? "on" : "";
  document.getElementById("last-update").textContent = fmt(t.timestamp);
  document.getElementById("staleness").textContent = fmt(twin.staleness_seconds, " s");
}

function renderSync(twin) {
  const desired = twin.desired || {};
  const reported = twin.reported || {};
  document.getElementById("reported-interval").textContent = fmt(reported.reporting_interval_s, " s");
  document.getElementById("desired-interval").textContent = fmt(desired.reporting_interval_s, " s");

  const statusEl = document.getElementById("command-status");
  const status = twin.command_status || "-";
  statusEl.textContent = status;
  statusEl.className = status;

  const syncEl = document.getElementById("synchronized");
  syncEl.textContent = twin.synchronized ? "Yes" : "No";
  syncEl.className = twin.synchronized ? "yes" : "no";

  const feedback = document.getElementById("submit-feedback");
  feedback.className = "feedback";
  if (status === "pending") {
    feedback.textContent = "Pending - waiting for the device to acknowledge...";
    feedback.classList.add("pending");
  } else if (status === "applied") {
    feedback.textContent = "Applied - the device confirmed this interval.";
    feedback.classList.add("applied");
  } else if (status === "rejected") {
    feedback.textContent = "Rejected - " + (reported.reason || "the device refused this value.");
    feedback.classList.add("rejected");
  } else {
    feedback.textContent = "";
  }
}

function renderArrivals(twin) {
  const t = twin.telemetry || {};
  if (!t.timestamp || t.timestamp === lastArrivalTimestamp) return;

  const list = document.getElementById("arrivals");
  let gapText = "";
  if (lastArrivalTimestamp) {
    const gap = (new Date(t.timestamp) - new Date(lastArrivalTimestamp)) / 1000;
    gapText = `+${gap.toFixed(1)} s`;
  }
  lastArrivalTimestamp = t.timestamp;

  const li = document.createElement("li");
  const time = document.createElement("span");
  time.textContent = t.timestamp.slice(11, 23); // HH:MM:SS.mmm
  const gap = document.createElement("span");
  gap.className = "gap";
  gap.textContent = gapText;
  li.appendChild(time);
  li.appendChild(gap);
  list.prepend(li);

  while (list.children.length > MAX_ARRIVALS) {
    list.removeChild(list.lastChild);
  }
}

async function poll() {
  try {
    const res = await fetch(`/api/twin/${DEVICE}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const twin = await res.json();
    setConnStatus(true);
    renderTelemetry(twin);
    renderSync(twin);
    renderArrivals(twin);
  } catch (err) {
    setConnStatus(false);
  }
}

async function applyInterval(value) {
  const feedback = document.getElementById("submit-feedback");
  feedback.textContent = "Sending...";
  feedback.className = "feedback pending";
  try {
    const res = await fetch(`/api/twin/${DEVICE}/desired`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reporting_interval_s: Number(value) }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      feedback.textContent = "Request rejected by the API: " + (body.detail || res.status);
      feedback.className = "feedback rejected";
      return;
    }
    // The next poll() tick will pick up command_status and replace this
    // message with the live pending/applied/rejected state.
  } catch (err) {
    feedback.textContent = "Could not reach the twin API.";
    feedback.className = "feedback rejected";
  }
}

document.getElementById("apply-form").addEventListener("submit", (evt) => {
  evt.preventDefault();
  const value = document.getElementById("interval-input").value;
  applyInterval(value);
});

document.querySelectorAll(".quick").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.getElementById("interval-input").value = btn.dataset.value;
    applyInterval(btn.dataset.value);
  });
});

poll();
setInterval(poll, 1000);
