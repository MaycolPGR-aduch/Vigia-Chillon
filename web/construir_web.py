# -*- coding: utf-8 -*-
"""
Construye web/index.html a partir del diseño del tablero, reemplazando la capa de
datos embebida por llamadas a la API. El tablero no contiene ningún dato del
distrito: todo llega de /api/*.

Uso:  python web/construir_web.py <ruta_plantilla.html>
"""
import re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "web" / "index.html"

NUEVO_JS = r"""
/* ------------------------------------------------------------------
   Capa de datos: todo procede de la API. La página no incrusta ningún
   dato del distrito; si la API no responde, no hay tablero.
   ------------------------------------------------------------------ */
const API = (location.origin.startsWith("http") ? location.origin : "http://127.0.0.1:8000");
let CELDAS = [], PUNTOS = [], RIO = [], MALLA = {}, RIESGO = null, FICHA = {};
let fechaActual = "2023-03-11", capa = "riesgo", sel = null, retrained = false;

const PRESETS = [
  { f: "2023-03-11", nom: "Ciclón Yaku", sub: "11 mar 2023" },
  { f: "2017-03-16", nom: "Niño Costero", sub: "16 mar 2017" },
  { f: "2015-08-03", nom: "Día seco", sub: "3 ago 2015" },
];
const CLASES = [
  { n: "Bajo", v: "--r1" }, { n: "Medio", v: "--r2" },
  { n: "Alto", v: "--r3" }, { n: "Muy alto", v: "--r4" },
];
const colorClase = n => (CLASES.find(c => c.n === n) || CLASES[0]).v;
const cssv = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = n => (n == null ? "—" : Number(n).toLocaleString("es-PE"));

async function pedir(ruta) {
  const t0 = performance.now();
  const r = await fetch(API + ruta, { headers: { "Accept": "application/json" } });
  const ms = performance.now() - t0;
  if (!r.ok) {
    let detalle = r.statusText;
    try { detalle = (await r.json()).detail || detalle; } catch (e) {}
    throw new Error(`${r.status} · ${detalle}`);
  }
  const j = await r.json();
  registrarLlamada(ruta, r.status, ms);
  return j;
}

const llamadas = [];
function registrarLlamada(ruta, estado, ms) {
  llamadas.unshift({ ruta, estado, ms: Math.round(ms), hora: new Date().toLocaleTimeString("es-PE") });
  llamadas.splice(8);
  const el = document.getElementById("api-log");
  if (el) el.innerHTML = llamadas.map(l =>
    `<div class="apirow"><code>${l.ruta}</code><span class="ok">${l.estado}</span><span class="ms">${l.ms} ms</span></div>`).join("");
}

/* nombre de sector: junto al cauce, el punto crítico más cercano */
function sectorDe(c) {
  if (c.dist_rio_m != null && c.dist_rio_m < 1300 && PUNTOS.length) {
    let mejor = null, d0 = Infinity;
    for (const p of PUNTOS) {
      const dx = (p.lon - c.lon) * Math.cos(c.lat * Math.PI / 180), dy = p.lat - c.lat;
      const d = Math.hypot(dx, dy);
      if (d < d0) { d0 = d; mejor = p; }
    }
    if (mejor) return mejor.nombre;
  }
  if (c.fila >= 27) return "Las Lomas";
  if (c.fila >= 20) return "Zapallal";
  if (c.fila >= 13) return "Puente Piedra centro";
  return "Laderas de Chillón";
}

const riesgoDe = id => (RIESGO && RIESGO.mapa[id]) || { indice: 0, clase: "Bajo" };
function valorCapa(c) {
  if (capa === "susc") return c.susceptibilidad;
  if (capa === "expo") return c.exposicion;
  return riesgoDe(c.spatial_id).indice;
}

/* ---------------- mapa ---------------- */
const S = 10, PADM = 3;
const mapEl = document.getElementById("map");
const gx = c => PADM + c.columna * S;
const gy = c => PADM + (MALLA.fila_max - c.fila) * S;

function drawMap() {
  const W = (MALLA.columna_max + 1) * S + PADM * 2, H = (MALLA.fila_max + 1) * S + PADM * 2;
  function fit(xs, ys) {
    const n = xs.length, sx = xs.reduce((a, b) => a + b, 0), sy = ys.reduce((a, b) => a + b, 0);
    const sxy = xs.reduce((a, b, i) => a + b * ys[i], 0), sxx = xs.reduce((a, b) => a + b * b, 0);
    const m = (n * sxy - sx * sy) / (n * sxx - sx * sx);
    return [m, (sy - m * sx) / n];
  }
  const [mx, bx] = fit(CELDAS.map(c => c.lon), CELDAS.map(c => gx(c) + S / 2));
  const [my, by] = fit(CELDAS.map(c => c.lat), CELDAS.map(c => gy(c) + S / 2));
  const px = lon => mx * lon + bx, py = lat => my * lat + by;

  const cells = CELDAS.map(c => {
    const v = valorCapa(c);
    const col = capa === "riesgo" ? cssv(colorClase(riesgoDe(c.spatial_id).clase)) : cssv("--accent");
    const op = capa === "riesgo" ? 1 : (0.12 + 0.88 * v);
    return `<rect class="cell" data-id="${c.spatial_id}" x="${gx(c)}" y="${gy(c)}" width="${S}" height="${S}" fill="${col}" fill-opacity="${op.toFixed(2)}"><title>${c.spatial_id} · ${sectorDe(c)}</title></rect>`;
  }).join("");
  const river = RIO.map(p => `${p[0]},${p[1]}`).join(" ");
  const marks = PUNTOS.map(p => {
    const x = px(p.lon).toFixed(1), y = py(p.lat).toFixed(1);
    return `<g><circle cx="${x}" cy="${y}" r="3.4" fill="none" stroke="${cssv('--ink')}" stroke-width="1.5"/><circle cx="${x}" cy="${y}" r="1.3" fill="${cssv('--ink')}"/><title>${p.nombre}</title></g>`;
  }).join("");
  mapEl.setAttribute("viewBox", `0 0 ${W} ${H}`);
  mapEl.innerHTML = `${cells}
    <polyline points="${river}" fill="none" stroke="${cssv('--accent')}" stroke-width="2.2" stroke-opacity=".85" stroke-linecap="round" stroke-linejoin="round"/>
    ${marks}
    <text x="${W - 4}" y="12" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="7" fill="${cssv('--ink-3')}">N ↑</text>`;
  if (sel) { const r = mapEl.querySelector(`[data-id="${sel}"]`); if (r) r.setAttribute("data-sel", "1"); }
  drawLegend();
}

function drawLegend() {
  const el = document.getElementById("legend");
  if (capa === "riesgo") {
    el.innerHTML = CLASES.map(c => `<div class="row"><span class="sw" style="background:var(${c.v})"></span>${c.n}</div>`).join("")
      + `<div class="row" style="margin-top:3px"><span class="sw" style="background:var(--accent);border-radius:99px;height:3px"></span>Río Chillón · borde SE del distrito</div>`
      + `<div class="row"><span class="sw" style="border:1.5px solid var(--ink);background:transparent;border-radius:50%"></span>Punto crítico PREDES</div>`;
  } else {
    const t = capa === "susc" ? "Susceptibilidad territorial (fija)" : "Exposición: población, área construida y servicios";
    el.innerHTML = `<div class="row"><span class="sw" style="background:var(--accent);opacity:.15"></span>Menor</div>
      <div class="row"><span class="sw" style="background:var(--accent)"></span>Mayor</div>
      <div class="row" style="color:var(--ink-3)">${t}</div>`;
  }
}

/* ---------------- ficha de celda ---------------- */
async function pintaDetalle(id) {
  const el = document.getElementById("detail");
  if (!id) { el.innerHTML = `<h3>Detalle de celda</h3><div class="sid">Selecciona una celda del mapa</div>`; return; }
  const c = CELDAS.find(x => x.spatial_id === id);
  if (!c) return;
  el.innerHTML = `<h3>${sectorDe(c)}</h3><div class="sid">${c.spatial_id} · consultando la API…</div>`;
  let d;
  try { d = await pedir(`/api/celda/${id}?fecha=${fechaActual}`); }
  catch (e) { el.innerHTML = `<h3>${sectorDe(c)}</h3><div class="sid">${e.message}</div>`; return; }
  const r = d.riesgo, f = d.factores;
  const nombres = { cercania_al_rio: "Cercanía al río", terreno_plano: "Terreno plano", cota_baja: "Cota baja",
                    drenaje: "Drenaje", canales: "Canales", intensidad_climatica: "Intensidad de lluvia" };
  el.innerHTML = `<h3>${sectorDe(c)}</h3><div class="sid">${c.spatial_id}</div>
    <span class="pill" style="background:var(${colorClase(r.clase)})">${r.clase} · ${r.indice.toFixed(2)}</span>
    <dl class="kv">
      <dt>Distancia al río</dt><dd>${fmt(Math.round(c.dist_rio_m))} m</dd>
      <dt>Elevación media</dt><dd>${c.elev_media_m?.toFixed(1)} m</dd>
      <dt>Pendiente media</dt><dd>${c.pendiente_grados?.toFixed(2)}°</dd>
      <dt>Drenaje en celda</dt><dd>${fmt(Math.round(c.drenaje_m || 0))} m</dd>
      <dt>Canales</dt><dd>${c.canales_n ?? 0}</dd>
      <dt>Población (WorldPop)</dt><dd>${fmt(Math.round(c.poblacion || 0))}</dd>
      <dt>IE / salud</dt><dd>${c.ie_n ?? 0} / ${c.salud_n ?? 0}</dd>
      <dt>Punto crítico PREDES</dt><dd>${(c.predes_n || 0) > 0 ? "sí" : "—"}</dd>
    </dl>
    <div class="factors">${Object.entries(f).map(([k, v]) =>
      `<div class="factor"><span>${nombres[k] || k}</span><span class="bar"><i style="width:${(v * 100).toFixed(0)}%"></i></span><span class="pct">${(v * 100).toFixed(0)}</span></div>`).join("")}</div>
    <p style="font-size:11px;color:var(--ink-3);margin:11px 0 0">Valores servidos por <code>GET /api/celda/${id}?fecha=${fechaActual}</code>.</p>`;
}

/* ---------------- paneles ---------------- */
function pintaStrip() {
  const p = RIESGO.precipitacion, d = RIESGO.distrital, r = RIESGO.resumen;
  const [a, m, dd] = RIESGO.fecha.split("-");
  document.getElementById("s-fecha").textContent = `${dd}/${m}/${a}`;
  const ev = RIESGO.evento_registrado;
  document.getElementById("s-nombre").textContent = ev
    ? `Evento registrado: ${ev.fenomeno}` : "Sin evento registrado en SINPAD para esta fecha";
  document.getElementById("s-p3").textContent = (p.p_3d ?? 0).toFixed(2);
  document.getElementById("s-p7").textContent = (p.p_7d ?? 0).toFixed(2);
  document.getElementById("s-prob").textContent = d.probabilidad_modelo.toFixed(3);
  document.getElementById("s-clase").textContent = d.clase;
  document.getElementById("s-celdas").textContent = r.celdas_alto_o_muy_alto;
  document.getElementById("s-pob").textContent = fmt(r.poblacion_en_esas_celdas);
  document.getElementById("s-ms").textContent = RIESGO.calculo_ms;
}

function pintaResumen() {
  const d = RIESGO.distrital, p = RIESGO.precipitacion;
  document.getElementById("d-clase").textContent = d.clase;
  document.getElementById("d-clase").style.background = `var(${colorClase(d.clase)})`;
  document.getElementById("d-prob").textContent = d.probabilidad_modelo.toFixed(2);
  const fx = [
    ["Lluvia 3 días", Math.min(1, (p.p_3d || 0) / 20)],
    ["Lluvia 7 días", Math.min(1, (p.p_7d || 0) / 40)],
    ["Lluvia 30 días", Math.min(1, (p.p_30d || 0) / 90)],
    ["Probabilidad del modelo", d.probabilidad_modelo],
  ];
  document.getElementById("d-factors").innerHTML = fx.map(([k, v]) =>
    `<div class="factor"><span>${k}</span><span class="bar"><i style="width:${(v * 100).toFixed(0)}%"></i></span><span class="pct">${(v * 100).toFixed(0)}</span></div>`).join("");
}

function pintaPuntos() {
  document.getElementById("puntos").innerHTML = PUNTOS.map(p => {
    const cerca = CELDAS.map(c => ({ c, d: Math.hypot((p.lon - c.lon) * Math.cos(c.lat * Math.PI / 180), p.lat - c.lat) }))
      .sort((a, b) => a.d - b.d)[0];
    const r = riesgoDe(cerca.c.spatial_id);
    return `<div class="pt"><span class="dot" style="background:var(${colorClase(r.clase)})"></span>
      <span><span class="nm">${p.nombre}</span><br><span class="mt">${fmt(p.viviendas)} viv. · ${fmt(p.personas)} pers.</span></span>
      <span class="st" style="color:var(${colorClase(r.clase)})">${r.clase}</span></div>`;
  }).join("");
}

function pintaTabla() {
  const filas = CELDAS.map(c => ({ c, r: riesgoDe(c.spatial_id) }))
    .sort((a, b) => b.r.indice - a.r.indice).slice(0, 8);
  document.getElementById("tbody").innerHTML = filas.map(({ c, r }) =>
    `<tr data-id="${c.spatial_id}"><td class="num" style="font-size:11.5px">${c.spatial_id.replace("PP0500_", "")}</td>
      <td>${sectorDe(c)}</td><td class="n">${r.indice.toFixed(2)}</td>
      <td class="n">${fmt(Math.round(c.dist_rio_m))} m</td>
      <td class="n">${fmt(Math.round(c.poblacion || 0))}</td>
      <td><span class="pill" style="background:var(${colorClase(r.clase)});font-size:10px;padding:2px 8px">${r.clase}</span></td></tr>`).join("");
  document.querySelectorAll("#tbody tr").forEach(tr => tr.addEventListener("click", () => selecciona(tr.dataset.id)));
}

async function pintaChart() {
  const el = document.getElementById("chart");
  let datos;
  try { datos = await pedir(`/api/precipitacion?hasta=${fechaActual}&dias=14`); }
  catch (e) { el.innerHTML = ""; return; }
  const s = datos.serie.map(d => ({ d: d.fecha.slice(8) + "/" + d.fecha.slice(5, 7), mm: d.p_t0 || 0 }));
  const w = 560, h = 190, ml = 34, mr = 8, mt = 12, mb = 26;
  const max = Math.max(4, Math.ceil(Math.max(...s.map(d => d.mm))));
  const iw = w - ml - mr, ih = h - mt - mb, bw = iw / s.length;
  const y = v => mt + ih - (v / max) * ih;
  const grid = [0, max / 2, max].map(t =>
    `<line x1="${ml}" y1="${y(t).toFixed(1)}" x2="${w - mr}" y2="${y(t).toFixed(1)}" stroke="${cssv('--line-soft')}" stroke-width="1"/>
     <text x="${ml - 6}" y="${(y(t) + 3.5).toFixed(1)}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="9.5" fill="${cssv('--ink-3')}">${t % 1 ? t.toFixed(1) : t}</text>`).join("");
  const bars = s.map((d, i) => {
    const bh = Math.max(1, mt + ih - y(d.mm)), last = i === s.length - 1;
    return `<rect x="${(ml + i * bw + bw * 0.18).toFixed(1)}" y="${y(d.mm).toFixed(1)}" width="${(bw * 0.64).toFixed(1)}" height="${bh.toFixed(1)}" rx="1.5" fill="${last ? cssv('--r3') : cssv('--accent')}" fill-opacity="${last ? 1 : .55}"><title>${d.d}: ${d.mm.toFixed(2)} mm</title></rect>`;
  }).join("");
  const labs = s.map((d, i) => (i % 2 === 0 || i === s.length - 1)
    ? `<text x="${(ml + i * bw + bw / 2).toFixed(1)}" y="${h - 9}" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="9" fill="${cssv('--ink-3')}">${d.d}</text>` : "").join("");
  el.setAttribute("viewBox", `0 0 ${w} ${h}`);
  el.innerHTML = `${grid}${bars}${labs}<text x="${ml}" y="${mt - 3}" font-family="IBM Plex Sans, sans-serif" font-size="10" fill="${cssv('--ink-3')}">mm/día · CHIRPS · GET /api/precipitacion</text>`;
}

function pintaModelo() {
  const m = FICHA.metricas || {};
  const el = document.getElementById("modelo-info");
  if (!el) return;
  el.innerHTML = `
    <div class="lbox"><div class="k">Versión</div><div class="v num" style="font-size:15px">${FICHA.version || "—"}</div><div class="d">${FICHA.unidad || ""}</div></div>
    <div class="lbox"><div class="k">Positivos</div><div class="v num">${FICHA.positivos ?? "—"}</div><div class="d">${fmt(FICHA.no_etiquetados)} días no etiquetados</div></div>
    <div class="lbox"><div class="k">Negativos verificados</div><div class="v num">0</div><div class="d">la bitácora de vigías los producirá</div></div>
    <div class="lbox"><div class="k">Percentil mediano (LOO)</div><div class="v num">${m.percentil_mediano ?? "—"}</div><div class="d">línea base lluvia 3 d: ${m.lineas_base?.p_3d?.percentil_mediano ?? "—"}</div></div>`;
  const lim = document.getElementById("modelo-limites");
  if (lim && FICHA.limitaciones) lim.innerHTML = FICHA.limitaciones.map(t => `<li>${t}</li>`).join("");
}

/* ---------------- interacción ---------------- */
function selecciona(id) {
  sel = id;
  mapEl.querySelectorAll("rect.cell").forEach(r => r.removeAttribute("data-sel"));
  const r = mapEl.querySelector(`[data-id="${id}"]`);
  if (r) r.setAttribute("data-sel", "1");
  pintaDetalle(id);
}
mapEl.addEventListener("click", ev => { const t = ev.target.closest("rect.cell"); if (t) selecciona(t.dataset.id); });

document.querySelectorAll(".layers button").forEach(b => b.addEventListener("click", () => {
  capa = b.dataset.ly;
  document.querySelectorAll(".layers button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  drawMap();
}));

async function irAFecha(f) {
  const aviso = document.getElementById("aviso");
  aviso.hidden = true;
  document.body.style.cursor = "progress";
  try {
    RIESGO = await pedir(`/api/riesgo?fecha=${f}`);
    RIESGO.mapa = Object.fromEntries(RIESGO.celdas.map(c => [c.spatial_id, c]));
    fechaActual = f;
    document.getElementById("fecha-input").value = f;
    document.querySelectorAll(".scen button").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.f === f)));
    pintaStrip(); drawMap(); pintaResumen(); pintaPuntos(); pintaTabla();
    await pintaChart();
    await pintaDetalle(sel);
  } catch (e) {
    aviso.hidden = false;
    aviso.textContent = `No se pudo consultar la API: ${e.message}`;
  } finally {
    document.body.style.cursor = "";
  }
}

document.querySelectorAll(".scen button").forEach(b =>
  b.addEventListener("click", () => irAFecha(b.dataset.f)));
document.getElementById("fecha-input").addEventListener("change", ev => irAFecha(ev.target.value));

/* ---------------- arranque ---------------- */
(async function boot() {
  const aviso = document.getElementById("aviso");
  try {
    const salud = await pedir("/api/salud");
    document.getElementById("api-estado").textContent = salud.estado;
    document.getElementById("api-origen").textContent = (salud.procedencia?.sha256_origen || "").slice(0, 12) + "…";
    const [cel, pts, ficha] = await Promise.all([
      pedir("/api/celdas"), pedir("/api/puntos-criticos"), pedir("/api/modelo"),
    ]);
    CELDAS = cel.celdas; RIO = cel.rio; MALLA = cel.malla; PUNTOS = pts.puntos; FICHA = ficha;
    pintaModelo();
    sel = "PP0500_R0011_C0014";
    await irAFecha(fechaActual);
  } catch (e) {
    aviso.hidden = false;
    aviso.textContent = `No se pudo iniciar: ${e.message}. Verifique que la API esté en ejecución.`;
  }
})();

const mq = window.matchMedia("(prefers-color-scheme: dark)");
mq.addEventListener?.("change", () => { drawMap(); pintaChart(); });
new MutationObserver(() => { drawMap(); pintaChart(); })
  .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: python web/construir_web.py <plantilla.html>", file=sys.stderr)
        return 1
    tpl = Path(sys.argv[1]).read_text(encoding="utf-8")

    # 1) el <script> completo se sustituye por la capa de datos contra la API
    tpl = re.sub(r"<script>.*</script>", f"<script>{NUEVO_JS}</script>", tpl, flags=re.S)

    # 2) título y subtítulo
    tpl = tpl.replace("<title>Tablero VIGÍA Chillón</title>",
                      "<title>VIGÍA Chillón · TRL 4</title>")
    tpl = tpl.replace('<span class="tag">', '<span class="tag" style="border-color:var(--accent);color:var(--accent-ink);background:var(--accent-soft)">')
    tpl = re.sub(r'<svg width="11" height="11" viewBox="0 0 16 16"[^>]*>.*?</svg>\s*Prototipo ilustrativo',
                 "Prototipo TRL 4 · datos servidos por la API", tpl, flags=re.S)

    # 3) selector de escenarios -> fechas reales + campo libre
    botones = "".join(
        f'<button type="button" data-f="{p["f"]}" aria-pressed="{"true" if i == 0 else "false"}">'
        f'{p["nom"]}<small>{p["sub"]}</small></button>' for i, p in enumerate(
            [{"f": "2023-03-11", "nom": "Ciclón Yaku", "sub": "11 mar 2023"},
             {"f": "2017-03-16", "nom": "Niño Costero", "sub": "16 mar 2017"},
             {"f": "2015-08-03", "nom": "Día seco", "sub": "3 ago 2015"}]))
    nuevo_selector = (
        f'<div class="scen" role="group" aria-label="Fecha de consulta">{botones}</div>'
        '<label style="display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink-2)">'
        '<span style="font-family:var(--display);font-weight:600">o cualquier fecha</span>'
        '<input type="date" id="fecha-input" value="2023-03-11" min="2003-01-31" max="2026-07-31" '
        'style="font-family:var(--mono);font-size:12px;padding:6px 8px;border:1px solid var(--line);'
        'border-radius:6px;background:var(--surface);color:var(--ink)"></label>')
    tpl = re.sub(r'<div class="scen" role="group".*?</div>\s*</div>\s*</header>',
                 nuevo_selector + "</div></header>", tpl, flags=re.S)

    # 4) banner: de "maqueta" a "evidencia TRL 4", más el aviso de error de API
    tpl = re.sub(r'<div class="banner">.*?</div>\s*</div>',
                 '<div class="banner" style="background:var(--accent-soft);border-color:var(--accent)">'
                 '<div><b>Prototipo de acreditación TRL 4.</b> Esta página no contiene datos del distrito: '
                 'los pide a la API en cada consulta. El riesgo de la fecha seleccionada se calcula en el '
                 'servidor con la lluvia CHIRPS realmente observada ese día y los 22 predictores de cada celda. '
                 'Elija cualquier fecha entre 2003 y 2026 para comprobarlo. Los reportes ciudadanos y las '
                 'bitácoras de vigías siguen siendo simulados, porque el trabajo de campo aún no existe: '
                 'son el objeto del proyecto.</div></div>'
                 '<p id="aviso" hidden style="margin:12px 0 0;padding:11px 14px;border-radius:8px;'
                 'background:#fdecea;border:1px solid var(--r4);color:var(--r4);font-size:12.5px"></p>',
                 tpl, flags=re.S, count=1)

    # 5) cinta de estado: se añaden probabilidad del modelo y latencia
    tpl = re.sub(r'<div class="stat">\s*<div class="k">Lluvia acumulada 3 d</div>.*?<div class="k">Celdas en alto',
                 '<div class="stat"><div class="k">Lluvia acumulada 3 d</div>'
                 '<div class="v"><span id="s-p3">—</span> <span>mm</span></div>'
                 '<div class="n">CHIRPS cuenca · <span id="s-p7">—</span> mm en 7 d</div></div>'
                 '<div class="stat"><div class="k">Probabilidad del modelo</div>'
                 '<div class="v"><span id="s-prob">—</span></div>'
                 '<div class="n">PU distrital · clase <span id="s-clase">—</span></div></div>'
                 '<div class="stat"><div class="k">Cálculo en servidor</div>'
                 '<div class="v"><span id="s-ms">—</span> <span>ms</span></div>'
                 '<div class="n">API <span id="api-estado">—</span> · origen <span id="api-origen">—</span></div></div>'
                 '<div class="stat"><div class="k">Celdas en alto',
                 tpl, flags=re.S, count=1)

    # 6) el panel del bucle se sustituye por la ficha del modelo y el registro de llamadas
    tpl = re.sub(r'<section class="card" id="sec-loop".*?</section>',
                 '<section class="card" id="sec-loop" style="margin-top:16px">'
                 '<div class="head"><h2>Modelo y trazabilidad</h2>'
                 '<span class="hint">servido por <code>GET /api/modelo</code></span></div>'
                 '<div class="body"><div class="loop" id="modelo-info"></div>'
                 '<h3 style="font-size:12.5px;margin:16px 0 6px">Limitaciones declaradas</h3>'
                 '<ul id="modelo-limites" style="margin:0;padding-left:18px;font-size:12px;color:var(--ink-2)"></ul>'
                 '<h3 style="font-size:12.5px;margin:16px 0 6px">Últimas llamadas a la API</h3>'
                 '<div id="api-log" style="font-size:11.5px"></div>'
                 '<p style="font-size:11.5px;color:var(--ink-3);margin-top:12px">'
                 'Documentación interactiva del servicio en <a href="/docs" style="color:var(--accent-ink)">/docs</a>.</p>'
                 '</div></section>',
                 tpl, flags=re.S, count=1)

    # 7) estilos del registro de llamadas
    tpl = tpl.replace("</style>",
                      ".apirow{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:3px 0;"
                      "border-bottom:1px solid var(--line-soft);font-family:var(--mono)}\n"
                      ".apirow code{color:var(--ink-2)}.apirow .ok{color:var(--r1);font-weight:600}\n"
                      ".apirow .ms{color:var(--ink-3)}\n</style>")

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(tpl, encoding="utf-8")
    print(f"web/index.html escrito ({len(tpl)/1024:.0f} KB)")
    print("Comprobación: ¿quedan datos embebidos?",
          "NO" if "PP0500_R" not in tpl.split("<script>")[0] else "SÍ — revisar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
