/* 学生端：选点、路线规划、结果展示 */
const ICONS = {
  elevator: "🛗", stairs: "🪜", door: "🚪", ramp: "♿",
  slope: "⛰️", corridor: "🏢", path: "🚶",
};

const state = {
  pois: [],
  poiIds: [],
  start: null,
  goal: null,
  mode: "accessible",
  pickStage: 0, // 0=下次点击设起点 1=设终点
};

let map;

async function init() {
  const [graphRes, poisRes] = await Promise.all([Api.graph(), Api.pois()]);
  state.pois = poisRes.pois;
  state.poiIds = new Set(state.pois.map((p) => p.id));

  map = new CampusMap(document.getElementById("map"), {
    showLabels: true,
    onNodeClick: (n) => {
      if (!state.poiIds.has(n.id)) return; // 只允许选择房间/出入口等 POI
      if (state.pickStage === 0 || (!state.start)) {
        state.start = n.id; state.pickStage = 1;
      } else {
        state.goal = n.id; state.pickStage = 0;
      }
      syncSelectors();
      map.setSelected([state.start, state.goal].filter(Boolean));
      if (state.start && state.goal) plan();
    },
  });
  map.setGraph(graphRes.graph);

  fillSelectors();
  bindEvents();

  // 默认示例：宿舍 305 -> 教学楼 204
  state.start = "dorm_room";
  state.goal = "teach_room";
  syncSelectors();
  map.setSelected([state.start, state.goal]);
  plan();
}

function groupName(p) {
  return p.building_label ? `${p.building_label} · ${p.type === "room" ? "房间" : "地点"}` : "校园公共点";
}

function fillSelectors() {
  const groups = {};
  state.pois.forEach((p) => {
    const g = groupName(p);
    (groups[g] = groups[g] || []).push(p);
  });
  ["startSel", "goalSel"].forEach((selId) => {
    const sel = document.getElementById(selId);
    sel.innerHTML = "<option value=''>请选择…</option>";
    Object.entries(groups).forEach(([gname, pois]) => {
      const og = document.createElement("optgroup");
      og.label = gname;
      pois.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.name}${p.floor ? `（${p.floor}F` : ""}${p.floor ? "）" : ""}`;
        og.appendChild(opt);
      });
      sel.appendChild(og);
    });
  });
}

function syncSelectors() {
  document.getElementById("startSel").value = state.start || "";
  document.getElementById("goalSel").value = state.goal || "";
}

function bindEvents() {
  document.getElementById("startSel").addEventListener("change", (e) => {
    state.start = e.target.value || null;
    map.setSelected([state.start, state.goal].filter(Boolean));
  });
  document.getElementById("goalSel").addEventListener("change", (e) => {
    state.goal = e.target.value || null;
    map.setSelected([state.start, state.goal].filter(Boolean));
  });
  document.querySelectorAll(".mode-opt").forEach((opt) => {
    opt.addEventListener("click", () => {
      document.querySelectorAll(".mode-opt").forEach((o) => o.classList.remove("active"));
      opt.classList.add("active");
      opt.querySelector("input").checked = true;
      state.mode = opt.dataset.mode;
    });
  });
  document.getElementById("planBtn").addEventListener("click", plan);
  document.getElementById("clearBtn").addEventListener("click", () => {
    state.start = state.goal = null; state.pickStage = 0;
    syncSelectors();
    map.setSelected([]);
    map.clearRoute();
    document.getElementById("resultCard").hidden = true;
  });
}

async function plan() {
  if (!state.start || !state.goal) {
    toast("请先选择起点和终点", true);
    return;
  }
  const res = await Api.route(state.start, state.goal, state.mode);
  if (!res.ok) {
    toast(res.error || "路线规划失败", true);
    return;
  }
  const rt = res.route;
  const cmp = state.mode === "accessible" ? res.regular_comparison : null;
  map.setRoute(rt, cmp);
  renderResult(rt, cmp);
  document.getElementById("resultCard").hidden = false;
}

function renderResult(rt, cmp) {
  const acc = rt.mode === "accessible";
  document.getElementById("summary").innerHTML = `
    <div class="summary-grid">
      <div class="stat"><div class="v">≈ ${rt.distance_m} m</div><div class="k">路线长度</div></div>
      <div class="stat"><div class="v">≈ ${rt.duration_min} 分钟</div><div class="k">预计用时</div></div>
      <div class="stat ${rt.stairs_segments ? "bad" : ""}"><div class="v">${rt.stairs_segments}</div><div class="k">途经台阶段</div></div>
      <div class="stat ${rt.steep_segments ? "bad" : ""}"><div class="v">${rt.steep_segments}</div><div class="k">途经陡坡道</div></div>
      <div class="stat"><div class="v">${rt.elevator_segments}</div><div class="k">乘用电梯</div></div>
      <div class="stat"><div class="v">${rt.weight}</div><div class="k">综合权重（越低越优）</div></div>
    </div>`;

  const cmpBox = document.getElementById("compare");
  if (acc && cmp) {
    cmpBox.innerHTML = `<div class="compare-box">
      <b>与普通步行路线对比：</b><br>
      普通路线长 ${cmp.distance_m} m、约 ${cmp.duration_min} 分钟，
      含 <b>${cmp.stairs_segments}</b> 段台阶、<b>${cmp.steep_segments}</b> 段陡坡；
      本方案为避开障碍多走约 <b>${Math.max(0, (rt.distance_m - cmp.distance_m).toFixed(0))} m</b>，
      但全程 ${rt.stairs_segments === 0 ? "✅ 无台阶" : "仍有台阶"}、
      ${rt.steep_segments === 0 ? "✅ 无陡坡" : "仍有陡坡"}。
      （蓝色虚线为普通路线）
    </div>`;
  } else {
    cmpBox.innerHTML = "";
  }

  const warnBox = document.getElementById("warnings");
  if (rt.warnings.length) {
    warnBox.innerHTML = rt.warnings.map((w) => `<div class="warn-item">⚠️ ${w}</div>`).join("");
  } else if (acc) {
    warnBox.innerHTML = `<div class="ok-item">✅ 该路线全程由平缓通道、坡道与电梯组成，无楼梯与陡坡</div>`;
  } else {
    warnBox.innerHTML = "";
  }

  document.getElementById("steps").innerHTML = rt.instructions.map((s) => `
    <li>
      <div class="step-icon">${ICONS[s.icon] || "•"}</div>
      <div><span class="step-seq">第 ${s.seq} 步</span><br>${s.text}</div>
    </li>`).join("");
}

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2400);
}

init();
