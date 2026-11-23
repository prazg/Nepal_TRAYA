/**
 * Nepal TRĀYA (त्राय) — Multi-Hazard Risk Observatory Frontend Module
 *
 * Security & Engineering Guarantees:
 * - Zero inline scripts, zero inline styles, zero inline on*= event handlers.
 * - Strict HTML escaping (esc including &#39;) & URL scheme/host pinning (safeUrl).
 * - Single shared Leaflet L.canvas renderers (zero GPU/RAM canvas leak).
 * - Selection highlights via layer.setStyle() without destroying/rebuilding layers.
 * - Lazy on-demand JSON loaders with Promise deduplication.
 * - Honest NPT (UTC+05:45) freshness telemetry & live GloFAS + Dahal-Hasegawa recomputation.
 * - Unified 77-district + Geolocation ("Near Me") cross-hazard triage & EN/नेपाली i18n.
 */

import {
  initLang,
  getLang,
  setLang,
  t,
  tTier,
  tRiverStatus,
  tDhLevel,
  tDataClass,
  tSlaStatus,
  tHealthState,
  tEvidenceType,
  tLandslideType,
  tProvince,
  tDistrict,
  applyStaticTranslations,
} from './i18n.js';

/* ==========================================================================
   1. Security, Formatting, NPT Time & Math Utilities
   ========================================================================== */
const ESC_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ESC_MAP[c]);
}

export function safeUrl(u, allowedHosts = null) {
  if (!u || typeof u !== 'string') return '';
  try {
    const parsed = new URL(u.trim());
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return '';
    if (allowedHosts && allowedHosts.length) {
      const host = parsed.hostname.toLowerCase();
      const matched = allowedHosts.some(pattern => {
        const p = pattern.toLowerCase();
        if (p.startsWith('*.')) {
          const base = p.slice(2);
          return host === base || host.endsWith('.' + base);
        }
        return host === p;
      });
      if (!matched) return '';
    }
    return parsed.href;
  } catch {
    return '';
  }
}

const STAC_THUMB_HOSTS = [
  'sentinel-cogs.s3.us-west-2.amazonaws.com',
  'sentinel-cogs.s3.amazonaws.com',
  'earth-search.aws.element84.com',
];

export function safeFlyAttr(lat, lon, zoom = 11) {
  if (lat == null || lon == null || lat === '' || lon === '') return '';
  const la = Number(lat);
  const lo = Number(lon);
  const z = Number(zoom);
  if (!Number.isFinite(la) || !Number.isFinite(lo) || la < -90 || la > 90 || lo < -180 || lo > 180) {
    return '';
  }
  const zz = Number.isFinite(z) ? Math.max(1, Math.min(18, Math.round(z))) : 11;
  return `${la.toFixed(5)},${lo.toFixed(5)},${zz}`;
}

export function fmt(v, d = 0) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('en-GB', {
    maximumFractionDigits: d,
    minimumFractionDigits: d,
  });
}

const NPT_OFFSET_MS = (5 * 60 + 45) * 60 * 1000;

export function fmtNpt(isoOrMs, withTime = true) {
  if (isoOrMs == null || isoOrMs === '') return '—';
  const ms = typeof isoOrMs === 'number' ? isoOrMs : Date.parse(String(isoOrMs));
  if (!Number.isFinite(ms)) return '—';
  const d = new Date(ms + NPT_OFFSET_MS);
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  if (!withTime) return `${yyyy}-${mm}-${dd} NPT`;
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mi = String(d.getUTCMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi} NPT`;
}

export function ageHours(isoOrMs) {
  if (isoOrMs == null || isoOrMs === '') return Infinity;
  const ms = typeof isoOrMs === 'number' ? isoOrMs : Date.parse(String(isoOrMs));
  if (!Number.isFinite(ms)) return Infinity;
  return Math.max(0, (Date.now() - ms) / 3600000);
}

export function fmtAge(isoOrMs) {
  const hrs = ageHours(isoOrMs);
  if (!Number.isFinite(hrs)) return '';
  const isNe = getLang() === 'ne';
  if (hrs < 1) {
    const mins = Math.max(1, Math.round(hrs * 60));
    return isNe ? `${mins} मि. अघि` : `${mins}m ago`;
  }
  if (hrs < 48) {
    const h = Math.round(hrs);
    return isNe ? `${h} घण्टा अघि` : `${h}h ago`;
  }
  const days = Math.floor(hrs / 24);
  return isNe ? `${days} दिन अघि` : `${days}d ago`;
}

function hav(lo1, la1, lo2, la2) {
  const R = 6371.0088;
  const rad = Math.PI / 180;
  const a = Math.sin((la2 - la1) * rad / 2) ** 2
    + Math.cos(la1 * rad) * Math.cos(la2 * rad) * Math.sin((lo2 - lo1) * rad / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
}

function debounce(fn, waitMs) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), waitMs);
  };
}

function combinedSignal(controller, timeoutMs = 15000) {
  const signals = [];
  if (controller) signals.push(controller.signal);
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    signals.push(AbortSignal.timeout(timeoutMs));
  }
  if (signals.length === 2 && typeof AbortSignal.any === 'function') {
    return AbortSignal.any(signals);
  }
  return signals[0];
}

function csvCell(v) {
  if (v == null) return '';
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function triggerBlobDownload(blob, filename) {
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
}

function hydrateBars(root) {
  if (!root) return;
  root.querySelectorAll('[data-w]').forEach(el => {
    el.style.width = el.dataset.w;
  });
  root.querySelectorAll('[data-h]').forEach(el => {
    el.style.height = el.dataset.h;
  });
}

function bindImageFallbacks(root) {
  if (!root) return;
  root.querySelectorAll('img.sat-thumb').forEach(img => {
    img.addEventListener('error', () => img.classList.add('is-hidden'));
  });
}

/* ==========================================================================
   2. Scientific Classification Helpers (matching src/floods.py & hydromet.py)
   ========================================================================== */
export function classifyRiverStatus(val, clim) {
  if (val == null || !clim) return 'normal';
  const v = Number(val);
  if (!Number.isFinite(v) || v <= 0) return 'normal';
  if (clim.q20 > 0 && v >= clim.q20) return 'q20_severe';
  if (clim.q5 > 0 && v >= clim.q5) return 'q5_warning';
  if (clim.q2 > 0 && v >= clim.q2) return 'q2_watch';
  if (clim.q90 > 0 && v >= clim.q90) return 'elevated';
  return 'normal';
}

function isRiverAlertStatus(st) {
  return ['q2_watch', 'q5_warning', 'q20_severe', 'watch', 'warning', 'severe'].includes(st);
}

const RIVER_SEV = {
  unassessed: -1,
  normal: 0,
  elevated: 1,
  watch: 2,
  q2_watch: 2,
  warning: 3,
  q5_warning: 3,
  severe: 4,
  q20_severe: 4,
};

function riverHeadlineStatus(b) {
  if (!b) return 'unassessed';
  const sNow = b.status_now || 'normal';
  const s14 = b.status_14d || 'normal';
  if (sNow === 'unassessed' && s14 === 'unassessed') return 'unassessed';
  if (sNow === 'unassessed') return s14;
  if (s14 === 'unassessed') return sNow;
  return (RIVER_SEV[s14] ?? 0) >= (RIVER_SEV[sNow] ?? 0) ? s14 : sNow;
}

function rollingMaxSum(values, windowLen) {
  if (!values || !values.length) return 0;
  const w = Math.min(windowLen, values.length);
  let cur = 0;
  for (let i = 0; i < w; i++) cur += Math.max(0, Number(values[i]) || 0);
  let best = cur;
  for (let i = w; i < values.length; i++) {
    cur += Math.max(0, Number(values[i]) || 0) - Math.max(0, Number(values[i - w]) || 0);
    if (cur > best) best = cur;
  }
  return Math.round(best * 10) / 10;
}

export function evaluateDahalHasegawa(rain24, rain72, rain168) {
  const ec24 = 144.0;
  const ec72 = 181.4;
  const ec168 = 216.8;
  const r24 = Math.max(0, Number(rain24) || 0) / ec24;
  const r72 = Math.max(0, Number(rain72) || 0) / ec72;
  const r168 = Math.max(0, Number(rain168) || 0) / ec168;
  const mr = Math.max(r24, r72, r168);
  const level = mr >= 1.0 ? 'exceeded' : mr >= 0.7 ? 'watch' : mr >= 0.4 ? 'elevated' : 'low';
  return {
    ec_24h_mm: ec24,
    ec_72h_mm: ec72,
    ec_168h_mm: ec168,
    ratio_24h: Math.round(r24 * 1000) / 1000,
    ratio_72h: Math.round(r72 * 1000) / 1000,
    ratio_168h: Math.round(r168 * 1000) / 1000,
    max_ratio: Math.round(mr * 1000) / 1000,
    level,
  };
}

/* ==========================================================================
   3. Application State & Lazy Data Cache
   ========================================================================== */
const S = {
  summary: null,
  districtsMeta: null,
  districts: [],
  lakes: [],
  lakeById: new Map(),
  routes: null,
  expo: null,
  expoById: {},
  eqHist: null,
  glofHist: null,
  faults: null,
  faultsMeta: null,
  rivers: [],
  riversMeta: null,
  landslides: null,
  lsMeta: null,
  hydromet: null,
  hmLakeById: {},
  gdacs: null,
  gdacsMeta: null,
  valid: null,
  sens: null,
  manifest: null,
  kpiBaseline: null,
  bipad: null,
  lsReviewQueue: null,
  exposureIso: null,
  cascades: null,
  eoSar: null,
  tshoRolpaPilot: null,

  sel: null,
  selKind: null,
  selDistrict: null,
  userCoords: null,
  live: [],
  liveFetchedAt: null,
  liveStatus: 'loading',
  mmi: null,
  gf: null,
  eqWindow: 'week',

  colourBy: 'hazard',
  filters: {
    priority: false,
    routed: false,
    ava: false,
    sla: false,
    ice: false,
    contact: false,
    past: false,
    prov: '',
    area: 0,
    q: '',
  },
  shown: [],
  tab: 'watch',
  sort: { k: 'pfv_Mm3', dir: -1 },
  lsTypeFilter: 'all',
  isoView: 'lakes',
  cascadeSel: { kind: 'edge', id: 'GII-01' },
  stacCache: {},
};

const LAZY_PATHS = {
  routes: 'data/routes.json',
  exposure: 'data/exposure.json',
  landslides: 'data/landslides.json',
  landslide_review_queue: 'data/landslide_review_queue.json',
  faults: 'data/faults.json',
  eq_history_m6: 'data/eq_history_m6.json',
  glof_history: 'data/glof_history.json',
  gdacs_alerts: 'data/gdacs_alerts.json',
  validation: 'data/validation.json',
  sensitivity: 'data/sensitivity.json',
  manifest: 'data/manifest.json',
  kpi_baseline: 'data/kpi_baseline.json',
  bipad_official: 'data/bipad_official.json',
  exposure_isolation: 'data/exposure_isolation.json',
  cascades: 'data/cascades.json',
  eo_sar: 'data/eo_sar.json',
  tsho_rolpa_pilot: 'data/tsho_rolpa_pilot.json',
};

const REPO_DOC_BASE = 'https://github.com/prazg/Nepal_TRAYA/blob/main';
const DATA_LICENSES_URL = `${REPO_DOC_BASE}/DATA_LICENSES.md`;
const TSHO_ROLPA_PLAN_URL = `${REPO_DOC_BASE}/docs/TSHO_ROLPA_2D_STUDY_PLAN.md`;
const MODEL_CARDS_URL = `${REPO_DOC_BASE}/docs/MODEL_CARDS.md`;
const INST_SPEC_URL = `${REPO_DOC_BASE}/docs/INSTITUTIONAL_INTEGRATION_SPEC.md`;

const lazyPromises = new Map();

export function unpackLakesCore(payload) {
  if (!payload) return [];
  if (payload.type === 'FeatureCollection' && Array.isArray(payload.features)) {
    return payload.features;
  }
  if (payload.format !== 'traya_lakes_v2' || !Array.isArray(payload.cols) || !Array.isArray(payload.rows)) {
    return [];
  }
  const cols = payload.cols;
  const dicts = payload.dicts || {};
  const boolSet = new Set(payload.bool_cols || []);
  const scale = Number(payload.coord_scale) || 10000;
  const geoms = payload.geoms || [];

  return payload.rows.map((row, idx) => {
    const props = {};
    for (let j = 0; j < row.length && j < cols.length; j++) {
      const v = row[j];
      if (v === null || v === undefined) continue;
      const k = cols[j];
      if (Object.prototype.hasOwnProperty.call(dicts, k)) {
        props[k] = dicts[k][v];
      } else if (boolSet.has(k)) {
        props[k] = Boolean(v);
      } else {
        props[k] = v;
      }
    }
    const rawG = geoms[idx];
    let geometry;
    if (Array.isArray(rawG)) {
      const ring = [];
      let ix = 0;
      let iy = 0;
      for (let k = 0; k + 1 < rawG.length; k += 2) {
        ix += rawG[k];
        iy += rawG[k + 1];
        ring.push([ix / scale, iy / scale]);
      }
      if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
        ring.push([ring[0][0], ring[0][1]]);
      }
      geometry = { type: 'Polygon', coordinates: [ring] };
    } else {
      geometry = rawG || { type: 'Point', coordinates: [props.lon || 0, props.lat || 0] };
    }
    return { type: 'Feature', geometry, properties: props };
  });
}

async function fetchJson(path, timeoutMs = 20000) {
  const signal = combinedSignal(null, timeoutMs);
  const resp = await fetch(path, { signal });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${path}`);
  return resp.json();
}

async function ensureData(key) {
  if (key === 'routes' && S.routes) return S.routes;
  if (key === 'exposure' && S.expo) return S.expo;
  if (key === 'landslides' && S.landslides) return S.landslides;
  if (key === 'landslide_review_queue' && S.lsReviewQueue) return S.lsReviewQueue;
  if (key === 'faults' && S.faults) return S.faults;
  if (key === 'eq_history_m6' && S.eqHist) return S.eqHist;
  if (key === 'glof_history' && S.glofHist) return S.glofHist;
  if (key === 'gdacs_alerts' && S.gdacs) return S.gdacs;
  if (key === 'validation' && S.valid) return S.valid;
  if (key === 'sensitivity' && S.sens) return S.sens;
  if (key === 'manifest' && S.manifest) return S.manifest;
  if (key === 'kpi_baseline' && S.kpiBaseline) return S.kpiBaseline;
  if (key === 'bipad_official' && S.bipad) return S.bipad;
  if (key === 'exposure_isolation' && S.exposureIso) return S.exposureIso;
  if (key === 'cascades' && S.cascades) return S.cascades;
  if (key === 'eo_sar' && S.eoSar) return S.eoSar;
  if (key === 'tsho_rolpa_pilot' && S.tshoRolpaPilot) return S.tshoRolpaPilot;

  if (lazyPromises.has(key)) return lazyPromises.get(key);
  const path = LAZY_PATHS[key];
  if (!path) return null;

  const p = fetchJson(path)
    .then(data => {
      if (key === 'routes') {
        S.routes = data || {};
      } else if (key === 'exposure') {
        S.expo = Array.isArray(data) ? data : [];
        S.expoById = {};
        S.expo.forEach(o => { S.expoById[o.i] = o; });
      } else if (key === 'landslides') {
        S.lsMeta = data || {};
        S.landslides = (data && data.events) || [];
      } else if (key === 'landslide_review_queue') {
        S.lsReviewQueue = data || null;
      } else if (key === 'faults') {
        S.faultsMeta = data || {};
        S.faults = (data && data.features) || [];
      } else if (key === 'eq_history_m6') {
        S.eqHist = Array.isArray(data) ? data : [];
      } else if (key === 'glof_history') {
        S.glofHist = Array.isArray(data) ? data : [];
      } else if (key === 'gdacs_alerts') {
        S.gdacsMeta = data || {};
        S.gdacs = (data && data.events) || [];
      } else if (key === 'validation') {
        S.valid = data || null;
      } else if (key === 'sensitivity') {
        S.sens = data || null;
      } else if (key === 'manifest') {
        S.manifest = data || null;
      } else if (key === 'kpi_baseline') {
        S.kpiBaseline = data || null;
      } else if (key === 'bipad_official') {
        S.bipad = data || null;
      } else if (key === 'exposure_isolation') {
        S.exposureIso = data || null;
      } else if (key === 'cascades') {
        S.cascades = data || null;
      } else if (key === 'eo_sar') {
        S.eoSar = data || null;
      } else if (key === 'tsho_rolpa_pilot') {
        S.tshoRolpaPilot = data || null;
      }
      return data;
    })
    .catch(err => {
      lazyPromises.delete(key);
      throw err;
    });

  lazyPromises.set(key, p);
  return p;
}

/* ==========================================================================
   4. Visual Palettes, Badge Classes & CVD-Safe SVG Map Icons
   ========================================================================== */
const HCLASS = {
  'very high': 'h-vhigh',
  high: 'h-high',
  moderate: 'h-mod',
  low: 'h-low',
};
const HCOL = {
  'very high': '#b91c1c',
  high: '#c2410c',
  moderate: '#eab308',
  low: '#0f766e',
};
const HCODE = {
  'very high': 'VH',
  high: 'H',
  moderate: 'M',
  low: 'L',
};
const HORD = { 'very high': 3, high: 2, moderate: 1, low: 0 };

const FCOL = {
  q20_severe: '#b91c1c',
  severe: '#b91c1c',
  q5_warning: '#c2410c',
  warning: '#c2410c',
  q2_watch: '#eab308',
  watch: '#eab308',
  elevated: '#0284c7',
  normal: '#0f766e',
  unassessed: '#475569',
};
const FCLASS = {
  q20_severe: 'h-vhigh',
  severe: 'h-vhigh',
  q5_warning: 'h-high',
  warning: 'h-high',
  q2_watch: 'h-mod',
  watch: 'h-mod',
  elevated: 'h-info',
  normal: 'h-low',
  unassessed: 'h-na',
};
const FCODE = {
  q20_severe: '20',
  severe: '20',
  q5_warning: 'Q5',
  warning: 'Q5',
  q2_watch: 'Q2',
  watch: 'Q2',
  elevated: 'E',
  normal: 'N',
  unassessed: '?',
};

const DHCOL = {
  exceeded: '#b91c1c',
  watch: '#c2410c',
  elevated: '#eab308',
  low: '#0f766e',
};
const DHCLASS = {
  exceeded: 'h-vhigh',
  watch: 'h-high',
  elevated: 'h-mod',
  low: 'h-low',
};

const DC_CLASS = {
  live_observation: 'dc-live',
  forecast: 'dc-forecast',
  historical: 'dc-hist',
  static_assessment: 'dc-static',
  cached: 'dc-cached',
  unavailable: 'dc-unavail',
};

const SLA_CLASS = {
  available: 'sla-available',
  stale: 'sla-stale',
  unavailable: 'sla-unavailable',
};

const LS_TYPE_ORDER = [
  'landslide_event',
  'landslide_scar',
  'susceptibility_zone',
  'hazard_report',
  'coseismic_failure',
];

function badgeDataClass(dc) {
  const k = String(dc || 'unavailable').toLowerCase();
  return `<span class="dc-badge ${DC_CLASS[k] || 'dc-unavail'}">${esc(tDataClass(k))}</span>`;
}

function badgeSla(st) {
  const k = String(st || 'unavailable').toLowerCase();
  return `<span class="sla-badge ${SLA_CLASS[k] || 'sla-unavailable'}">${esc(tSlaStatus(k))}</span>`;
}

function badgeEvidence(ev) {
  const k = String(ev || 'modelled_static').toLowerCase();
  const cls = k === 'observed' ? 'dc-live' : k === 'forecast' ? 'dc-forecast' : 'dc-static';
  return `<span class="dc-badge ${cls}">${esc(tEvidenceType(k))}</span>`;
}

function badgeLsType(ft) {
  const k = String(ft || 'landslide_scar').toLowerCase();
  const cls = k === 'landslide_event'
    ? 'dc-live'
    : k === 'coseismic_failure'
      ? 'dc-unavail'
      : k === 'hazard_report'
        ? 'dc-forecast'
        : k === 'susceptibility_zone'
          ? 'dc-static'
          : 'dc-cached';
  return `<span class="dc-badge ${cls}">${esc(tLandslideType(k))}</span>`;
}

function fmtNullCount(v) {
  if (v === null || v === undefined || v === '') {
    return `<span class="val-unknown">${esc(t('unknownVal'))}</span>`;
  }
  return fmt(v);
}

function fmtNullDate(isoOrDate) {
  if (!isoOrDate) {
    return `<span class="val-unknown">${esc(t('unknownVal'))}</span>`;
  }
  const s = String(isoOrDate);
  return s.length > 10 ? esc(fmtNpt(s, false)) : esc(s);
}

const SEQ = ['#1e4b66', '#1d6f8f', '#0284c7', '#eab308', '#c2410c', '#b91c1c'];
const SCALES = {
  qp_m3s: { stops: [0, 250, 1000, 3000, 8000, 20000], unit: 'm³/s', label: 'Peak discharge (pooled median)' },
  pfv_Mm3: { stops: [0, 1, 5, 10, 25, 50], unit: 'Mm³', label: 'Potential flood volume (Fujita et al. 2013)' },
  pop_high: { stops: [0, 1000, 10000, 50000, 200000, 500000], unit: 'people', label: 'People within 1 km of routed channel' },
  fault_km: { stops: [0, 5, 15, 30, 60, 100], unit: 'km', label: 'Distance to nearest mapped active fault (GEM)', invert: true },
  area_change_pct: { stops: [-20, 0, 10, 25, 50, 100], unit: '%', label: 'Observed lake area change' },
};

function scaleColour(v, stops, cols, invert = false) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '#475569';
  const arr = invert ? cols.slice().reverse() : cols;
  for (let i = stops.length - 1; i >= 0; i--) {
    if (v >= stops[i]) return arr[i];
  }
  return arr[0];
}

function lakeColour(p) {
  const by = S.colourBy;
  if (by === 'hazard') return HCOL[p.hazard] || '#475569';
  if (by === 'hazard_enum') return HCOL[p.hazard_enum] || '#475569';
  if (by === 'risk') return HCOL[p.risk] || '#475569';
  if (by === 'priority') return p.priority ? '#b91c1c' : '#475569';
  const sc = SCALES[by];
  return sc ? scaleColour(p[by], sc.stops, SEQ, Boolean(sc.invert)) : '#475569';
}

/* CVD-Safe SVG DivIcon Builders */
function makePriorityLakeIcon(fillCol, selected) {
  const sz = selected ? 22 : 16;
  const stroke = selected ? '#ffffff' : '#facc15';
  const sw = selected ? 2.4 : 1.7;
  const c = sz / 2;
  const r = selected ? 8 : 5.5;
  const pts = `${c},${c - r} ${c + r},${c} ${c},${c + r} ${c - r},${c}`;
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [sz, sz],
    iconAnchor: [c, c],
    html: `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" aria-hidden="true"><polygon points="${pts}" fill="${fillCol}" stroke="${stroke}" stroke-width="${sw}"/></svg>`,
  });
}

function makeRiverIcon(st, snapWarn) {
  const col = FCOL[st] || '#0f766e';
  const code = FCODE[st] || 'N';
  const textCol = (st === 'q2_watch' || st === 'watch') ? '#0a0f16' : '#ffffff';
  const warnDot = snapWarn ? '<circle cx="19" cy="3" r="3" fill="#facc15" stroke="#0a0f16" stroke-width="1"/>' : '';
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><rect x="2" y="2" width="18" height="18" rx="4" fill="${col}" stroke="#ffffff" stroke-width="1.6"/><text x="11" y="14.5" text-anchor="middle" fill="${textCol}" font-size="8.5" font-weight="700" font-family="monospace">${code}</text>${warnDot}</svg>`,
  });
}

function makeNodeIcon(lv) {
  const col = DHCOL[lv] || '#0f766e';
  const stroke = lv === 'elevated' ? '#0a0f16' : '#ffffff';
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [18, 18],
    iconAnchor: [9, 10],
    html: `<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><polygon points="9,2 16.5,15.5 1.5,15.5" fill="${col}" stroke="${stroke}" stroke-width="1.4"/></svg>`,
  });
}

function makeGlofIcon() {
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    html: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><polygon points="2,3 14,3 8,14" fill="#14b8a6" stroke="#0a0f16" stroke-width="1.3"/></svg>',
  });
}

function makeGdacsIcon(level, evType) {
  const col = level === 'Red' ? '#b91c1c' : level === 'Orange' ? '#c2410c' : '#15803d';
  const code = esc(String(evType || 'AL').slice(0, 2).toUpperCase());
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><polygon points="11,1 20,6 20,16 11,21 2,16 2,6" fill="${col}" stroke="#ffffff" stroke-width="1.4"/><text x="11" y="14" text-anchor="middle" fill="#ffffff" font-size="7.5" font-weight="700" font-family="monospace">${code}</text></svg>`,
  });
}

function magColour(m) {
  return m >= 6 ? '#b91c1c' : m >= 5 ? '#c2410c' : m >= 4 ? '#eab308' : '#0f766e';
}

function makeQuakeIcon(mag) {
  const r = Math.max(6, Math.min(18, Math.round(3.2 * Math.max(1, mag))));
  const sz = r * 2 + 4;
  const c = sz / 2;
  const col = magColour(mag);
  const textCol = (mag >= 4 && mag < 5) ? '#0a0f16' : '#ffffff';
  const lbl = mag >= 4.0
    ? `<text x="${c}" y="${c + 3}" text-anchor="middle" fill="${textCol}" font-size="8.5" font-weight="700" font-family="monospace">${fmt(mag, 1)}</text>`
    : `<circle cx="${c}" cy="${c}" r="2" fill="#ffffff"/>`;
  return L.divIcon({
    className: 'traya-divicon',
    iconSize: [sz, sz],
    iconAnchor: [c, c],
    html: `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" aria-hidden="true"><circle cx="${c}" cy="${c}" r="${r}" fill="${col}" fill-opacity="0.88" stroke="#ffffff" stroke-width="1.5"/>${lbl}</svg>`,
  });
}

/* ==========================================================================
   5. Theme & Map Initialization (Shared Canvas Renderers — Zero Leak)
   ========================================================================== */
function initTheme() {
  try {
    const saved = localStorage.getItem('traya.theme');
    if (saved === 'light' || saved === 'dark') {
      document.documentElement.setAttribute('data-theme', saved);
    }
  } catch {
    // ignore storage errors
  }
}

initTheme();
initLang();

const map = L.map('map', {
  preferCanvas: true,
  zoomControl: true,
  worldCopyJump: false,
}).setView([28.3, 84.2], 7);

L.control.scale({ imperial: false, position: 'bottomright' }).addTo(map);
map.attributionControl.setPrefix('');

// Shared Leaflet canvas renderers — allocated ONCE for the lifetime of the app
const lakeRenderer = L.canvas({ padding: 0.4 });
const overlayRenderer = L.canvas({ padding: 0.4 });

map.on('mousemove', e => {
  const el = document.getElementById('coordPill');
  if (el) el.textContent = `${e.latlng.lat.toFixed(3)}°N, ${e.latlng.lng.toFixed(3)}°E`;
});

const DATA_CREDIT = 'TRĀYA | Copernicus DEM GLO-30 | Nepal Cryosphere Inventory | GloFAS | GEM | USGS';
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';

const BASEMAPS = {
  'Dark grey': L.tileLayer(`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 17,
    maxNativeZoom: 16,
    attribution: `Esri, HERE, Garmin, &copy; OpenStreetMap | ${DATA_CREDIT}`,
  }),
  'Sentinel-2 cloudless (10 m)': L.tileLayer(
    'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg',
    {
      maxZoom: 17,
      maxNativeZoom: 14,
      attribution: `<a href="https://s2maps.eu" target="_blank" rel="noopener noreferrer">Sentinel-2 cloudless</a> by EOX (CC-BY 4.0) | ${DATA_CREDIT}`,
    }
  ),
  'Satellite imagery': L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 17,
    maxNativeZoom: 17,
    attribution: `Esri, Maxar, Earthstar Geographics | ${DATA_CREDIT}`,
  }),
  'Terrain (hillshade)': L.tileLayer(`${ESRI}/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 17,
    maxNativeZoom: 15,
    attribution: `Esri, Airbus DS, USGS, NGA, NASA, CGIAR | ${DATA_CREDIT}`,
  }),
  OpenTopoMap: L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    maxNativeZoom: 16,
    subdomains: 'abc',
    attribution: `&copy; OpenStreetMap, SRTM | <a href="https://opentopomap.org" target="_blank" rel="noopener noreferrer">OpenTopoMap</a> (CC-BY-SA) | ${DATA_CREDIT}`,
  }),
  OpenStreetMap: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    maxNativeZoom: 17,
    attribution: `&copy; OpenStreetMap contributors | ${DATA_CREDIT}`,
  }),
  'No basemap': L.layerGroup([]),
};

let baseName = 'Dark grey';
try {
  const savedBase = localStorage.getItem('traya.basemap') || localStorage.getItem('ews.basemap');
  if (savedBase && BASEMAPS[savedBase]) baseName = savedBase;
} catch {
  // ignore
}
BASEMAPS[baseName].addTo(map);
L.control.layers(BASEMAPS, null, { position: 'topright', collapsed: true }).addTo(map);

let basemapOk = true;
let tileErrors = 0;

function setBasemapPill(msg) {
  const el = document.getElementById('pill-base');
  if (!el) return;
  if (!msg) {
    el.className = 'pill';
    el.innerHTML = `<span class="dot"></span>${esc(baseName.toLowerCase())}`;
  } else {
    el.className = 'pill err';
    el.innerHTML = `<span class="dot"></span>${esc(msg)}`;
  }
}

map.on('baselayerchange', e => {
  baseName = e.name;
  try { localStorage.setItem('traya.basemap', e.name); } catch { /* ignore */ }
  basemapOk = true;
  tileErrors = 0;
  setBasemapPill(null);
});

Object.values(BASEMAPS).forEach(l => {
  if (!l.on) return;
  l.on('tileload', () => { tileErrors = 0; });
  l.on('tileerror', () => {
    if (!basemapOk || ++tileErrors < 8) return;
    basemapOk = false;
    setBasemapPill('tiles offline — switch basemap');
  });
});

/* Map Layer Groups */
const gSat = L.layerGroup().addTo(map);
const gDistrict = L.layerGroup().addTo(map);
const gFaults = L.layerGroup();
const gLakes = L.layerGroup().addTo(map);
const gRoute = L.layerGroup().addTo(map);
const gExp = L.layerGroup().addTo(map);
const gRivers = L.layerGroup().addTo(map);
const gNodes = L.layerGroup();
const gLs = L.layerGroup();
const gHydro = L.layerGroup();
const gEqH = L.layerGroup();
const gGlof = L.layerGroup();
const gMmi = L.layerGroup().addTo(map);
const gEq = L.layerGroup().addTo(map);
const gGdacs = L.layerGroup();

const lakeLayerById = new Map();
const prioMarkerById = new Map();

/* ==========================================================================
   6. NASA GIBS Satellite Overlay
   ========================================================================== */
const GIBS_PRODUCTS = {
  imerg: { id: 'IMERG_Precipitation_Rate', matrix: 'GoogleMapsCompatible_Level6', ext: 'png', maxNative: 6, label: 'GPM IMERG Precip' },
  snow: { id: 'MODIS_Terra_NDSI_Snow_Cover', matrix: 'GoogleMapsCompatible_Level8', ext: 'png', maxNative: 8, label: 'MODIS NDSI Snow' },
  viirs: { id: 'VIIRS_SNPP_CorrectedReflectance_TrueColor', matrix: 'GoogleMapsCompatible_Level9', ext: 'jpg', maxNative: 9, label: 'VIIRS True Colour' },
};

function defaultGibsDate() {
  return new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
}

const satDateInput = document.getElementById('satDate');
if (satDateInput) satDateInput.value = defaultGibsDate();

let activeGibsTile = null;

function updateSatOverlay() {
  gSat.clearLayers();
  activeGibsTile = null;
  const key = document.getElementById('satLayer').value;
  const bar = document.getElementById('satBar');
  const op = Number(document.getElementById('satOp').value) / 100;
  document.getElementById('satOpLbl').textContent = `${Math.round(op * 100)}%`;
  if (key === 'none' || !GIBS_PRODUCTS[key]) {
    bar.classList.remove('on');
    return;
  }
  const prod = GIBS_PRODUCTS[key];
  const dtStr = document.getElementById('satDate').value || defaultGibsDate();
  const base = safeUrl(
    (S.summary && S.summary.live_feeds && S.summary.live_feeds.nasa_gibs_wmts)
      || 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best',
    ['gibs.earthdata.nasa.gov']
  ) || 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
  activeGibsTile = L.tileLayer(`${base}/${prod.id}/default/${dtStr}/${prod.matrix}/{z}/{y}/{x}.${prod.ext}`, {
    maxZoom: 17,
    maxNativeZoom: prod.maxNative,
    opacity: op,
    attribution: 'NASA EOSDIS GIBS',
  }).addTo(gSat);
  bar.classList.add('on');
  document.getElementById('satBarName').textContent = prod.label;
  document.getElementById('satBarDate').textContent = dtStr;
}

function shiftSatDate(days) {
  const inp = document.getElementById('satDate');
  const cur = new Date((inp.value || defaultGibsDate()) + 'T00:00:00Z');
  cur.setUTCDate(cur.getUTCDate() + days);
  inp.value = cur.toISOString().slice(0, 10);
  updateSatOverlay();
}

/* ==========================================================================
   7. Legend, Filters & Zero-Leak Lake Rendering
   ========================================================================== */
function drawLegend() {
  const by = S.colourBy;
  const el = document.getElementById('legend');
  if (!el) return;

  if (by === 'hazard' || by === 'hazard_enum' || by === 'risk') {
    const tiers = [
      ['very high', 'sw-vhigh', 'VH'],
      ['high', 'sw-high', 'H'],
      ['moderate', 'sw-mod', 'M'],
      ['low', 'sw-low', 'L'],
    ];
    el.innerHTML = tiers
      .map(([k, cls, code]) => `<div class="legend-item"><span class="legend-swatch ${cls}" aria-hidden="true">${code}</span><span>${esc(tTier(k))}</span></div>`)
      .join('')
      + `<div class="legend-item"><span class="legend-swatch sw-na" aria-hidden="true">—</span><span>${esc(tTier('not assessed'))}</span></div>`
      + (by === 'hazard_enum'
        ? '<p class="muted">Alternative literal enumeration of Rounce et al. (2016) Sect. 4.2 — 977 of 1,429 lakes shift class.</p>'
        : '')
      + (by === 'risk'
        ? '<p class="muted">Risk combines hazard × downstream impact on lakes with a routed flood path.</p>'
        : '');
  } else if (by === 'priority') {
    el.innerHTML = '<div class="legend-item"><span class="legend-swatch sw-vhigh" aria-hidden="true">◆</span><span>PFV ≥ 10 Mm³ — priority set (16)</span></div>'
      + '<div class="legend-item"><span class="legend-swatch sw-na" aria-hidden="true">•</span><span>Below 10 Mm³ threshold</span></div>'
      + '<p class="muted">Fujita et al. (2013) screening threshold comparable to recorded major Himalayan GLOFs.</p>';
  } else {
    const sc = SCALES[by];
    const stops = sc.stops.map((s, i) => {
      const idx = sc.invert ? (sc.stops.length - 1 - i) : i;
      return `<div class="legend-item"><span class="legend-swatch sw-seq-${idx}" aria-hidden="true"></span><span>≥ ${fmt(s)} ${esc(sc.unit)}</span></div>`;
    }).reverse().join('');
    el.innerHTML = `<div class="muted">${esc(sc.label)}</div>${stops}`
      + `<div class="legend-item"><span class="legend-swatch sw-na" aria-hidden="true">—</span><span>${esc(tTier('not assessed'))}</span></div>`;
  }
}

function populateProvinceAndDistrictDropdowns() {
  const provSel = document.getElementById('fProv');
  const currentProv = provSel.value;
  provSel.innerHTML = `<option value="">${esc(t('fAllProvs'))}</option>`;
  const provinces = (S.districtsMeta && S.districtsMeta.provinces) || [];
  provinces.forEach(pr => {
    const opt = document.createElement('option');
    opt.value = pr.name;
    opt.textContent = getLang() === 'ne' ? `${pr.name_ne} (${pr.name.replace(' Province', '')})` : pr.name;
    provSel.appendChild(opt);
  });
  provSel.value = currentProv;

  populateDistrictSelect(document.getElementById('districtSearch').value);
}

function populateDistrictSelect(query = '') {
  const sel = document.getElementById('fDistrict');
  const prev = S.selDistrict || sel.value;
  const q = String(query || '').trim().toLowerCase();
  sel.innerHTML = `<option value="">${esc(t('triageAllDistricts'))}</option>`;

  const provinces = (S.districtsMeta && S.districtsMeta.provinces) || [];
  const byProv = new Map();
  provinces.forEach(p => byProv.set(p.name, []));

  S.districts.forEach(d => {
    if (q) {
      const hay = `${d.name} ${d.name_ne || ''} ${d.prov || ''} ${d.prov_ne || ''}`.toLowerCase();
      if (!hay.includes(q)) return;
    }
    if (!byProv.has(d.prov)) byProv.set(d.prov, []);
    byProv.get(d.prov).push(d);
  });

  provinces.forEach(p => {
    const list = byProv.get(p.name) || [];
    if (!list.length) return;
    const og = document.createElement('optgroup');
    og.label = getLang() === 'ne' ? `${p.name_ne} (${p.name})` : `${p.name} · ${p.name_ne || ''}`;
    list.sort((a, b) => a.name.localeCompare(b.name)).forEach(d => {
      const opt = document.createElement('option');
      opt.value = d.name;
      opt.textContent = getLang() === 'ne'
        ? `${d.name_ne || d.name} (${d.name})`
        : `${d.name} — ${d.name_ne || ''}`;
      og.appendChild(opt);
    });
    sel.appendChild(og);
  });

  if (prev && S.districts.some(d => d.name === prev)) {
    sel.value = prev;
  }
}

function passes(p) {
  const f = S.filters;
  if (f.priority && !p.priority) return false;
  if (f.routed && !(p.route_km > 0)) return false;
  if (f.ava && !p.avalanche) return false;
  if (f.sla && !(p.sla_area_km2 > 0)) return false;
  if (f.ice && !p.ice_cored) return false;
  if (f.contact && !p.ice_contact) return false;
  if (f.past && !p.past_glof) return false;
  if (f.prov && p.prov !== f.prov) return false;
  if (p.area_km2 < f.area) return false;
  if (f.q) {
    const hay = `${p.id} ${p.name || ''} ${p.prov || ''} ${p.district || ''} ${p.typ || ''} ${p.rgi || ''} ${p.fault_name || ''}`.toLowerCase();
    if (!hay.includes(f.q)) return false;
  }
  return true;
}

function readFilters() {
  const areaMax = 0.5;
  const v = Number(document.getElementById('fArea').value);
  const area = areaMax * Math.pow(v / 100, 2);
  document.getElementById('areaLbl').textContent = area.toFixed(3);
  S.filters = {
    priority: document.getElementById('fPriority').checked,
    routed: document.getElementById('fOnlyRouted').checked,
    ava: document.getElementById('fAva').checked,
    sla: document.getElementById('fSla').checked,
    ice: document.getElementById('fIce').checked,
    contact: document.getElementById('fContact').checked,
    past: document.getElementById('fPast').checked,
    prov: document.getElementById('fProv').value,
    area,
    q: document.getElementById('fSearch').value.trim().toLowerCase(),
  };
}

function resetFilters() {
  ['fPriority', 'fOnlyRouted', 'fAva', 'fSla', 'fIce', 'fContact', 'fPast'].forEach(id => {
    document.getElementById(id).checked = false;
  });
  document.getElementById('fProv').value = '';
  document.getElementById('fArea').value = 0;
  document.getElementById('fSearch').value = '';
  refresh();
}

function lakeStyle(p, isSelected) {
  return {
    color: isSelected ? '#ffffff' : '#090d12',
    weight: isSelected ? 2.4 : (p.priority ? 1.4 : 0.7),
    fillColor: lakeColour(p),
    fillOpacity: isSelected ? 1.0 : 0.9,
    opacity: 0.96,
  };
}

function lakeTip(p) {
  const hcls = HCLASS[p.hazard] || 'h-na';
  const rcls = HCLASS[p.risk] || 'h-na';
  return `<b>${esc(p.name || p.id)}</b>${p.priority ? ' <span class="hbadge h-vhigh">PFV ≥10</span>' : ''}`
    + `<br>${fmt(p.area_km2, 3)} km² · ${fmt(p.z)} m · ${esc(tDistrict(p.district, S.districtsMeta))}`
    + `<br>Hazard: <span class="hbadge ${hcls}">${esc(tTier(p.hazard))}</span>`
    + (p.risk ? ` · Risk: <span class="hbadge ${rcls}">${esc(tTier(p.risk))}</span>` : '')
    + `<br>PFV <b>${fmt(p.pfv_Mm3, 1)} Mm³</b>`
    + (p.qp_m3s ? ` · Qp ≈ <b>${fmt(p.qp_m3s)} m³/s</b>` : '');
}

function updateLakeSelectionStyle(prevId, nextId) {
  if (prevId && lakeLayerById.has(prevId)) {
    const prevF = S.lakeById.get(prevId);
    if (prevF) lakeLayerById.get(prevId).setStyle(lakeStyle(prevF.properties, false));
  }
  if (prevId && prioMarkerById.has(prevId)) {
    const prevF = S.lakeById.get(prevId);
    if (prevF) prioMarkerById.get(prevId).setIcon(makePriorityLakeIcon(lakeColour(prevF.properties), false));
  }
  if (nextId && lakeLayerById.has(nextId)) {
    const nextF = S.lakeById.get(nextId);
    if (nextF) {
      const lyr = lakeLayerById.get(nextId);
      lyr.setStyle(lakeStyle(nextF.properties, true));
      if (lyr.bringToFront) lyr.bringToFront();
    }
  }
  if (nextId && prioMarkerById.has(nextId)) {
    const nextF = S.lakeById.get(nextId);
    if (nextF) prioMarkerById.get(nextId).setIcon(makePriorityLakeIcon(lakeColour(nextF.properties), true));
  }
}

function updateFilterCount() {
  const countEl = document.getElementById('filterCount');
  if (!countEl) return;
  countEl.textContent = getLang() === 'ne'
    ? `${fmt(S.lakes.length)} मध्ये ${fmt(S.shown.length)} हिमताल देखाइएको`
    : `${fmt(S.shown.length)} of ${fmt(S.lakes.length)} glacial lakes shown`;
}

function renderLakes() {
  gLakes.clearLayers();
  lakeLayerById.clear();
  prioMarkerById.clear();

  const shown = S.lakes.filter(f => passes(f.properties));
  S.shown = shown;
  updateFilterCount();

  if (!document.getElementById('lLakes').checked) {
    if (S.tab === 'watch') renderTab();
    return;
  }

  L.geoJSON({ type: 'FeatureCollection', features: shown }, {
    renderer: lakeRenderer,
    style: f => lakeStyle(f.properties, f.properties.id === S.sel && S.selKind === 'lake'),
    onEachFeature: (f, lyr) => {
      const lid = f.properties.id;
      lakeLayerById.set(lid, lyr);
      lyr.on('click', () => selectLake(lid, false));
      lyr.bindTooltip(() => lakeTip(f.properties), { sticky: true, direction: 'top' });
    },
  }).addTo(gLakes);

  // CVD-safe diamond beacons on priority lakes for low-zoom clickability
  shown.filter(f => f.properties.priority).forEach(f => {
    const p = f.properties;
    const isSel = p.id === S.sel && S.selKind === 'lake';
    const marker = L.marker([p.lat, p.lon], {
      icon: makePriorityLakeIcon(lakeColour(p), isSel),
      keyboard: true,
      title: p.name || p.id,
    })
      .on('click', () => selectLake(p.id, false))
      .bindTooltip(() => lakeTip(p), { direction: 'top' })
      .addTo(gLakes);
    prioMarkerById.set(p.id, marker);
  });

  if (S.tab === 'watch') renderTab();
}

/* ==========================================================================
   8. Independent Multi-Hazard Overlay Renderers (Lazy-Loaded)
   ========================================================================== */
function drawRiversLayer() {
  gRivers.clearLayers();
  if (!document.getElementById('lRivers').checked) return;
  S.rivers.forEach(b => {
    const st = riverHeadlineStatus(b);
    const bName = getLang() === 'ne' && b.name_ne ? b.name_ne : b.name;
    const snapTag = b.climatology_unmatched
      ? '<br><span class="text-warn">⚠ Live discharge shown; off-mainstem climatology withheld</span>'
      : b.grid_snap_warning
        ? '<br><span class="text-warn">⚠ Cached off-mainstem grid cell</span>'
        : '';
    L.marker([b.lat, b.lon], {
      icon: makeRiverIcon(st, Boolean(b.grid_snap_warning)),
      keyboard: true,
      title: bName,
    })
      .on('click', () => selectRiver(b.id, false))
      .bindTooltip(
        `<b>■ ${esc(bName)}</b> (${esc(b.station)})`
        + `<br>Now: <b>${fmt(b.current_m3s, 1)} m³/s</b> · 14d med: <b>${fmt(b.peak_14d_median_m3s, 1)} m³/s</b>`
        + `<br>Status: <span class="hbadge ${FCLASS[st] || 'h-na'}">${esc(tRiverStatus(st))}</span>${snapTag}`,
        { direction: 'top' }
      )
      .addTo(gRivers);
  });
}

async function drawFaultsLayer() {
  gFaults.clearLayers();
  if (!document.getElementById('lFaults').checked) return;
  if (!S.faults) {
    try { await ensureData('faults'); } catch { return; }
  }
  if (!document.getElementById('lFaults').checked || !S.faults.length) return;
  L.geoJSON({ type: 'FeatureCollection', features: S.faults }, {
    renderer: overlayRenderer,
    style: f => {
      const sl = String((f.properties && f.properties.slip_type) || '').toLowerCase();
      if (sl.includes('reverse') || sl.includes('thrust')) {
        return { color: '#ef4444', weight: 2.5, opacity: 0.88 };
      }
      if (sl.includes('normal')) {
        return { color: '#a78bfa', weight: 1.9, opacity: 0.84, dashArray: '6 4' };
      }
      return { color: '#f59e0b', weight: 2.0, opacity: 0.85, dashArray: '8 3 2 3' };
    },
    onEachFeature: (f, l) => {
      const p = f.properties || {};
      l.bindPopup(
        `<b>${esc(p.name)}</b><br>Kinematics: <b>${esc(p.slip_type || '—')}</b>`
        + (p.dip_deg != null ? `<br>Dip: ${fmt(p.dip_deg, 0)}° ${esc(p.dip_dir || '')}` : '')
        + (p.slip_rate_mm_yr != null ? `<br>Slip rate: ${fmt(p.slip_rate_mm_yr, 1)} mm/yr` : '')
        + '<br><span class="band">GEM Global Active Faults (surface trace only; excludes buried MHT megathrust)</span>'
      );
    },
  }).addTo(gFaults);
}

function drawNodesLayer() {
  gNodes.clearLayers();
  if (!document.getElementById('lNodes').checked) return;
  const nodes = (S.hydromet && S.hydromet.nodes) || [];
  nodes.forEach(nd => {
    const dh = nd.dh_combined || nd.dh_obs || {};
    const lv = dh.level || 'low';
    L.marker([nd.lat, nd.lon], {
      icon: makeNodeIcon(lv),
      keyboard: true,
      title: nd.name,
    })
      .on('click', () => selectNode(nd.id, false))
      .bindTooltip(
        `<b>▲ ${esc(nd.name)}</b> (${esc(nd.zone)})`
        + `<br>7d rain: <b>${fmt(nd.rain_past_7d_mm, 1)} mm</b> · 5d fcst: <b>${fmt(nd.rain_next_5d_mm, 1)} mm</b>`
        + `<br>Dahal–Hasegawa: <b>${fmt((dh.max_ratio || 0) * 100, 0)}%</b> <span class="hbadge ${DHCLASS[lv] || 'h-low'}">${esc(tDhLevel(lv))}</span>`,
        { direction: 'top' }
      )
      .addTo(gNodes);
  });
}

async function drawLandslidesLayer() {
  gLs.clearLayers();
  if (!document.getElementById('lLandslides').checked) return;
  if (!S.landslides) {
    try { await ensureData('landslides'); } catch { return; }
  }
  if (!document.getElementById('lLandslides').checked) return;
  const isNe = getLang() === 'ne';
  S.landslides.forEach(ev => {
    const ft = ev.feature_type || 'landslide_scar';
    const col = ft === 'landslide_event'
      ? '#c2410c'
      : ft === 'coseismic_failure'
        ? '#b91c1c'
        : ft === 'hazard_report'
          ? '#0284c7'
          : ft === 'susceptibility_zone'
            ? '#7c3aed'
            : '#eab308';
    const link = safeUrl(ev.evidence_url || ev.url);
    const titleTxt = (isNe && ev.title_ne) ? ev.title_ne : (ev.title || 'Landslide record');
    const dateVal = ev.event_date_utc || ev.date;
    L.circleMarker([ev.lat, ev.lon], {
      renderer: overlayRenderer,
      radius: (ev.fatalities != null && ev.fatalities > 0)
        ? Math.min(8, 3.8 + Math.log10(ev.fatalities + 1) * 2.2)
        : (ft === 'landslide_event' || ft === 'coseismic_failure' ? 4.8 : 3.6),
      color: '#0a0f16',
      weight: 1,
      fillColor: col,
      fillOpacity: 0.85,
    })
      .bindPopup(
        `<b>◇ ${esc(titleTxt)}</b><br>${badgeLsType(ft)} · ${esc(ev.source || '')}`
        + `<br>Date: <b>${fmtNullDate(dateVal)}</b>`
        + `<br>Trigger: <b>${esc(ev.trigger || 'mapped scar')}</b>`
        + `<br>Fatalities: <b>${fmtNullCount(ev.fatalities)}</b>`
        + (ev.verified === true ? ' <span class="hbadge h-low">Verified</span>' : '')
        + (link ? `<br><a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open source record ↗</a>` : '')
      )
      .addTo(gLs);
  });
}

async function drawHydroLayer() {
  gHydro.clearLayers();
  if (!document.getElementById('lHydro').checked) return;
  if (!S.expo) {
    try { await ensureData('exposure'); } catch { return; }
  }
  if (!document.getElementById('lHydro').checked) return;
  S.expo.filter(o => o.kind === 'hydropower').forEach(o => {
    L.circleMarker([o.lat, o.lon], {
      renderer: overlayRenderer,
      radius: 4.8,
      color: '#0a0f16',
      weight: 1.4,
      fillColor: '#facc15',
      fillOpacity: 0.94,
    })
      .bindPopup(
        `<b>▪ ${esc(o.name || 'Hydropower facility')}</b>`
        + `<br>${o.capacity_mw ? `${fmt(o.capacity_mw, 1)} MW` : 'Capacity not tagged in OSM'}`
      )
      .addTo(gHydro);
  });
}

async function drawEqHistLayer() {
  gEqH.clearLayers();
  if (!document.getElementById('lEqHist').checked) return;
  if (!S.eqHist) {
    try { await ensureData('eq_history_m6'); } catch { return; }
  }
  if (!document.getElementById('lEqHist').checked) return;
  S.eqHist.forEach(e => {
    L.circleMarker([e.lat, e.lon], {
      renderer: overlayRenderer,
      radius: Math.max(5.5, Math.min(18, 2.3 * Number(e.mag || 6))),
      color: '#dc2626',
      weight: 1.8,
      dashArray: '4 3',
      fillColor: '#dc2626',
      fillOpacity: 0.16,
    })
      .bindPopup(
        `<b>◌ M ${fmt(e.mag, 1)}</b> ${esc(e.place || '')}`
        + `<br>${new Date(e.time).getUTCFullYear()} · depth ${fmt(e.depth_km, 0)} km`
      )
      .addTo(gEqH);
  });
}

async function drawGlofLayer() {
  gGlof.clearLayers();
  if (!document.getElementById('lGlof').checked) return;
  if (!S.glofHist) {
    try { await ensureData('glof_history'); } catch { return; }
  }
  if (!document.getElementById('lGlof').checked) return;
  S.glofHist.forEach(g => {
    L.marker([g.lat, g.lon], {
      icon: makeGlofIcon(),
      keyboard: true,
      title: g.lake || 'Recorded GLOF',
    })
      .bindPopup(
        `<b>▼ ${esc(g.lake)}</b> ${g.year ? fmt(g.year) : ''}`
        + `<br>${esc(g.lake_type || '')}${g.mechanism && g.mechanism !== 'Unknown' ? ' · ' + esc(g.mechanism) : ''}`
        + `<br>Basin: ${esc(g.basin || '—')}`
        + (g.lives ? `<br>Lives lost: <b>${fmt(g.lives)}</b>` : '')
        + (g.discharge ? `<br>Reported peak discharge: <b>${fmt(g.discharge)} m³/s</b>` : '')
      )
      .addTo(gGlof);
  });
}

async function drawGdacsLayer() {
  gGdacs.clearLayers();
  if (!document.getElementById('lGdacs').checked) return;
  if (!S.gdacs) {
    try { await ensureData('gdacs_alerts'); } catch { return; }
  }
  if (!document.getElementById('lGdacs').checked) return;
  S.gdacs.forEach(a => {
    const link = safeUrl(a.url, ['www.gdacs.org', 'gdacs.org']);
    L.marker([a.lat, a.lon], {
      icon: makeGdacsIcon(a.alert_level, a.type),
      keyboard: true,
      title: a.name,
    })
      .bindPopup(
        `<b>⬡ GDACS ${esc(a.type)}: ${esc(a.name)}</b>`
        + `<br>Alert: <b>${esc(a.alert_level)}</b> · ${esc(a.from_date)}`
        + `<br>${esc(a.severity_text || '')}`
        + (link ? `<br><a href="${esc(link)}" target="_blank" rel="noopener noreferrer">GDACS report ↗</a>` : '')
      )
      .addTo(gGdacs);
  });
}

function drawEq() {
  gEq.clearLayers();
  if (!document.getElementById('lEq').checked) return;
  S.live.forEach(f => {
    const c = f.geometry && f.geometry.coordinates;
    const p = f.properties || {};
    if (!c || c.length < 2) return;
    const u = safeUrl(p.url, ['*.usgs.gov']);
    L.marker([c[1], c[0]], {
      icon: makeQuakeIcon(Number(p.mag) || 2.5),
      keyboard: true,
      title: `M ${fmt(p.mag, 1)} ${p.place || ''}`,
    })
      .bindPopup(
        `<b>◎ M ${fmt(p.mag, 1)}</b> ${esc(p.place || '')}`
        + `<br>${esc(fmtNpt(p.time))} (${esc(fmtAge(p.time))})`
        + `<br>Depth: ${fmt(c[2], 1)} km`
        + (u ? `<br><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">USGS event page ↗</a>` : '')
      )
      .addTo(gEq);
  });
}

function drawMmi() {
  gMmi.clearLayers();
  if (!S.mmi || !S.mmi.gj || !document.getElementById('lMmi').checked) return;
  L.geoJSON(S.mmi.gj, {
    renderer: overlayRenderer,
    style: ft => ({
      color: (ft.properties && /^#[0-9a-f]{3,8}$/i.test(String(ft.properties.color || '')))
        ? ft.properties.color
        : '#eab308',
      weight: 1.7,
      opacity: 0.88,
      fill: false,
    }),
    onEachFeature: (ft, l) => {
      const mmiVal = ft.properties ? ft.properties.value : '';
      l.bindTooltip(`MMI ${esc(mmiVal)} — ${esc(S.mmi.event)}`);
    },
  }).addTo(gMmi);
}

/* ==========================================================================
   9. Honest Freshness Telemetry, Stale Banner & Compound Hazard Strip
   ========================================================================== */
function setToast(msg) {
  const box = document.getElementById('liveToast');
  const txt = document.getElementById('liveToastMsg');
  if (!box || !txt) return;
  if (!msg) {
    box.classList.add('is-hidden');
    return;
  }
  txt.textContent = msg;
  box.classList.remove('is-hidden');
}

function updateEqPill() {
  const pill = document.getElementById('pill-eq');
  const keq = document.getElementById('k-eq');
  const isNe = getLang() === 'ne';

  if (S.liveStatus === 'live') {
    const maxM = S.live.length
      ? Math.max(...S.live.map(f => Number((f.properties && f.properties.mag) || 0)))
      : null;
    if (pill) {
      pill.className = 'pill live';
      pill.innerHTML = isNe
        ? `<span class="dot"></span>${fmt(S.live.length)} भूकम्प${maxM ? ` (अधिकतम M${maxM.toFixed(1)})` : ''} · ${esc(t('liveFresh'))}`
        : `<span class="dot"></span>${S.live.length} quake${S.live.length === 1 ? '' : 's'}${maxM ? ` (max M${maxM.toFixed(1)})` : ''} · ${esc(t('liveFresh'))}`;
    }
    if (keq) {
      keq.textContent = isNe
        ? `${fmt(S.live.length)} प्रत्यक्ष (${S.eqWindow})`
        : `${S.live.length} live (${S.eqWindow})`;
    }
  } else if (S.liveStatus === 'offline') {
    if (pill) {
      pill.className = 'pill err';
      pill.innerHTML = isNe
        ? `<span class="dot"></span>भूकम्प: ${esc(t('liveOffline'))}`
        : `<span class="dot"></span>quakes: ${esc(t('liveOffline'))}`;
    }
    if (keq) keq.textContent = t('liveOffline');
  } else if (pill) {
    pill.className = 'pill';
    pill.innerHTML = isNe
      ? '<span class="dot"></span>भूकम्प: लोड हुँदै…'
      : '<span class="dot"></span>quakes: fetching…';
  }
}

function updateStatusPills() {
  // 0. Live USGS earthquake pill (ensures immediate re-translation on EN/नेपाली switch)
  updateEqPill();

  // 1. Build pill — never green .live if > 24h old
  const bp = document.getElementById('pill-build');
  if (bp && S.summary) {
    const hrs = ageHours(S.summary.build);
    const cadenceHrs = ((S.summary.refresh_interval_days || 7) + 1) * 24;
    const cls = hrs <= 24 ? 'live' : hrs <= cadenceHrs ? 'info' : 'stale';
    bp.className = `pill ${cls}`;
    bp.innerHTML = `<span class="dot"></span>${esc(fmtNpt(S.summary.build, false))} · ${esc(fmtAge(S.summary.build))}`;
  }

  // 2. River flood pill
  const fp = document.getElementById('pill-flood');
  if (fp && S.rivers.length) {
    const rAgeH = ageHours(S.riversMeta && S.riversMeta.updated_utc);
    const isFresh = rAgeH <= 24;
    const nAlert = S.rivers.filter(b => isRiverAlertStatus(b.status_14d) || isRiverAlertStatus(b.status_now)).length;
    const nUnassessed = S.rivers.filter(b => riverHeadlineStatus(b) === 'unassessed').length;
    const nNormal = Math.max(0, S.rivers.length - nAlert - nUnassessed);
    const snapCnt = S.rivers.filter(b => b.grid_snap_warning).length;
    let cls = 'stale';
    if (nAlert > 0) cls = 'watch';
    else if (rAgeH > 168) cls = 'err';
    else if (isFresh) cls = 'live';
    const ageLbl = isFresh ? t('liveFresh') : `${t('liveSnapshot')} · ${fmtAge(S.riversMeta.updated_utc)}`;
    const statusSummary = nAlert
      ? `${nAlert} alert`
      : nUnassessed
        ? `${nNormal} normal · ${nUnassessed} unassessed`
        : `${S.rivers.length} normal`;
    fp.className = `pill ${cls}`;
    fp.innerHTML = `<span class="dot"></span>rivers: ${esc(statusSummary)} · ${esc(ageLbl)}`;
    document.getElementById('k-rivers').textContent = nAlert
      ? `${nAlert} alert / ${S.rivers.length}`
      : nUnassessed
        ? `${nNormal} normal · ${nUnassessed} unassessed`
        : `${S.rivers.length} normal`;
    document.getElementById('k-rivers-sub').textContent = `${ageLbl}${snapCnt ? ` · ${snapCnt} snap ⚠` : ''}`;
  }

  // 3. Landslide rainfall pill
  const lp = document.getElementById('pill-ls');
  const nodes = (S.hydromet && S.hydromet.nodes) || [];
  if (lp && nodes.length) {
    const hAgeH = ageHours(S.hydromet && S.hydromet.updated_utc);
    const fcExp = S.hydromet && S.hydromet.forecast_expires_utc ? Date.parse(S.hydromet.forecast_expires_utc) : Infinity;
    const isExpired = Number.isFinite(fcExp) && Date.now() > fcExp;
    const isFresh = hAgeH <= 24 && !isExpired;
    const nEx = nodes.filter(n => ['watch', 'exceeded'].includes(((n.dh_combined || n.dh_obs) || {}).level)).length;
    let cls = 'stale';
    if (nEx > 0) cls = 'watch';
    else if (isExpired || hAgeH > 168) cls = 'err';
    else if (isFresh) cls = 'live';
    const ageLbl = isFresh
      ? t('liveFresh')
      : isExpired
        ? `Expired · ${fmtAge(S.hydromet.updated_utc)}`
        : `${t('liveSnapshot')} · ${fmtAge(S.hydromet.updated_utc)}`;
    lp.className = `pill ${cls}`;
    lp.innerHTML = `<span class="dot"></span>rain-ls: ${nEx ? `${nEx} watch` : '24 low'} · ${esc(ageLbl)}`;
    document.getElementById('k-ls').textContent = nEx ? `${nEx} watch / 24` : '24 low';
    document.getElementById('k-ls-sub').textContent = `${ageLbl} · D–H (2008)`;
  }

  updateSourceHealthButton();
  updateStaleBanner();
  evaluateCompoundHazards();
}

function updateSourceHealthButton() {
  const btn = document.getElementById('btnSourceHealth');
  const lbl = document.getElementById('sourceHealthBtnLbl');
  if (!btn || !lbl) return;

  let health = 'degraded';
  let suffix = '';
  if (S.manifest) {
    health = S.manifest.overall_health || 'degraded';
    const sc = S.manifest.source_counts || {};
    const avail = sc.available ?? 0;
    const oper = sc.operational ?? sc.total ?? 0;
    suffix = oper ? ` · ${tHealthState(health)} (${avail}/${oper})` : ` · ${tHealthState(health)}`;
  } else if (S.summary) {
    const buildAge = ageHours(S.summary.build);
    const bpStatus = S.summary.bipad_official && S.summary.bipad_official.status;
    if (buildAge > 168) health = 'stale';
    else if (bpStatus === 'unavailable' || S.summary.build_mode === 'offline') health = 'degraded';
    else health = 'healthy';
    suffix = ` · ${tHealthState(health)}`;
  }

  btn.classList.remove('healthy', 'degraded', 'stale');
  btn.classList.add(health === 'healthy' ? 'healthy' : health === 'stale' ? 'stale' : 'degraded');
  lbl.textContent = `${t('btnSourceHealth')}${suffix}`;
}

function updateStaleBanner() {
  const banner = document.getElementById('staleBanner');
  const msgEl = document.getElementById('staleBannerMsg');
  if (!banner || !msgEl) return;

  const reasons = [];
  if (S.hydromet) {
    const expMs = Date.parse(S.hydromet.forecast_expires_utc || '');
    const hAge = ageHours(S.hydromet.updated_utc);
    if (Number.isFinite(expMs) && Date.now() > expMs) {
      reasons.push(`Hydromet / rainfall-landslide 5-day forecast expired ${fmtNpt(expMs, false)} (snapshot ${fmtAge(S.hydromet.updated_utc)})`);
    } else if (hAge > 168) {
      reasons.push(`Hydromet snapshot is ${fmtAge(S.hydromet.updated_utc)}`);
    }
  }
  if (S.riversMeta) {
    const expMs = Date.parse(S.riversMeta.forecast_expires_utc || '');
    const rAge = ageHours(S.riversMeta.updated_utc);
    if (Number.isFinite(expMs) && Date.now() > expMs) {
      reasons.push(`GloFAS river forecast expired ${fmtNpt(expMs, false)}`);
    } else if (rAge > 168) {
      reasons.push(`GloFAS river snapshot is ${fmtAge(S.riversMeta.updated_utc)}`);
    }
  }
  if (S.summary && ageHours(S.summary.build) > 168) {
    reasons.push(`Weekly build snapshot is ${fmtAge(S.summary.build)}`);
  }

  if (reasons.length) {
    msgEl.innerHTML = `<b>${esc(t('staleExpiredTitle'))}</b> ${esc(reasons.join(' · '))}.`;
    banner.classList.remove('is-hidden');
  } else {
    banner.classList.add('is-hidden');
  }
}

function evaluateCompoundHazards() {
  const banner = document.getElementById('compoundBanner');
  const msgEl = document.getElementById('compoundBannerMsg');
  if (!banner || !msgEl) return;

  const alerts = [];
  const bigQuakes = S.live.filter(f => f.properties && Number(f.properties.mag) >= 4.5);
  const prioLakes = S.lakes.filter(f => f.properties.priority || f.properties.hazard === 'very high');
  const hotNodes = ((S.hydromet && S.hydromet.nodes) || []).filter(n => {
    const lv = ((n.dh_combined || n.dh_obs) || {}).level;
    return lv === 'elevated' || lv === 'watch' || lv === 'exceeded';
  });

  bigQuakes.forEach(q => {
    const c = q.geometry && q.geometry.coordinates;
    if (!c) return;
    const nearPrio = prioLakes.filter(lk => hav(c[0], c[1], lk.properties.lon, lk.properties.lat) <= 100);
    const nearHotNodes = hotNodes.filter(nd => hav(c[0], c[1], nd.lon, nd.lat) <= 100);
    if (nearPrio.length || nearHotNodes.length) {
      const parts = [];
      if (nearPrio.length) parts.push(`${nearPrio.length} high-hazard/priority glacial lake(s) ≤100 km`);
      if (nearHotNodes.length) parts.push(`${nearHotNodes.length} elevated rainfall-landslide zone(s) ≤100 km`);
      alerts.push(`Live M${fmt(q.properties.mag, 1)} (${q.properties.place || 'Nepal region'}, ${fmtAge(q.properties.time)}) overlaps ${parts.join(' and ')} — heightened coseismic avalanche/landslide & GLOF screening awareness.`);
    }
  });

  const warmIce = ((S.hydromet && S.hydromet.priority_lakes) || []).filter(x => x.warm_rain_on_ice);
  if (warmIce.length) {
    alerts.push(`Warm rain-on-ice condition flagged at ${warmIce.map(x => x.name).join(', ')} (liquid rain ≥10 mm with 0 °C isotherm ≥300 m above lake).`);
  }

  const alertBasins = S.rivers.filter(b => isRiverAlertStatus(b.status_14d) || isRiverAlertStatus(b.status_now));
  if (alertBasins.length && hotNodes.length) {
    const bProvs = new Set(alertBasins.map(b => b.prov));
    const overlap = hotNodes.filter(n => bProvs.has(n.prov));
    if (overlap.length) {
      alerts.push(`Concurrent fluvial flood watch (${alertBasins.map(b => b.name).join(', ')}) and elevated rainfall-landslide indices (${overlap.map(n => n.name).join(', ')}).`);
    }
  }

  if (alerts.length) {
    msgEl.innerHTML = `<b>⚠ ${esc(t('compoundTitle'))}</b> ${esc(alerts.join(' | '))}`;
    banner.classList.remove('is-hidden');
  } else {
    banner.classList.add('is-hidden');
  }
}

/* ==========================================================================
   10. Live Browser Feeds (USGS Nepal FDSN + GloFAS + Open-Meteo Rainfall)
   ========================================================================== */
let eqAbort = null;
let eqDetailSeq = 0;

function usgsFdsnUrl(win) {
  const now = Date.now();
  const cfg = win === 'day'
    ? { days: 1, minMag: 2.0 }
    : win === 'month'
      ? { days: 30, minMag: 3.5 }
      : { days: 7, minMag: 2.5 };
  const startIso = new Date(now - cfg.days * 86400000).toISOString().slice(0, 19);
  return 'https://earthquake.usgs.gov/fdsnws/event/1/query'
    + `?format=geojson&minlatitude=24.2&maxlatitude=32.6&minlongitude=77.9&maxlongitude=90.3`
    + `&minmagnitude=${cfg.minMag}&orderby=time&starttime=${encodeURIComponent(startIso)}`;
}

async function loadEq(force = false) {
  if (document.hidden && !force) return { ok: true, skipped: true };
  const win = document.getElementById('eqWindow').value;
  S.eqWindow = win;
  S.liveStatus = 'loading';
  updateEqPill();

  if (eqAbort) eqAbort.abort();
  eqAbort = new AbortController();

  // Clear stale ShakeMap/ground-failure overlays on window change
  S.mmi = null;
  S.gf = null;
  gMmi.clearLayers();
  const mySeq = ++eqDetailSeq;

  try {
    const resp = await fetch(usgsFdsnUrl(win), {
      cache: 'no-store',
      signal: combinedSignal(eqAbort, 15000),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const gj = await resp.json();
    S.live = (gj.features || [])
      .filter(f => {
        const c = f && f.geometry && f.geometry.coordinates;
        return Array.isArray(c)
          && c.length >= 2
          && typeof c[0] === 'number' && Number.isFinite(c[0])
          && typeof c[1] === 'number' && Number.isFinite(c[1])
          && c[0] >= -180 && c[0] <= 180
          && c[1] >= -90 && c[1] <= 90;
      })
      .map(f => {
        const c = f.geometry.coordinates;
        const depth = typeof c[2] === 'number' && Number.isFinite(c[2]) ? c[2] : null;
        return {
          ...f,
          geometry: { ...f.geometry, coordinates: [c[0], c[1], depth] },
        };
      })
      .sort((a, b) => ((b.properties && b.properties.time) || 0) - ((a.properties && a.properties.time) || 0));
    S.liveFetchedAt = new Date().toISOString();
    S.liveStatus = 'live';

    updateEqPill();
    const keqSub = document.getElementById('k-eq-sub');
    if (keqSub) {
      const nFaults = (S.summary && S.summary.active_faults && S.summary.active_faults.n_traces) || 70;
      keqSub.textContent = `NDRRMA BIPAD · USGS + ${fmt(nFaults)} GEM traces`;
    }

    drawEq();
    evaluateCompoundHazards();
    if (S.tab === 'live') renderTab();
    if (S.selKind === 'district' && S.selDistrict) renderDistrictByName(S.selDistrict, false);

    const big = S.live.find(f => f.properties && Number(f.properties.mag) >= 4.5);
    if (big) loadEventDetail(big, mySeq);
    return { ok: true, count: S.live.length };
  } catch (err) {
    if (err && err.name === 'AbortError') return { ok: false, aborted: true };
    S.liveStatus = 'offline';
    S.live = [];
    updateEqPill();
    drawEq();
    evaluateCompoundHazards();
    if (S.tab === 'live') renderTab();
    return { ok: false, error: err ? err.message : 'network error' };
  }
}

async function loadEventDetail(f, seq) {
  const detailUrl = safeUrl(f.properties && f.properties.detail, ['*.usgs.gov']);
  if (!detailUrl) return;
  try {
    const resp = await fetch(detailUrl, { signal: combinedSignal(null, 12000) });
    if (!resp.ok || seq !== eqDetailSeq) return;
    const d = await resp.json();
    if (seq !== eqDetailSeq) return;
    const prods = (d.properties && d.properties.products) || {};
    const gf = (prods['ground-failure'] || [])[0];
    S.gf = gf && gf.properties ? {
      landslide_alert: gf.properties['landslide-alert'],
      landslide_value: gf.properties['landslide-hazard-alert-value'],
      landslide_pop: gf.properties['landslide-population-alert-value'],
      liq_alert: gf.properties['liquefaction-alert'],
      event: `M ${fmt(f.properties.mag, 1)} ${f.properties.place || ''}`,
      url: safeUrl(f.properties.url, ['*.usgs.gov']),
    } : null;

    const sm = (prods.shakemap || [])[0];
    const contEntry = sm && sm.contents && sm.contents['download/cont_mmi.json'];
    const contUrl = safeUrl(contEntry && contEntry.url, ['*.usgs.gov']);
    if (contUrl) {
      const mResp = await fetch(contUrl, { signal: combinedSignal(null, 12000) });
      if (mResp.ok && seq === eqDetailSeq) {
        const mj = await mResp.json();
        if (seq === eqDetailSeq) {
          S.mmi = { event: `M ${fmt(f.properties.mag, 1)} ${f.properties.place || ''}`, gj: mj };
          drawMmi();
        }
      }
    }
    if (S.tab === 'live') renderTab();
  } catch {
    // Non-fatal: ShakeMap/ground-failure optional
  }
}

async function refreshLiveGlofas() {
  if (!S.rivers.length) return { ok: false, error: 'no basins loaded' };
  // Query snapped climatology cell for calibrated basins so live discharge matches
  // the Gumbel EV1 reanalysis cell; query gauge coords for off-mainstem snap-warned
  // basins (and withhold return-period grading until weekly reanalysis refits).
  const queryCoords = S.rivers.map(b => {
    const c = b.climatology || {};
    const useClimCell = !b.grid_snap_warning
      && c.grid_lat != null && c.grid_lon != null
      && Number.isFinite(Number(c.grid_lat))
      && Number.isFinite(Number(c.grid_lon));
    return {
      lat: useClimCell ? Number(c.grid_lat) : Number(b.lat),
      lon: useClimCell ? Number(c.grid_lon) : Number(b.lon),
    };
  });
  const lats = queryCoords.map(pt => pt.lat.toFixed(4)).join(',');
  const lons = queryCoords.map(pt => pt.lon.toFixed(4)).join(',');
  const base = safeUrl(
    (S.summary && S.summary.live_feeds && S.summary.live_feeds.open_meteo_flood)
      || 'https://flood-api.open-meteo.com/v1/flood',
    ['flood-api.open-meteo.com']
  ) || 'https://flood-api.open-meteo.com/v1/flood';
  const u = `${base}?latitude=${lats}&longitude=${lons}&daily=river_discharge,river_discharge_median,river_discharge_mean,river_discharge_p25,river_discharge_p75,river_discharge_max&past_days=30&forecast_days=30`;
  const resp = await fetch(u, { cache: 'no-store', signal: combinedSignal(null, 15000) });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const arr = await resp.json();
  const items = Array.isArray(arr) ? arr : [arr];
  const nowIso = new Date().toISOString();
  const todayUtc = nowIso.slice(0, 10);
  let lastDate = '';

  const pickNear = (series, idx) => {
    if (!Array.isArray(series) || !series.length) return null;
    for (const i of [idx, idx - 1, idx + 1]) {
      if (i >= 0 && i < series.length && series[i] != null && Number.isFinite(Number(series[i]))) {
        return Number(series[i]);
      }
    }
    for (let i = series.length - 1; i >= 0; i--) {
      if (series[i] != null && Number.isFinite(Number(series[i]))) return Number(series[i]);
    }
    return null;
  };
  const finiteSlice = (series, start, end) => (Array.isArray(series) ? series.slice(start, end) : [])
    .filter(v => v != null && Number.isFinite(Number(v)))
    .map(Number);

  items.forEach((it, idx) => {
    const b = S.rivers[idx];
    if (!b || !it || !it.daily) return;
    const d = it.daily;
    const times = Array.isArray(d.time) ? d.time : [];
    const foundIdx = times.indexOf(todayUtc);
    const idx0 = foundIdx >= 0 ? foundIdx : Math.min(30, Math.max(0, times.length - 1));
    const dis = Array.isArray(d.river_discharge) ? d.river_discharge : [];
    const rawMed = Array.isArray(d.river_discharge_median) ? d.river_discharge_median : [];
    const hasMed = rawMed.some(v => v != null && Number.isFinite(Number(v)));
    const med = hasMed ? rawMed : dis;
    const p25 = Array.isArray(d.river_discharge_p25) ? d.river_discharge_p25 : [];
    const p75 = Array.isArray(d.river_discharge_p75) && d.river_discharge_p75.some(v => v != null) ? d.river_discharge_p75 : med;
    const mx = Array.isArray(d.river_discharge_max) && d.river_discharge_max.some(v => v != null) ? d.river_discharge_max : p75;

    const cur = pickNear(dis, idx0) ?? pickNear(med, idx0);
    const fcMed = finiteSlice(med, idx0, idx0 + 14);
    const fcP75 = finiteSlice(p75, idx0, idx0 + 14);
    const fcMax = finiteSlice(mx, idx0, idx0 + 14);

    b.current_m3s = cur != null ? Math.round(cur * 10) / 10 : b.current_m3s;
    b.peak_14d_median_m3s = fcMed.length ? Math.round(Math.max(...fcMed) * 10) / 10 : b.current_m3s;
    b.peak_14d_p75_m3s = fcP75.length ? Math.round(Math.max(...fcP75) * 10) / 10 : b.peak_14d_median_m3s;
    b.peak_14d_max_m3s = fcMax.length ? Math.round(Math.max(...fcMax) * 10) / 10 : b.peak_14d_p75_m3s;

    const clim = b.climatology || {};
    const hasRetGrid = it.latitude != null && it.longitude != null
      && Number.isFinite(Number(it.latitude)) && Number.isFinite(Number(it.longitude));
    const hasClimGrid = clim.grid_lat != null && clim.grid_lon != null
      && Number.isFinite(Number(clim.grid_lat)) && Number.isFinite(Number(clim.grid_lon));
    const cellDistKm = (hasClimGrid && hasRetGrid)
      ? hav(Number(it.longitude), Number(it.latitude), Number(clim.grid_lon), Number(clim.grid_lat))
      : null;
    const canGradeClim = !b.grid_snap_warning
      && Number(clim.q50) > 0
      && Number(clim.q20) > 0
      && (cellDistKm == null || cellDistKm <= 3.0);

    if (canGradeClim) {
      b.climatology_unmatched = false;
      b.anomaly_ratio = (clim.q50 > 0 && b.current_m3s != null)
        ? Math.round((b.current_m3s / clim.q50) * 100) / 100
        : null;
      b.status_now = classifyRiverStatus(b.current_m3s, clim);
      b.status_14d = classifyRiverStatus(b.peak_14d_median_m3s, clim);
    } else {
      b.climatology_unmatched = true;
      b.grid_snap_warning = true;
      b.anomaly_ratio = null;
      b.status_now = 'unassessed';
      b.status_14d = 'unassessed';
      const distTxt = cellDistKm != null ? ` (${cellDistKm.toFixed(1)} km from cached climatology cell)` : '';
      b.grid_snap_note = `Live discharge is shown from the corrected gauge cell, while return-period grading (Q2/Q5/Q20) and anomaly ratios are withheld because cached climatology sits off-mainstem/mismatched${distTxt} — refits automatically on the next weekly live pipeline run.`;
    }
    b.fetched_utc = nowIso;
    b.series = {
      today_index: idx0,
      time: times,
      discharge: dis,
      median: rawMed,
      mean: Array.isArray(d.river_discharge_mean) ? d.river_discharge_mean : [],
      p25,
      p75,
      max: mx,
    };
    if (times.length) lastDate = times[times.length - 1];
  });

  if (S.riversMeta) {
    S.riversMeta.updated_utc = nowIso;
    S.riversMeta.mode = 'live_browser';
    if (lastDate) S.riversMeta.forecast_expires_utc = `${lastDate}T23:59:59Z`;
  }
  return { ok: true, count: items.length };
}

function extractFreezingAndSoil(it, todayIdx, todayNpt, nowHourNpt) {
  const daily = (it && it.daily) || {};
  const hourly = (it && it.hourly) || {};
  const hTimes = Array.isArray(hourly.time) ? hourly.time : [];

  const pickNearFinite = (arr, targetIdx) => {
    if (!Array.isArray(arr) || !arr.length) return null;
    const clamped = Math.max(0, Math.min(targetIdx, arr.length - 1));
    for (let d = 0; d <= 6; d++) {
      for (const idx of d === 0 ? [clamped] : [clamped - d, clamped + d]) {
        if (idx >= 0 && idx < arr.length && arr[idx] != null && Number.isFinite(Number(arr[idx]))) {
          return Number(arr[idx]);
        }
      }
    }
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i] != null && Number.isFinite(Number(arr[i]))) return Number(arr[i]);
    }
    return null;
  };

  let hIdx = hTimes.indexOf(nowHourNpt);
  if (hIdx < 0 && todayNpt) hIdx = hTimes.findIndex(ts => String(ts).startsWith(todayNpt));
  if (hIdx < 0) hIdx = todayIdx * 24;

  const flDaily = Array.isArray(daily.freezing_level_height_max) ? daily.freezing_level_height_max : [];
  const flHourly = Array.isArray(hourly.freezinglevel_height) ? hourly.freezinglevel_height : [];
  const flDailyVals = flDaily.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
  const flHourlyVals = flHourly.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
  const flAll = flDailyVals.length ? flDailyVals : flHourlyVals;
  const flMax = flAll.length ? Math.round(Math.max(...flAll) * 10) / 10 : null;
  const flNowRaw = flDailyVals.length
    ? pickNearFinite(flDaily, todayIdx)
    : (flHourlyVals.length ? pickNearFinite(flHourly, hIdx) : null);
  const flNow = flNowRaw != null ? Math.round(flNowRaw * 10) / 10 : null;

  const smDaily = Array.isArray(daily.soil_moisture_0_to_7cm_mean) ? daily.soil_moisture_0_to_7cm_mean : [];
  const smHourly = Array.isArray(hourly.soil_moisture_0_to_7cm) ? hourly.soil_moisture_0_to_7cm : [];
  const smDailyVals = smDaily.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
  const smHourlyVals = smHourly.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
  const smNowRaw = smDailyVals.length
    ? pickNearFinite(smDaily, todayIdx)
    : (smHourlyVals.length ? pickNearFinite(smHourly, hIdx) : null);
  const smNow = smNowRaw != null ? Math.round(smNowRaw * 1000) / 1000 : null;

  return { flNow, flMax, smNow };
}

async function fetchOpenMeteoBatch(base, coords) {
  const lats = coords.map(pt => Number(pt.lat).toFixed(4)).join(',');
  const lons = coords.map(pt => Number(pt.lon).toFixed(4)).join(',');
  const common = `latitude=${lats}&longitude=${lons}&past_days=7&forecast_days=5&timezone=Asia%2FKathmandu`;
  // Request valid Open-Meteo Forecast API variables directly (freezing level &
  // topsoil moisture are hourly variables, avoiding HTTP 400 daily errors).
  const urls = [
    `${base}?${common}&daily=rain_sum,snowfall_sum,precipitation_sum,temperature_2m_max&hourly=freezinglevel_height,soil_moisture_0_to_7cm`,
    `${base}?${common}&daily=rain_sum,snowfall_sum,precipitation_sum,temperature_2m_max&hourly=freezinglevel_height`,
    `${base}?${common}&daily=rain_sum,snowfall_sum,precipitation_sum,temperature_2m_max`,
  ];
  let resp = null;
  for (const url of urls) {
    resp = await fetch(url, { cache: 'no-store', signal: combinedSignal(null, 15000) });
    if (resp.status !== 400) break;
  }
  if (!resp || !resp.ok) throw new Error(`HTTP ${resp ? resp.status : 'network'}`);
  const arr = await resp.json();
  return Array.isArray(arr) ? arr : [arr];
}

async function refreshLiveHydromet() {
  const nodes = (S.hydromet && S.hydromet.nodes) || [];
  if (!nodes.length) return { ok: false, error: 'no nodes loaded' };
  const priorityLakes = (S.hydromet && S.hydromet.priority_lakes) || [];
  const prevLakesUpdatedUtc = S.hydromet.priority_lakes_updated_utc || S.hydromet.updated_utc || null;

  const base = safeUrl(
    (S.summary && S.summary.live_feeds && S.summary.live_feeds.open_meteo)
      || 'https://api.open-meteo.com/v1/forecast',
    ['api.open-meteo.com']
  ) || 'https://api.open-meteo.com/v1/forecast';

  const [nodeRes, lakeRes] = await Promise.allSettled([
    fetchOpenMeteoBatch(base, nodes),
    priorityLakes.length ? fetchOpenMeteoBatch(base, priorityLakes) : Promise.resolve([]),
  ]);

  if (nodeRes.status !== 'fulfilled') {
    throw nodeRes.reason || new Error('Hydromet node fetch failed');
  }
  const items = nodeRes.value;
  const nowMs = Date.now();
  const nowIso = new Date(nowMs).toISOString();
  const nptIso = new Date(nowMs + NPT_OFFSET_MS).toISOString();
  const todayNpt = nptIso.slice(0, 10);
  const nowHourNpt = `${nptIso.slice(0, 13)}:00`;
  let lastDate = '';

  items.forEach((it, idx) => {
    const nd = nodes[idx];
    if (!nd || !it || !it.daily) return;
    const d = it.daily;
    const times = Array.isArray(d.time) ? d.time : [];
    const foundDay = times.indexOf(todayNpt);
    const todayIdx = foundDay >= 0 ? foundDay : Math.min(7, Math.max(0, times.length - 1));
    const precip = (d.precipitation_sum || []).map(v => Math.max(0, Number(v) || 0));
    const snow = (d.snowfall_sum || []).map(v => Math.max(0, Number(v) || 0));
    const hasRainSum = Array.isArray(d.rain_sum) && d.rain_sum.some(v => v != null && Number.isFinite(Number(v)));
    const rain = hasRainSum
      ? d.rain_sum.map(v => Math.max(0, Number(v) || 0))
      : precip.map((pr, i) => Math.max(0, pr - (snow[i] || 0)));

    const obs = rain.slice(0, todayIdx);
    const fc = rain.slice(todayIdx);
    const r7 = Math.round(obs.reduce((a, b) => a + b, 0) * 10) / 10;
    const f5 = Math.round(fc.reduce((a, b) => a + b, 0) * 10) / 10;
    const max24Obs = rollingMaxSum(obs, 1);
    const max72Obs = rollingMaxSum(obs, 3);
    const max168Obs = rollingMaxSum(obs, 7);
    const max24Comb = rollingMaxSum(rain, 1);
    const max72Comb = rollingMaxSum(rain, 3);
    const max168Comb = rollingMaxSum(rain, 7);

    const { flNow, smNow } = extractFreezingAndSoil(it, todayIdx, todayNpt, nowHourNpt);

    nd.rain_basis = hasRainSum ? 'live_open_meteo_rain_sum' : 'live_open_meteo_precip_minus_snow';
    nd.rain_past_7d_mm = r7;
    nd.rain_next_5d_mm = f5;
    nd.max_24h_obs_mm = max24Obs;
    nd.max_72h_obs_mm = max72Obs;
    nd.max_24h_fc_mm = rollingMaxSum(fc, 1);
    nd.snow_past_7d_cm = Math.round(snow.slice(0, todayIdx).reduce((a, b) => a + b, 0) * 10) / 10;
    if (d.temperature_2m_max && d.temperature_2m_max[todayIdx] != null && Number.isFinite(Number(d.temperature_2m_max[todayIdx]))) {
      nd.temp_max_today_c = Math.round(Number(d.temperature_2m_max[todayIdx]) * 10) / 10;
    }
    nd.freezing_level_m = flNow != null ? Math.round(flNow) : null;
    nd.soil_moisture_m3m3 = smNow;
    nd.dh_obs = evaluateDahalHasegawa(max24Obs, max72Obs, max168Obs);
    nd.dh_combined = evaluateDahalHasegawa(max24Comb, max72Comb, max168Comb);
    nd.daily_time = times;
    nd.daily_precip = precip;
    nd.daily_rain = rain;
    if (times.length) lastDate = times[times.length - 1];
  });

  let lakesUpdated = false;
  let lakesCount = 0;
  if (priorityLakes.length && lakeRes.status === 'fulfilled' && Array.isArray(lakeRes.value)) {
    const lakeItems = lakeRes.value;
    lakeItems.forEach((it, idx) => {
      const lk = priorityLakes[idx];
      if (!lk || !it || !it.daily) return;
      const d = it.daily;
      const times = Array.isArray(d.time) ? d.time : [];
      const foundDay = times.indexOf(todayNpt);
      const todayIdx = foundDay >= 0 ? foundDay : Math.min(7, Math.max(0, times.length - 1));
      const precip = (d.precipitation_sum || []).map(v => Math.max(0, Number(v) || 0));
      const snow = (d.snowfall_sum || []).map(v => Math.max(0, Number(v) || 0));
      const hasRainSum = Array.isArray(d.rain_sum) && d.rain_sum.some(v => v != null && Number.isFinite(Number(v)));
      const rain = hasRainSum
        ? d.rain_sum.map(v => Math.max(0, Number(v) || 0))
        : precip.map((pr, i) => Math.max(0, pr - (snow[i] || 0)));

      const { flNow, flMax } = extractFreezingAndSoil(it, todayIdx, todayNpt, nowHourNpt);

      lk.precip_past_7d_mm = Math.round(precip.slice(0, todayIdx).reduce((a, b) => a + b, 0) * 10) / 10;
      lk.precip_next_5d_mm = Math.round(precip.slice(todayIdx).reduce((a, b) => a + b, 0) * 10) / 10;
      lk.liquid_rain_12d_mm = Math.round(rain.reduce((a, b) => a + b, 0) * 10) / 10;
      lk.snowfall_12d_cm = Math.round(snow.reduce((a, b) => a + b, 0) * 10) / 10;
      lk.freezing_level_now_m = flNow;
      lk.freezing_level_max_m = flMax;
      if (flMax != null && lk.z_m != null && Number.isFinite(Number(lk.z_m))) {
        lk.freezing_margin_m = Math.round((flMax - Number(lk.z_m)) * 10) / 10;
        lk.warm_rain_on_ice = lk.liquid_rain_12d_mm >= 10.0 && lk.freezing_margin_m >= 300.0;
      } else {
        lk.freezing_margin_m = null;
        lk.warm_rain_on_ice = false;
      }
      S.hmLakeById[lk.id] = lk;
      lakesCount += 1;
    });
    if (lakesCount > 0) {
      lakesUpdated = true;
      S.hydromet.priority_lakes_updated_utc = nowIso;
    }
  }
  if (!lakesUpdated && prevLakesUpdatedUtc) {
    S.hydromet.priority_lakes_updated_utc = prevLakesUpdatedUtc;
  }

  S.hydromet.updated_utc = nowIso;
  S.hydromet.nodes_updated_utc = nowIso;
  S.hydromet.mode = 'live_browser';
  if (lastDate) S.hydromet.forecast_expires_utc = `${lastDate}T23:59:59Z`;
  return { ok: true, count: items.length, lakesCount, lakesUpdated };
}

async function refreshAllLiveInBrowser() {
  const btn = document.getElementById('btnRefreshLive');
  btn.textContent = t('btnRefreshing');
  btn.disabled = true;

  try {
    const [rEq, rFl, rHm] = await Promise.allSettled([
      loadEq(true),
      refreshLiveGlofas(),
      refreshLiveHydromet(),
    ]);

    const parts = [];
    if (rEq.status === 'fulfilled' && rEq.value && rEq.value.ok) {
      parts.push(`USGS (${rEq.value.count} quakes) ✓`);
    } else {
      const msg = rEq.status === 'rejected' ? rEq.reason.message : (rEq.value && rEq.value.error) || 'offline';
      parts.push(`USGS ✕ (${msg})`);
    }
    if (rFl.status === 'fulfilled' && rFl.value && rFl.value.ok) {
      parts.push(`GloFAS (${rFl.value.count} basins) ✓`);
    } else {
      const msg = rFl.status === 'rejected' ? rFl.reason.message : 'offline';
      parts.push(`GloFAS ✕ (${msg})`);
    }
    const lakesRefreshed = rHm.status === 'fulfilled' && rHm.value && rHm.value.lakesUpdated;
    if (rHm.status === 'fulfilled' && rHm.value && rHm.value.ok) {
      const lakeSuffix = lakesRefreshed ? `, ${rHm.value.lakesCount} lakes` : ', lakes cached';
      parts.push(`Hydromet (${rHm.value.count} nodes${lakeSuffix}) ✓`);
    } else {
      const msg = rHm.status === 'rejected' ? rHm.reason.message : 'offline';
      parts.push(`Hydromet ✕ (${msg})`);
    }

    updateStatusPills();
    drawRiversLayer();
    if (document.getElementById('lNodes').checked) drawNodesLayer();

    // Refresh active inspector/tab without clobbering unrelated tabs
    if (S.selKind === 'river' && S.sel) selectRiver(S.sel, false);
    else if (S.selKind === 'node' && S.sel) selectNode(S.sel, false);
    else if (S.selKind === 'district' && S.selDistrict) renderDistrictByName(S.selDistrict, false);

    if (['floods', 'landslides', 'live'].includes(S.tab) || (S.tab === 'sat' && lakesRefreshed)) {
      renderTab();
    }

    setToast(`Live refresh (${fmtNpt(Date.now())}): ${parts.join(' · ')}`);
  } finally {
    btn.textContent = t('btnRefreshLive');
    btn.disabled = false;
  }
}

/* ==========================================================================
   11. Mobile Drawer Switching & Right Inspector Helpers
   ========================================================================== */
function setMobilePane(pane) {
  const app = document.getElementById('app');
  if (app) app.setAttribute('data-mobile-pane', pane);
  document.querySelectorAll('#mobileTabs button[data-mobile-tab]').forEach(btn => {
    btn.setAttribute('aria-selected', btn.dataset.mobileTab === pane ? 'true' : 'false');
  });
}

function ensureRightVisible() {
  const m = document.getElementById('mainGrid');
  if (m && m.classList.contains('hide-right')) {
    m.classList.remove('hide-right');
    const btn = document.getElementById('btnToggleRight');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    setTimeout(() => map.invalidateSize(), 180);
  }
  if (window.matchMedia('(max-width: 760px)').matches) {
    setMobilePane('detail');
  }
}

/* ==========================================================================
   11b. Official Nepal Authority Separation Panel (NDRRMA BIPAD · DHM · NSC)
   ========================================================================== */
function matchDistrictRecord(rec, dist, cLon, cLat) {
  if (!dist || !rec) return true;
  if (rec.lat != null && rec.lon != null && Number.isFinite(Number(rec.lat)) && Number.isFinite(Number(rec.lon))) {
    if (hav(cLon, cLat, Number(rec.lon), Number(rec.lat)) <= 60) return true;
  }
  const hay = `${rec.title || ''} ${rec.titleNe || ''} ${rec.address || ''} ${rec.description || ''} ${rec.streetAddress || ''} ${typeof rec.district === 'string' ? rec.district : ''}`.toLowerCase();
  const enMatch = dist.name && hay.includes(dist.name.toLowerCase());
  const neMatch = dist.name_ne && hay.includes(dist.name_ne.toLowerCase());
  return Boolean(enMatch || neMatch);
}

function renderOfficialAuthorityPanel(opts = {}) {
  const compact = Boolean(opts.compact);
  const dist = opts.dist || null;
  const cLon = opts.cLon ?? 84.2;
  const cLat = opts.cLat ?? 28.3;
  const isNe = getLang() === 'ne';

  const bp = S.bipad;
  const prov = (bp && bp.provenance) || {};
  const dClass = prov.data_class || (S.summary && S.summary.bipad_official && S.summary.bipad_official.data_class) || 'unavailable';
  const status = prov.status || (S.summary && S.summary.bipad_official && S.summary.bipad_official.status) || 'unavailable';
  const retrievedAt = prov.retrieved_at_utc || (S.summary && S.summary.bipad_official && S.summary.bipad_official.retrieved_at_utc) || null;
  const obsAt = prov.observation_time_utc || null;

  const allAlerts = (bp && Array.isArray(bp.alerts)) ? bp.alerts : [];
  const allIncidents = (bp && Array.isArray(bp.landslide_incidents)) ? bp.landslide_incidents : [];
  const allRivers = (bp && Array.isArray(bp.dhm_rivers)) ? bp.dhm_rivers : [];
  const allRain = (bp && Array.isArray(bp.dhm_rain)) ? bp.dhm_rain : [];
  const allQuakes = (bp && Array.isArray(bp.nsc_earthquakes)) ? bp.nsc_earthquakes : [];

  const alerts = dist ? allAlerts.filter(r => matchDistrictRecord(r, dist, cLon, cLat)) : allAlerts;
  const incidents = dist ? allIncidents.filter(r => matchDistrictRecord(r, dist, cLon, cLat)) : allIncidents;
  const rivers = dist ? allRivers.filter(r => matchDistrictRecord(r, dist, cLon, cLat)) : allRivers;
  const rain = dist ? allRain.filter(r => matchDistrictRecord(r, dist, cLon, cLat)) : allRain;
  const quakes = dist ? allQuakes.filter(r => matchDistrictRecord(r, dist, cLon, cLat)) : allQuakes;

  const totalNational = allAlerts.length + allIncidents.length + allRivers.length + allRain.length + allQuakes.length;
  const isUnavailable = !bp || status === 'unavailable' || totalNational === 0;

  let bodyHtml = '';
  if (isUnavailable) {
    bodyHtml = `
      <div class="official-offline-box">
        <div><b>${esc(t('bipadAwaitingRefresh'))}</b> ${badgeSla(status)}</div>
        <div class="muted field-gap">${esc(prov.notes || (isNe ? 'प्रत्यक्ष BIPAD API स्न्यापसट उपलब्ध नभएकाले आधिकारिक पोर्टलहरू सिधै हेर्नुहोस्।' : 'No live cached BIPAD snapshot is bundled in this offline build. Always verify live statutory warnings directly on official portals:'))}</div>
        <div class="btn-row">
          <a class="btn sm" href="https://bipadportal.gov.np/" target="_blank" rel="noopener noreferrer">NDRRMA BIPAD ↗</a>
          <a class="btn sm" href="https://hydrology.gov.np/" target="_blank" rel="noopener noreferrer">DHM Floods ↗</a>
          <a class="btn sm" href="https://seismonepal.gov.np/" target="_blank" rel="noopener noreferrer">DMG / NEMRC ↗</a>
        </div>
      </div>`;
  } else if (compact) {
    const localCount = alerts.length + incidents.length + rivers.length + rain.length + quakes.length;
    const summaryRow = localCount > 0
      ? `<div class="kv">
          <span>${esc(t('bipadAlertsHead'))}</span><b>${fmt(alerts.length)}</b>
          <span>${esc(t('bipadRiversHead'))} / ${esc(t('bipadRainHead'))}</span><b>${fmt(rivers.length)} / ${fmt(rain.length)}</b>
          <span>${esc(t('bipadEqHead'))}</span><b>${fmt(quakes.length)}</b>
          <span>${esc(t('bipadLsHead'))}</span><b>${fmt(incidents.length)}</b>
        </div>`
      : `<p class="muted">${isNe ? `यस जिल्ला नजिक ० BIPAD अभिलेख (राष्ट्रिय कुल: ${fmt(totalNational)} अभिलेख)।` : `0 matched BIPAD records within 60 km of this district (${fmt(totalNational)} national records cached).`}</p>`;

    const topAlertItems = alerts.slice(0, 3).map(a => {
      const ttl = (isNe && a.titleNe) ? a.titleNe : (a.title || a.titleNe || 'BIPAD Alert');
      return `<li><b>${esc(ttl)}</b>${a.source ? ` <span class="band">(${esc(String(a.source).toUpperCase())})</span>` : ''} — ${esc(fmtNpt(a.startedOn))}</li>`;
    }).join('');
    const topIncItems = incidents.slice(0, 3).map(inc => {
      const ttl = (isNe && inc.titleNe) ? inc.titleNe : (inc.title || inc.titleNe || 'Landslide incident');
      return `<li><b>${esc(ttl)}</b> — ${fmtNullDate(inc.incidentOn || inc.date)} · ${isNe ? 'मृत्यु' : 'Deaths'}: ${fmtNullCount(inc.peopleDeathCount)}</li>`;
    }).join('');
    bodyHtml = `
      ${summaryRow}
      ${topAlertItems ? `<ul class="trig-list">${topAlertItems}</ul>` : ''}
      ${topIncItems ? `<ul class="trig-list">${topIncItems}</ul>` : ''}
      <div class="btn-row">
        <a class="btn sm" href="https://bipadportal.gov.np/" target="_blank" rel="noopener noreferrer">BIPAD Portal ↗</a>
        <a class="btn sm" href="https://hydrology.gov.np/" target="_blank" rel="noopener noreferrer">DHM ↗</a>
        <a class="btn sm" href="https://seismonepal.gov.np/" target="_blank" rel="noopener noreferrer">NSC ↗</a>
      </div>`;
  } else {
    const alertRows = alerts.slice(0, 12).map(a => {
      const ttl = (isNe && a.titleNe) ? a.titleNe : (a.title || a.titleNe || 'BIPAD Alert');
      const fly = safeFlyAttr(a.lat, a.lon, 10);
      return `<tr tabindex="0" ${fly ? `data-fly="${fly}"` : ''}>
        <td class="wrap-cell"><b>${esc(ttl)}</b>${a.description ? `<div class="band">${esc(a.description)}</div>` : ''}</td>
        <td>${esc(a.source ? String(a.source).toUpperCase() : 'BIPAD')}${a.verified === true ? ' <span class="hbadge h-low">✓</span>' : ''}</td>
        <td class="mono">${esc(fmtNpt(a.startedOn))}</td>
      </tr>`;
    }).join('');

    const riverRows = rivers.slice(0, 12).map(rv => {
      const fly = safeFlyAttr(rv.lat, rv.lon, 10);
      return `<tr tabindex="0" ${fly ? `data-fly="${fly}"` : ''}>
        <td><b>${esc(rv.title || 'DHM station')}</b> <span class="band">${esc(rv.basin || '')}</span></td>
        <td class="num"><b>${rv.waterLevel != null ? fmt(rv.waterLevel, 2) + ' m' : esc(t('unknownVal'))}</b></td>
        <td class="num">${rv.warningLevel != null ? fmt(rv.warningLevel, 1) : '—'} / ${rv.dangerLevel != null ? fmt(rv.dangerLevel, 1) : '—'}</td>
        <td>${esc(rv.status || '—')}</td>
        <td class="mono">${esc(fmtNpt(rv.waterLevelOn))}</td>
      </tr>`;
    }).join('');

    const rainRows = rain.slice(0, 12).map(rn => {
      const fly = safeFlyAttr(rn.lat, rn.lon, 10);
      return `<tr tabindex="0" ${fly ? `data-fly="${fly}"` : ''}>
        <td><b>${esc(rn.title || 'DHM rain gauge')}</b> <span class="band">${esc(rn.basin || '')}</span></td>
        <td class="num">${rn.rain_1h_mm != null ? fmt(rn.rain_1h_mm, 1) : '—'}</td>
        <td class="num">${rn.rain_3h_mm != null ? fmt(rn.rain_3h_mm, 1) : '—'}</td>
        <td class="num"><b>${rn.rain_24h_mm != null ? fmt(rn.rain_24h_mm, 1) : '—'}</b></td>
        <td class="mono">${esc(fmtNpt(rn.measuredOn))}</td>
      </tr>`;
    }).join('');

    const nscRows = quakes.slice(0, 12).map(q => {
      const fly = safeFlyAttr(q.lat, q.lon, 9);
      return `<tr tabindex="0" ${fly ? `data-fly="${fly}"` : ''}>
        <td class="mono">${esc(fmtNpt(q.eventOn))}</td>
        <td class="num"><b>ML ${q.magnitude != null ? fmt(q.magnitude, 1) : '—'}</b></td>
        <td class="wrap-cell">${esc(q.address || q.description || 'Nepal')}</td>
      </tr>`;
    }).join('');

    const lsRows = incidents.slice(0, 12).map(inc => {
      const ttl = (isNe && inc.titleNe) ? inc.titleNe : (inc.title || inc.titleNe || 'BIPAD Landslide');
      const fly = safeFlyAttr(inc.lat, inc.lon, 11);
      return `<tr tabindex="0" ${fly ? `data-fly="${fly}"` : ''}>
        <td class="mono">${fmtNullDate(inc.incidentOn || inc.date)}</td>
        <td class="wrap-cell"><b>${esc(ttl)}</b>${inc.verified === true ? ' <span class="hbadge h-low">Verified</span>' : ''}</td>
        <td class="num">${fmtNullCount(inc.peopleDeathCount)}</td>
        <td class="num">${fmtNullCount(inc.peopleInjuredCount)}</td>
      </tr>`;
    }).join('');

    bodyHtml = `
      <div class="official-grid">
        <div class="official-subcard">
          <h5><span>${esc(t('bipadAlertsHead'))}</span><span class="mono">${fmt(alerts.length)}</span></h5>
          ${alertRows
            ? `<div class="tbl-scroll"><table><thead><tr><th scope="col">Alert</th><th scope="col">Agency</th><th scope="col">Started (NPT)</th></tr></thead><tbody>${alertRows}</tbody></table></div>`
            : '<p class="muted">0 alerts in current BIPAD snapshot.</p>'}
        </div>
        <div class="official-subcard">
          <h5><span>${esc(t('bipadEqHead'))}</span><span class="mono">${fmt(quakes.length)}</span></h5>
          ${nscRows
            ? `<div class="tbl-scroll"><table><thead><tr><th scope="col">Time (NPT)</th><th scope="col">ML</th><th scope="col">Epicentre</th></tr></thead><tbody>${nscRows}</tbody></table></div>`
            : '<p class="muted">0 NSC earthquake bulletins in current BIPAD snapshot.</p>'}
        </div>
        <div class="official-subcard">
          <h5><span>${esc(t('bipadRiversHead'))}</span><span class="mono">${fmt(rivers.length)}</span></h5>
          ${riverRows
            ? `<div class="tbl-scroll"><table><thead><tr><th scope="col">Station</th><th scope="col">Level</th><th scope="col">Warn/Dang</th><th scope="col">Status</th><th scope="col">NPT</th></tr></thead><tbody>${riverRows}</tbody></table></div>`
            : '<p class="muted">0 active DHM river readings in current BIPAD snapshot.</p>'}
        </div>
        <div class="official-subcard">
          <h5><span>${esc(t('bipadRainHead'))}</span><span class="mono">${fmt(rain.length)}</span></h5>
          ${rainRows
            ? `<div class="tbl-scroll"><table><thead><tr><th scope="col">Gauge</th><th scope="col">1h</th><th scope="col">3h</th><th scope="col">24h mm</th><th scope="col">NPT</th></tr></thead><tbody>${rainRows}</tbody></table></div>`
            : '<p class="muted">0 DHM rain gauge readings in current BIPAD snapshot.</p>'}
        </div>
      </div>
      <div class="official-subcard field-gap">
        <h5><span>${esc(t('bipadLsHead'))}</span><span class="mono">${fmt(incidents.length)}</span></h5>
        ${lsRows
          ? `<div class="tbl-scroll"><table><thead><tr><th scope="col">Date</th><th scope="col">Incident</th><th scope="col">Deaths</th><th scope="col">Injured</th></tr></thead><tbody>${lsRows}</tbody></table></div>`
          : '<p class="muted">0 dated BIPAD landslide incidents in current snapshot.</p>'}
      </div>`;
  }

  return `
    <section class="official-lane${compact ? ' official-lane-compact' : ''}" aria-label="${esc(t('officialLaneTitle'))}">
      <div class="official-lane-head">
        <div class="official-lane-title">
          <span class="badge-official">${esc(t('officialBadge'))}</span>
          <span>${esc(t('officialLaneTitle'))}</span>
        </div>
        <div class="badge-row">
          ${badgeDataClass(dClass)}
          <span class="band mono">${esc(obsAt ? fmtNpt(obsAt) : fmtNpt(retrievedAt))}</span>
        </div>
      </div>
      <div class="muted">${esc(isNe ? t('officialNotice') : ((bp && bp.official_notice) || t('officialNotice')))}</div>
      ${bodyHtml}
    </section>`;
}

/* ==========================================================================
   12. 77-District & "Near Me" Cross-Hazard Triage
   ========================================================================== */
function clearDistrictHighlight() {
  S.selDistrict = null;
  S.userCoords = null;
  gDistrict.clearLayers();
  document.getElementById('fDistrict').value = '';
  document.getElementById('btnClearDistrict').classList.add('is-hidden');
  document.getElementById('geoStatus').textContent = '';
}

async function selectDistrict(distName, fly = true, userCoords = null) {
  const dist = S.districts.find(d => d.name === distName);
  if (!dist) return;
  const prevLakeId = S.selKind === 'lake' ? S.sel : null;
  S.sel = dist.name;
  S.selKind = 'district';
  S.selDistrict = dist.name;
  if (userCoords) S.userCoords = userCoords;
  if (prevLakeId) updateLakeSelectionStyle(prevLakeId, null);

  document.getElementById('fDistrict').value = dist.name;
  document.getElementById('btnClearDistrict').classList.remove('is-hidden');
  ensureRightVisible();

  gDistrict.clearLayers();
  if (Array.isArray(dist.bbox) && dist.bbox.length === 4) {
    const [w, s, e, n] = dist.bbox;
    const bounds = [[s, w], [n, e]];
    L.rectangle(bounds, {
      color: '#56ccf2',
      weight: 2.2,
      dashArray: '6 4',
      fillColor: '#56ccf2',
      fillOpacity: 0.08,
    }).addTo(gDistrict);
    if (fly) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 10 });
  } else if (fly && Array.isArray(dist.centroid)) {
    map.setView([dist.centroid[1], dist.centroid[0]], 10);
  }

  if (S.userCoords) {
    L.circleMarker([S.userCoords.lat, S.userCoords.lon], {
      radius: 7,
      color: '#ffffff',
      weight: 2,
      fillColor: '#0284c7',
      fillOpacity: 0.95,
    }).bindTooltip('Your location / तपाईँको स्थान').addTo(gDistrict);
  }

  // Ensure lightweight GDACS, historical M>=6, official BIPAD & isolation screening data are ready
  await Promise.allSettled([
    ensureData('gdacs_alerts'),
    ensureData('eq_history_m6'),
    ensureData('bipad_official'),
    ensureData('exposure_isolation'),
  ]);
  if (S.selKind === 'district' && S.selDistrict === dist.name) {
    renderDistrictByName(dist.name, false);
  }
}

function renderDistrictByName(distName) {
  const dist = S.districts.find(d => d.name === distName);
  if (!dist) return;
  const el = document.getElementById('detailBody');
  const [cLon, cLat] = dist.centroid || [84.2, 28.3];

  const basin = S.rivers.find(b => b.id === dist.nearest_river_basin);
  const bSt = basin ? riverHeadlineStatus(basin) : 'unassessed';

  const node = ((S.hydromet && S.hydromet.nodes) || []).find(n => n.id === dist.nearest_sentinel_node);
  const ndDh = node ? (node.dh_combined || node.dh_obs || {}) : {};
  const ndLv = ndDh.level || 'low';

  const eq100 = S.live.filter(f => {
    const c = f.geometry && f.geometry.coordinates;
    return c && hav(cLon, cLat, c[0], c[1]) <= 100;
  });

  const histM6Near = (S.eqHist || [])
    .map(e => ({ e, km: hav(cLon, cLat, e.lon, e.lat) }))
    .filter(x => x.km <= 120)
    .sort((a, b) => a.km - b.km)
    .slice(0, 3);

  const routedPrioLakes = (dist.routed_priority_lake_ids || [])
    .map(id => S.lakeById.get(id))
    .filter(Boolean);
  const insidePrioLakes = (dist.priority_lake_ids || [])
    .map(id => S.lakeById.get(id))
    .filter(Boolean);
  const allAffectedPrio = Array.from(new Map(
    [...insidePrioLakes, ...routedPrioLakes].map(f => [f.properties.id, f])
  ).values());

  const gdacsList = S.gdacs || [];
  const gdacsNepal = gdacsList.filter(a => a.in_nepal);
  const isoDist = (S.exposureIso && Array.isArray(S.exposureIso.districts))
    ? S.exposureIso.districts.find(d => d.name === dist.name)
    : null;
  const isoRiskCls = isoDist
    ? (isoDist.district_isolation_risk === 'high' ? 'h-vhigh' : isoDist.district_isolation_risk === 'moderate' ? 'h-mod' : isoDist.district_isolation_risk === 'low' ? 'h-low' : 'h-na')
    : 'h-na';

  const distLabel = getLang() === 'ne'
    ? `${dist.name_ne || dist.name} (${dist.name})`
    : `${dist.name} (${dist.name_ne || ''})`;
  const provLabel = getLang() === 'ne'
    ? `${dist.prov_ne || dist.prov}`
    : `${dist.prov} · ${dist.prov_ne || ''}`;

  el.innerHTML = `
    <div class="detail-head">
      <div>
        <h2>${esc(distLabel)}</h2>
        <div class="muted">${esc(provLabel)} · ${cLat.toFixed(2)}°N, ${cLon.toFixed(2)}°E</div>
      </div>
      <button type="button" class="btn sm" id="btnDistrictBack">✕</button>
    </div>

    <div class="badge-row">
      <span class="hbadge h-info">${esc(t('distBriefTitle'))}</span>
      <span class="hbadge ${FCLASS[bSt] || 'h-na'}">River: ${esc(tRiverStatus(bSt))}</span>
      <span class="hbadge ${DHCLASS[ndLv] || 'h-low'}">Rain-LS: ${esc(tDhLevel(ndLv))}</span>
      ${isoDist ? `<span class="hbadge ${isoRiskCls}">Isolation: ${esc(isoDist.district_isolation_risk)}</span>` : ''}
    </div>

    ${renderOfficialAuthorityPanel({ compact: true, dist, cLon, cLat })}

    <div class="district-section">
      <div class="district-section-head">
        <span>■ ${esc(t('distRiverSec'))} <span class="badge-screening">${esc(t('modelledBadge'))}</span></span>
        ${basin ? `<span class="hbadge ${FCLASS[bSt] || 'h-na'}">${esc(tRiverStatus(bSt))}</span>` : ''}
      </div>
      ${basin ? `
        <div class="kv">
          <span>${esc(getLang() === 'ne' && basin.name_ne ? basin.name_ne : basin.name)} (${fmt(dist.nearest_river_km, 1)} km)</span>
          <b>${fmt(basin.current_m3s, 1)} m³/s</b>
          <span>14d median / p75 peak</span>
          <b>${fmt(basin.peak_14d_median_m3s, 1)} / ${fmt(basin.peak_14d_p75_m3s, 1)} m³/s</b>
        </div>
        ${basin.grid_snap_warning ? `<div class="band text-warn">⚠ Cached off-mainstem grid cell; verify live DHM gauge (${esc(basin.dhm_ref || 'hydrology.gov.np')}).</div>` : ''}
        <div class="btn-row"><button type="button" class="btn sm pri" data-open-river="${esc(basin.id)}">${esc(t('distInspectRiver'))}</button></div>
      ` : '<p class="muted">No GloFAS basin matched.</p>'}
    </div>

    <div class="district-section">
      <div class="district-section-head">
        <span>▲ ${esc(t('distRainSec'))}</span>
        <span class="hbadge ${DHCLASS[ndLv] || 'h-low'}">${esc(tDhLevel(ndLv))} (${fmt((ndDh.max_ratio || 0) * 100, 0)}%)</span>
      </div>
      ${node ? `
        <div class="kv">
          <span>${esc(node.name)} (${fmt(dist.nearest_sentinel_km, 1)} km)</span>
          <b>${fmt(node.rain_past_7d_mm, 1)} mm (7d)</b>
          <span>Next 5d forecast / soil moisture</span>
          <b>${fmt(node.rain_next_5d_mm, 1)} mm · ${fmt(node.soil_moisture_m3m3, 2)}</b>
          <span>OSM mapped landslide scars in district</span>
          <b>${fmt(dist.n_landslide_records)}</b>
        </div>
        <div class="btn-row"><button type="button" class="btn sm pri" data-open-node="${esc(node.id)}">${esc(t('distInspectNode'))}</button></div>
      ` : '<p class="muted">No sentinel node matched.</p>'}
    </div>

    <div class="district-section">
      <div class="district-section-head">
        <span>◎ ${esc(t('distEqSec'))}</span>
        <span class="mono">${fmt(eq100.length)} (${esc(S.eqWindow)})</span>
      </div>
      ${eq100.length ? `<ul class="trig-list">${eq100.slice(0, 5).map(q => {
        const p = q.properties || {};
        return `<li><b>M ${fmt(p.mag, 1)}</b> ${esc(p.place || '')} — ${esc(fmtNpt(p.time))} (${esc(fmtAge(p.time))})</li>`;
      }).join('')}</ul>` : `<p class="muted">${esc(t('distNoEq100'))}</p>`}
      ${histM6Near.length ? `<div class="band">Historical M≥6 nearby: ${histM6Near.map(x => `M${fmt(x.e.mag, 1)} (${new Date(x.e.time).getUTCFullYear()}, ${fmt(x.km, 0)} km)`).join(' · ')}</div>` : ''}
    </div>

    <div class="district-section">
      <div class="district-section-head">
        <span>◆ ${esc(t('distLakeSec'))}</span>
        <span class="mono">${fmt(dist.n_lakes)} lakes · ${fmt(dist.n_routed_corridors)} paths</span>
      </div>
      ${dist.n_lakes === 0
        ? `<p class="muted">${esc(t('distNoLakesInside'))}</p>`
        : `<div class="kv">
            <span>Glacial lakes inside district</span><b>${fmt(dist.n_lakes)} (${fmt(dist.n_priority_lakes)} priority)</b>
            <span>Upstream GLOF paths traversing district</span><b>${fmt(dist.n_routed_corridors)}</b>
          </div>`
      }
      ${allAffectedPrio.length ? `
        <div class="quick-list field-gap">
          ${allAffectedPrio.slice(0, 6).map(f => {
            const p = f.properties;
            return `<button type="button" class="quick-card" data-open-lake="${esc(p.id)}">
              <div class="quick-card-top">
                <b>${esc(p.name || p.id)}</b>
                <span class="mono quick-card-val">${fmt(p.pfv_Mm3, 1)} Mm³</span>
              </div>
              <div class="band">Qp ≈ ${fmt(p.qp_m3s)} m³/s · ≤1 km: ${fmt(p.pop_high)} people · ${fmt(p.n_settlements)} places · ${fmt(p.n_health)} clinics · ${fmt(p.n_hydropower)} hydro</div>
            </button>`;
          }).join('')}
        </div>
      ` : ''}
      ${dist.n_lakes > 0 ? `<div class="btn-row"><button type="button" class="btn sm" id="btnFilterToDistrict">${esc(t('distFilterLakes'))}</button></div>` : ''}
    </div>

    ${isoDist ? `
    <div class="district-section">
      <div class="district-section-head">
        <span>⛓ ${esc(t('isoSectionTitle'))} <span class="badge-screening">${esc(t('screeningBadge'))}</span></span>
        <span class="hbadge ${isoRiskCls}">${esc(isoDist.district_isolation_risk)}</span>
      </div>
      <div class="band">${esc(t('isoCorridorBadge'))}</div>
      <div class="kv field-gap">
        <span>Bridges at corridor crossings (vehicular)</span><b>${fmt(isoDist.unique_bridges_at_crossings)} (${fmt(isoDist.unique_vehicular_bridges_at_crossings)})</b>
        <span>Settlements potentially isolated</span><b>${fmt(isoDist.unique_settlements_potentially_isolated)} / ${fmt(isoDist.unique_settlements_in_1km_corridors)}</b>
        <span>Nearest hospital (median / max)</span><b>${isoDist.nearest_hospital_km != null ? `${fmt(isoDist.nearest_hospital_km, 1)} / ${fmt(isoDist.nearest_hospital_max_km, 1)} km` : '—'}</b>
        <span>Hydropower MW in 1 km corridors</span><b>${fmt(isoDist.hydropower_mw_exposed, 1)} MW</b>
      </div>
      <div class="btn-row"><button type="button" class="btn sm pri" id="btnOpenCascadesFromDist">${esc(t('tabCascades'))} →</button></div>
    </div>` : ''}

    <div class="district-section">
      <div class="district-section-head">
        <span>⬡ ${esc(t('distGdacsSec'))}</span>
        <span class="mono">${fmt(gdacsNepal.length)} in Nepal / ${fmt(gdacsList.length)} regional</span>
      </div>
      ${gdacsNepal.length
        ? `<ul class="trig-list">${gdacsNepal.map(a => `<li><b>${esc(a.type)} (${esc(a.alert_level)})</b> ${esc(a.name)} · ${esc(a.from_date)}</li>`).join('')}</ul>`
        : `<p class="muted">0 active GDACS alerts inside Nepal (${fmt(gdacsList.length)} regional events cached ${esc(fmtAge(S.gdacsMeta && S.gdacsMeta.updated_utc))}).</p>`}
    </div>

    <div class="btn-row">
      <button type="button" class="btn sm emerg" id="btnDistrictEmerg">${esc(t('btnEmergency'))}</button>
    </div>
  `;

  const backBtn = el.querySelector('#btnDistrictBack');
  if (backBtn) backBtn.addEventListener('click', () => { clearDistrictHighlight(); renderDefaultInspector(); });

  const filtBtn = el.querySelector('#btnFilterToDistrict');
  if (filtBtn) {
    filtBtn.addEventListener('click', () => {
      document.getElementById('fSearch').value = dist.name;
      refresh();
    });
  }

  const emBtn = el.querySelector('#btnDistrictEmerg');
  if (emBtn) emBtn.addEventListener('click', openEmergencyModal);

  const cascDistBtn = el.querySelector('#btnOpenCascadesFromDist');
  if (cascDistBtn) cascDistBtn.addEventListener('click', () => switchTab('cascades'));

  el.querySelectorAll('[data-open-river]').forEach(btn => {
    btn.addEventListener('click', () => selectRiver(btn.dataset.openRiver, true));
  });
  el.querySelectorAll('[data-open-node]').forEach(btn => {
    btn.addEventListener('click', () => selectNode(btn.dataset.openNode, true));
  });
  el.querySelectorAll('[data-open-lake]').forEach(btn => {
    btn.addEventListener('click', () => selectLake(btn.dataset.openLake, true));
  });
}

function locateNearMe() {
  const statusEl = document.getElementById('geoStatus');
  const btn = document.getElementById('btnNearMe');
  if (!navigator.geolocation) {
    statusEl.textContent = t('triageGeoUnsupported');
    return;
  }
  btn.disabled = true;
  btn.textContent = t('triageNearMeBusy');
  statusEl.textContent = '';

  navigator.geolocation.getCurrentPosition(
    pos => {
      btn.disabled = false;
      btn.textContent = t('triageNearMe');
      const { latitude: lat, longitude: lon } = pos.coords;
      const inNepal = lat >= 26.2 && lat <= 30.6 && lon >= 79.9 && lon <= 88.3;
      let best = null;
      let bestKm = Infinity;
      S.districts.forEach(d => {
        if (!Array.isArray(d.centroid)) return;
        const km = hav(lon, lat, d.centroid[0], d.centroid[1]);
        if (km < bestKm) {
          bestKm = km;
          best = d;
        }
      });
      if (best) {
        statusEl.textContent = inNepal
          ? `${tDistrict(best.name, S.districtsMeta)} (~${fmt(bestKm, 0)} km from centroid)`
          : `${t('triageOutsideNepal')} ${tDistrict(best.name, S.districtsMeta)} (${fmt(bestKm, 0)} km)`;
        selectDistrict(best.name, true, { lat, lon });
      }
    },
    () => {
      btn.disabled = false;
      btn.textContent = t('triageNearMe');
      statusEl.textContent = t('triageGeoDenied');
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 180000 }
  );
}

/* ==========================================================================
   13. Default, Lake, River & Rainfall Node Inspectors
   ========================================================================== */
function renderDefaultInspector() {
  const el = document.getElementById('detailBody');
  const pri = S.lakes
    .filter(f => f.properties.priority)
    .sort((a, b) => (b.properties.pfv_Mm3 || 0) - (a.properties.pfv_Mm3 || 0));

  el.innerHTML = `
    <h2>Multi-Hazard Inspector</h2>
    <p class="muted field-gap">Choose any of <b>77 Nepal districts</b> in <b>My District / मेरो जिल्ला</b>, or click a <b>glacial lake</b>, <b>GloFAS river station</b>, or <b>rainfall–landslide node</b> on the map or tables below.</p>

    <section class="blk field-gap">
      <h3>Top priority glacial lakes (PFV ≥ 10 Mm³)</h3>
      <div class="quick-list">
        ${pri.slice(0, 8).map((f, idx) => {
          const p = f.properties;
          return `<button type="button" class="quick-card" data-open-lake="${esc(p.id)}">
            <div class="quick-card-top">
              <b>#${idx + 1} ${esc(p.name || p.id)}</b>
              <span class="mono quick-card-val">${fmt(p.pfv_Mm3, 1)} Mm³</span>
            </div>
            <div class="band">${esc(tDistrict(p.district, S.districtsMeta))} · ${fmt(p.z)} m · Qp ≈ ${fmt(p.qp_m3s)} m³/s · pop ≤1 km: ${fmt(p.pop_high)}</div>
          </button>`;
        }).join('')}
      </div>
    </section>

    <section class="blk">
      <h3>Snapshot &amp; refresh telemetry (NPT, UTC+05:45)</h3>
      <div class="kv">
        <span>Pipeline build</span><b>${esc(fmtNpt(S.summary && S.summary.build))}</b>
        <span>GloFAS river watch</span><b>${esc(fmtNpt(S.riversMeta && S.riversMeta.updated_utc))}</b>
        <span>Hydromet / rainfall</span><b>${esc(fmtNpt(S.hydromet && S.hydromet.updated_utc))}</b>
        <span>Scheduled cadence</span><b>${esc((S.summary && S.summary.schedule_npt) || 'Weekly Mondays 09:00 NPT')}</b>
      </div>
    </section>`;

  el.querySelectorAll('[data-open-lake]').forEach(btn => {
    btn.addEventListener('click', () => selectLake(btn.dataset.openLake, true));
  });
}

function travelText(km) {
  const vs = (S.summary && S.summary.thresholds && S.summary.thresholds.front_velocity_ms) || [2, 5, 10];
  const fmtDur = v => {
    const m = (km * 1000) / v / 60;
    return m < 90 ? `${m.toFixed(0)} min` : `${(m / 60).toFixed(1)} h`;
  };
  return `${fmtDur(vs[vs.length - 1])}–${fmtDur(vs[0])} (${fmtDur(vs[1])})`;
}

async function selectLake(id, fly) {
  const f = S.lakeById.get(id);
  if (!f) return;
  const prevId = S.selKind === 'lake' ? S.sel : null;
  S.sel = id;
  S.selKind = 'lake';
  ensureRightVisible();
  updateLakeSelectionStyle(prevId, id);

  try { history.replaceState(null, '', `#lake=${encodeURIComponent(id)}`); } catch { /* ignore */ }

  const p = f.properties;
  if (fly) {
    const b = L.geoJSON(f).getBounds();
    map.fitBounds(b, { padding: [48, 48], maxZoom: 12 });
  }

  // Render immediate details while lazy-fetching routes & exposure if routed
  renderLakeDetail(p, S.routes ? S.routes[id] : null, f, p.route_km > 0 && !S.routes);

  if (p.route_km > 0) {
    try {
      await Promise.all([ensureData('routes'), ensureData('exposure')]);
    } catch {
      return;
    }
    // Guard against async selection race
    if (S.sel !== id || S.selKind !== 'lake') return;
    const r = S.routes[id] || null;
    drawSelectedLakeRoute(r);
    if (fly && r && r.path && r.path.length) {
      const b = L.geoJSON(f).getBounds();
      const rb = L.polyline(r.path.map(c => [c[1], c[0]])).getBounds();
      map.fitBounds(L.latLngBounds(b).extend(rb), { padding: [42, 42], maxZoom: 12 });
    }
    renderLakeDetail(p, r, f, false);
  } else {
    gRoute.clearLayers();
    gExp.clearLayers();
  }

  if (S.tab === 'watch') {
    document.querySelectorAll('#tabbody tr[data-lake]').forEach(tr => {
      tr.classList.toggle('sel', tr.dataset.lake === id);
    });
  }
}

function drawSelectedLakeRoute(r) {
  gRoute.clearLayers();
  gExp.clearLayers();
  if (!r) return;

  if (document.getElementById('lRoute').checked && r.path && r.path.length) {
    const latlngs = r.path.map(c => [c[1], c[0]]);
    L.polyline(latlngs, { renderer: overlayRenderer, color: '#56ccf2', weight: 10, opacity: 0.18 }).addTo(gRoute);
    L.polyline(latlngs, { renderer: overlayRenderer, color: '#56ccf2', weight: 3.2, opacity: 0.95 }).addTo(gRoute);
    let cum = 0;
    let nextTick = 25;
    for (let i = 1; i < r.path.length; i++) {
      const seg = hav(r.path[i - 1][0], r.path[i - 1][1], r.path[i][0], r.path[i][1]);
      if (cum + seg >= nextTick && nextTick <= 100) {
        L.circleMarker([r.path[i][1], r.path[i][0]], {
          renderer: overlayRenderer,
          radius: 4,
          color: '#0a0f16',
          weight: 1.2,
          fillColor: '#56ccf2',
          fillOpacity: 1,
        })
          .bindTooltip(`${nextTick} km downstream · arrival ${travelText(nextTick)}`, { direction: 'top' })
          .addTo(gRoute);
        nextTick += 25;
      }
      cum += seg;
    }
  }

  if (document.getElementById('lExp').checked && Array.isArray(r.exp)) {
    const colMap = {
      hydropower: '#facc15',
      health: '#4fd1c5',
      places: '#eef4fb',
      bridges: '#94a3b8',
      borders: '#c084fc',
    };
    r.exp.forEach(([idx, km, off]) => {
      const o = S.expoById[idx];
      if (!o) return;
      L.circleMarker([o.lat, o.lon], {
        renderer: overlayRenderer,
        radius: o.kind === 'hydropower' ? 6 : 4,
        color: '#0a0f16',
        weight: 1.1,
        fillColor: colMap[o.kind] || '#94a3b8',
        fillOpacity: 0.95,
      })
        .bindPopup(
          `<b>${esc(o.name || o.sub || o.kind)}</b>`
          + `<br>${esc(o.kind)}${o.sub ? ' · ' + esc(o.sub) : ''}`
          + `<br>${fmt(km, 1)} km downstream, ${fmt(off)} m from channel`
          + `<br>Arrival: ${esc(travelText(km))}`
        )
        .addTo(gExp);
    });
  }
}

function downstreamTimelineSvg(r) {
  if (!r || !r.km) return '';
  const W = 345;
  const H = 58;
  const padL = 10;
  const padR = 14;
  const trackW = W - padL - padR;
  const maxKm = Math.max(10, r.km);
  const xOf = km => padL + Math.min(1, km / maxKm) * trackW;
  const ticks = [0, 30, 60, 90, 120].filter(k => k <= maxKm + 5);
  const colVar = {
    hydropower: 'var(--chart-hydro)',
    health: 'var(--chart-health)',
    places: 'var(--chart-place)',
    bridges: 'var(--chart-bridge)',
  };
  const pts = (r.exp || []).map(([idx, km]) => ({ o: S.expoById[idx], km })).filter(x => x.o);

  return `<svg class="timeline-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Downstream flood arrival timeline">
    <line x1="${padL}" y1="24" x2="${padL + trackW}" y2="24" stroke="var(--chart-axis)" stroke-width="3" stroke-linecap="round"/>
    ${ticks.map(k => {
      const x = xOf(k).toFixed(1);
      const min5 = Math.round((k * 1000) / 5 / 60);
      const lbl = k === 0 ? 'Lake' : `${k}km (${min5 < 90 ? min5 + 'm' : (min5 / 60).toFixed(1) + 'h'})`;
      const anchor = k === 0 ? 'start' : k >= 100 ? 'end' : 'middle';
      return `<line x1="${x}" y1="19" x2="${x}" y2="29" stroke="var(--chart-axis)" stroke-width="1"/>
        <text x="${x}" y="44" fill="var(--chart-text)" font-size="9" text-anchor="${anchor}" font-family="monospace">${lbl}</text>`;
    }).join('')}
    ${pts.map(({ o, km }) => {
      const y = o.kind === 'hydropower' ? 14 : o.kind === 'health' ? 18 : o.kind === 'places' ? 24 : 30;
      const rad = o.kind === 'hydropower' ? 4.2 : o.kind === 'health' ? 3.5 : 2.5;
      return `<circle cx="${xOf(km).toFixed(1)}" cy="${y}" r="${rad}" fill="${colVar[o.kind] || 'var(--chart-bridge)'}" opacity="0.92">
        <title>${esc(o.name || o.kind)} — ${fmt(km, 1)} km</title></circle>`;
    }).join('')}
  </svg>
  <div class="band">Channel timeline (5 m/s surge): hydro · health · settlements · bridges</div>`;
}

function renderLakeDetail(p, r, feat, routeLoading = false) {
  const el = document.getElementById('detailBody');
  const lon = Number(p.lon);
  const lat = Number(p.lat);
  const copUrl = safeUrl(
    `https://browser.dataspace.copernicus.eu/?zoom=14&lat=${lat.toFixed(4)}&lng=${lon.toFixed(4)}&datasetId=S2_L2A_CDAS`,
    ['browser.dataspace.copernicus.eu']
  );
  const osmUrl = safeUrl(
    `https://www.openstreetmap.org/?mlat=${lat.toFixed(4)}&mlon=${lon.toFixed(4)}#map=14/${lat.toFixed(4)}/${lon.toFixed(4)}`,
    ['www.openstreetmap.org']
  );

  const trig = [];
  if (p.avalanche) trig.push(`Snow/ice avalanche trajectory reaches lake (${p.ava_volume_Mm3 ? `≈${fmt(p.ava_volume_Mm3, 2)} Mm³, ` : ''}min reach ${fmt(p.ava_reach_deg, 1)}°)`);
  if (p.rockfall) trig.push(`Rockfall/landslide trajectory reaches lake (min reach ${fmt(p.rock_reach_deg, 1)}°)`);
  if (p.upstream_glof) trig.push('Another mapped glacial lake lies within 30 km upstream');
  if (p.sla_area_km2 > 0) trig.push(`Steep lakefront area ${fmt(p.sla_area_km2, 3)} km² (max depression ${fmt(p.sla_max_angle, 1)}°)`);
  if (p.ice_cored) trig.push('Moraine ice core documented in peer-reviewed literature');
  if (p.ice_contact) trig.push('Direct glacier-ice shoreline contact on Copernicus DEM / RGI 7.0');

  const hm = S.hmLakeById[p.id];
  const expRows = (r && Array.isArray(r.exp))
    ? r.exp
        .filter(([idx]) => {
          const o = S.expoById[idx];
          return o && (o.kind === 'places' || o.kind === 'hydropower' || o.kind === 'health') && o.name;
        })
        .slice(0, 12)
        .map(([idx, km]) => {
          const o = S.expoById[idx];
          return `<tr><td>${esc(o.name)} <span class="band">${esc(o.sub || o.kind)}</span></td><td class="num">${fmt(km, 1)}</td><td class="num">${esc(travelText(km))}</td></tr>`;
        })
        .join('')
    : '';

  el.innerHTML = `
    <div class="detail-head">
      <div>
        <h2>${esc(p.name || p.id)}</h2>
        <div class="band mono">${esc(p.name ? p.id : (p.rgi || 'unmatched glacier'))}${p.name && p.rgi ? ' · ' + esc(p.rgi) : ''}</div>
      </div>
      <div class="detail-actions">
        <button type="button" class="btn sm" id="btnCopyLink" title="Copy direct URL to this lake">🔗 Link</button>
        <button type="button" class="btn sm" id="btnBriefJson" title="Download full screening brief JSON">⬇ JSON</button>
      </div>
    </div>

    <div class="muted field-gap">${esc(p.typ || 'glacial lake')} · ${esc(tDistrict(p.district, S.districtsMeta))}, ${esc(tProvince(p.prov, S.districtsMeta))} · <b>${fmt(p.z)} m</b> a.s.l.</div>

    <div class="badge-row">
      <span class="hbadge ${HCLASS[p.hazard] || 'h-na'}">Hazard: ${esc(tTier(p.hazard))}</span>
      ${p.hazard_enum && p.hazard_enum !== p.hazard ? `<span class="hbadge ${HCLASS[p.hazard_enum] || 'h-na'}" title="Enumerated reading of Rounce et al. (2016)">Enum: ${esc(tTier(p.hazard_enum))}</span>` : ''}
      ${p.impact ? `<span class="hbadge ${HCLASS[p.impact] || 'h-na'}">Impact: ${esc(tTier(p.impact))}</span>` : ''}
      ${p.risk ? `<span class="hbadge ${HCLASS[p.risk] || 'h-na'}">Risk: ${esc(tTier(p.risk))}</span>` : ''}
      ${p.priority ? '<span class="hbadge h-vhigh">Priority ≥10 Mm³</span>' : ''}
      ${p.permafrost_belt ? '<span class="hbadge h-info">Permafrost belt</span>' : ''}
    </div>

    <section class="blk">
      <h3>Copernicus Sentinel-2 satellite EO</h3>
      <div id="stacBox" class="sat-card"><span class="loading">Querying Sentinel-2 L2A STAC archive…</span></div>
      <div class="btn-row">
        <a class="btn sm" href="${esc(copUrl)}" target="_blank" rel="noopener noreferrer">Copernicus Browser ↗</a>
        <a class="btn sm" href="${esc(osmUrl)}" target="_blank" rel="noopener noreferrer">OpenStreetMap ↗</a>
      </div>
    </section>

    <section class="blk">
      <h3>Triggers &amp; catchment geometry</h3>
      ${trig.length
        ? `<ul class="trig-list">${trig.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`
        : '<p class="muted">No dynamic or steep-lakefront trigger identified at 30 m DEM resolution. Subsurface moraine ice cannot be ruled out from a DEM.</p>'}
      <div class="kv">
        <span>Contributing catchment</span><b>${fmt(p.contrib_km2, 2)} km²</b>
        <span>Upslope relief in window</span><b>${fmt(p.relief_m)} m</b>
        <span>Max slope within 1 km</span><b>${fmt(p.slope1k_deg, 1)}°</b>
        <span>Lake area change</span><b>${p.area_change_pct == null ? '—' : `${p.area_change_pct > 0 ? '+' : ''}${fmt(p.area_change_pct, 1)} %`} (${esc(p.change_class || '—')})</b>
        <span>Recorded historical GLOF</span><b>${p.past_glof ? 'yes' : 'no'}</b>
      </div>
    </section>

    <section class="blk">
      <h3>Drainage &amp; breach scenarios</h3>
      <div class="kv">
        <span>Lake surface area</span><b>${fmt(p.area_km2, 3)} km²</b>
        <span>Max depth (Bayesian median)</span><b>${fmt(p.depth_m)} m <span class="band">[${fmt(p.depth_lo)}–${fmt(p.depth_hi)}]</span></b>
        <span>Bathymetric volume (Veh 2020)</span><b>${fmt(p.volume_Mm3, 2)} Mm³</b>
        <span>Potential flood volume (Fujita 2013)</span><b>${fmt(p.pfv_Mm3, 2)} Mm³ <span class="band">[${fmt(p.pfv_lo_Mm3, 1)}–${fmt(p.pfv_hi_Mm3, 1)}]</span></b>
        <span class="band">Lowering Hp${p.hp_capped ? ' (capped)' : ''} vs mean depth Dm</span><span class="band mono">${fmt(p.hp_m, 1)} m vs ${fmt(p.dm_fujita_m, 1)} m</span>
        <span>Pooled peak discharge Qp</span><b>${fmt(p.qp_m3s)} m³/s <span class="band">[${fmt(p.qp_lo)}–${fmt(p.qp_hi)}]</span></b>
        ${p.qp_over_mean_flow ? `<span>Qp ÷ mean reach discharge</span><b>×${fmt(p.qp_over_mean_flow)}</b>` : ''}
      </div>
      ${p.qp_10 ? `<div class="sat-card">
        <div class="band">Median Qp (m³/s) by breach-depth fraction:</div>
        <div class="breach-grid">
          <div><span class="band">10%</span><br><b class="mono">${fmt(p.qp_10)}</b></div>
          <div><span class="band">30%</span><br><b class="mono">${fmt(p.qp_30)}</b></div>
          <div><span class="band">50%</span><br><b class="mono">${fmt(p.qp_50)}</b></div>
          <div><span class="band">100%</span><br><b class="mono">${fmt(p.qp_100)}</b></div>
        </div>
      </div>` : ''}
    </section>

    ${p.route_km > 0 ? `
    <section class="blk">
      <h3>Downstream corridor (${fmt(p.route_km, 1)} km)</h3>
      ${routeLoading ? '<p class="loading">Loading routed channel &amp; corridor exposure…</p>' : downstreamTimelineSvg(r)}
      <div class="kv field-gap">
        <span>People within 1 km (WorldPop)</span><b>${fmt(p.pop_low)}–${fmt(p.pop_high)}</b>
        <span>Settlements / clinics / hydro / bridges</span><b>${fmt(p.n_settlements)} / ${fmt(p.n_health)} / ${fmt(p.n_hydropower)} / ${fmt(p.n_bridges)}</b>
      </div>
      ${!routeLoading ? `<table><thead><tr><th scope="col">Exposure</th><th scope="col">km</th><th scope="col">Arrival</th></tr></thead><tbody>
        ${expRows || '<tr><td colspan="3" class="muted">No named settlement, clinic, or plant mapped within 1 km.</td></tr>'}
      </tbody></table>` : ''}
    </section>` : '<section class="blk"><h3>Downstream</h3><p class="muted">Below routing threshold — no downstream channel traced.</p></section>'}

    <section class="blk">
      <h3>Hydromet, 0 °C isotherm &amp; river flow</h3>
      <div id="wx">${hm ? renderCachedLakeWx(hm) : ''}<button type="button" class="btn sm pri field-gap" id="wxBtn">↻ Load live 12-day weather, 0 °C level &amp; GloFAS flow</button></div>
    </section>

    <section class="blk">
      <h3>Active surface fault &amp; seismic proximity</h3>
      <div class="kv">
        <span>Nearest GEM surface fault</span><b>${p.fault_km != null ? fmt(p.fault_km, 1) + ' km' : '—'}</b>
        <span class="band">Structure &amp; kinematics</span><span class="band">${esc(p.fault_name || '—')} (${esc(p.fault_slip || '—')})</span>
        <span>Catalogued M≥5 within 50 km</span><b>${fmt(p.eq_n_m5_within_50km)}</b>
        <span>Catalogued M≥6 within 100 km</span><b>${fmt(p.eq_n_m6_within_100km)} (nearest ${fmt(p.eq_nearest_m6_km, 1)} km)</b>
      </div>
    </section>`;

  const wxBtn = document.getElementById('wxBtn');
  if (wxBtn) wxBtn.addEventListener('click', () => loadLakeLiveEnv(p, lat, lon, r));

  const cpBtn = document.getElementById('btnCopyLink');
  if (cpBtn) {
    cpBtn.addEventListener('click', () => {
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).catch(() => {});
      cpBtn.textContent = '✓ Copied';
    });
  }

  const dlBtn = document.getElementById('btnBriefJson');
  if (dlBtn) {
    dlBtn.addEventListener('click', () => {
      const payload = {
        lake: p,
        route: r || null,
        stac: S.stacCache[p.id] || null,
        build: S.summary && S.summary.build,
      };
      triggerBlobDownload(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }), `${p.id}_traya_brief.json`);
    });
  }

  loadStacForLake(p.id, lon, lat);
}

function renderCachedLakeWx(hm) {
  const warnCls = hm.warm_rain_on_ice ? 'text-bad' : '';
  return `<div class="kv">
    <span>Weekly precip (past 7d / next 5d)</span><b>${fmt(hm.precip_past_7d_mm, 1)} / ${fmt(hm.precip_next_5d_mm, 1)} mm</b>
    <span>12d snowfall / liquid rain</span><b>${fmt(hm.snowfall_12d_cm, 1)} cm / ${fmt(hm.liquid_rain_12d_mm, 1)} mm</b>
    <span>0 °C freezing level (now / 12d max)</span><b>${fmt(hm.freezing_level_now_m)} / ${fmt(hm.freezing_level_max_m)} m</b>
    <span>Margin vs lake (${fmt(hm.z_m)} m)</span><b class="${warnCls}">${hm.freezing_margin_m > 0 ? '+' : ''}${fmt(hm.freezing_margin_m)} m ${hm.warm_rain_on_ice ? '(warm rain-on-ice!)' : ''}</b>
  </div>`;
}

async function loadStacForLake(id, lon, lat) {
  const box = document.getElementById('stacBox');
  if (!box) return;
  if (S.stacCache[id]) {
    renderStacCard(box, S.stacCache[id]);
    return;
  }
  const url = safeUrl(
    (S.summary && S.summary.live_feeds && S.summary.live_feeds.stac_earth_search)
      || 'https://earth-search.aws.element84.com/v1/search',
    ['earth-search.aws.element84.com']
  ) || 'https://earth-search.aws.element84.com/v1/search';

  const now = new Date();
  const past = new Date(now.getTime() - 120 * 86400000);
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: combinedSignal(null, 15000),
      body: JSON.stringify({
        collections: ['sentinel-2-l2a'],
        bbox: [Number((lon - 0.025).toFixed(4)), Number((lat - 0.025).toFixed(4)), Number((lon + 0.025).toFixed(4)), Number((lat + 0.025).toFixed(4))],
        datetime: `${past.toISOString().slice(0, 19)}Z/${now.toISOString().slice(0, 19)}Z`,
        limit: 10,
      }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const gj = await resp.json();
    const feats = (gj.features || []).sort((a, b) =>
      String((b.properties && b.properties.datetime) || '').localeCompare(String((a.properties && a.properties.datetime) || ''))
    );
    if (!feats.length) {
      if (S.sel === id) box.innerHTML = '<span class="muted">No recent Sentinel-2 L2A scene returned for this footprint.</span>';
      return;
    }
    const clear = feats.filter(f => (f.properties && f.properties['eo:cloud_cover'] != null ? f.properties['eo:cloud_cover'] : 100) <= 30);
    const best = clear[0] || feats.reduce((a, b) => ((a.properties['eo:cloud_cover'] ?? 100) <= (b.properties['eo:cloud_cover'] ?? 100) ? a : b));
    const bp = best.properties || {};
    const assets = best.assets || {};
    const rec = {
      scene_id: best.id,
      datetime: bp.datetime,
      cloud_cover_pct: Number((bp['eo:cloud_cover'] || 0).toFixed(1)),
      grid_code: bp['grid:code'] || '',
      thumbnail: safeUrl(
        (assets.thumbnail && assets.thumbnail.href) || (assets.rendered_preview && assets.rendered_preview.href) || '',
        STAC_THUMB_HOSTS
      ),
      latest_pass_datetime: feats[0].properties && feats[0].properties.datetime,
    };
    S.stacCache[id] = rec;
    if (S.sel === id && S.selKind === 'lake') renderStacCard(box, rec);
  } catch (err) {
    if (S.sel === id && S.selKind === 'lake') {
      box.innerHTML = `<span class="muted">Live STAC preview unavailable (${esc(err.message)}). Use Copernicus Browser below for 10 m imagery.</span>`;
    }
  }
}

function renderStacCard(box, sc) {
  const thumb = safeUrl(sc.thumbnail, STAC_THUMB_HOSTS);
  box.innerHTML = `
    ${thumb ? `<img class="sat-thumb" src="${esc(thumb)}" alt="Sentinel-2 L2A optical quicklook" loading="lazy">` : ''}
    <div class="kv">
      <span>Clearest S2 pass</span><b>${esc(fmtNpt(sc.datetime, false))} (${fmt(sc.cloud_cover_pct, 1)}% cloud)</b>
      <span class="band">Scene / tile</span><span class="band mono">${esc(sc.scene_id || '—')}</span>
      ${sc.latest_pass_datetime ? `<span class="band">Most recent overpass</span><span class="band mono">${esc(fmtNpt(sc.latest_pass_datetime, false))}</span>` : ''}
    </div>`;
  bindImageFallbacks(box);
}

async function loadLakeLiveEnv(p, lat, lon, r) {
  const box = document.getElementById('wx');
  if (!box) return;
  const reqId = p.id;
  box.innerHTML = '<span class="loading">Fetching live Open-Meteo liquid rain, 0 °C isotherm &amp; GloFAS discharge…</span>';

  const wxUrl = 'https://api.open-meteo.com/v1/forecast'
    + `?latitude=${lat.toFixed(3)}&longitude=${lon.toFixed(3)}`
    + '&daily=rain_sum,precipitation_sum,snowfall_sum,temperature_2m_max&hourly=rain,freezinglevel_height&past_days=7&forecast_days=5&timezone=Asia%2FKathmandu';
  const outlet = (r && r.path && r.path.length) ? r.path[Math.min(8, r.path.length - 1)] : [lon, lat];
  const flUrl = 'https://flood-api.open-meteo.com/v1/flood'
    + `?latitude=${outlet[1].toFixed(3)}&longitude=${outlet[0].toFixed(3)}&daily=river_discharge,river_discharge_median,river_discharge_max&past_days=7&forecast_days=14`;

  try {
    const [wxRes, flRes] = await Promise.all([
      fetch(wxUrl, { signal: combinedSignal(null, 15000) }),
      fetch(flUrl, { signal: combinedSignal(null, 15000) }).catch(() => null),
    ]);
    if (S.sel !== reqId || S.selKind !== 'lake') return;
    if (!wxRes.ok) throw new Error(`HTTP ${wxRes.status}`);
    const d = await wxRes.json();
    const days = (d.daily && d.daily.time) || [];
    const pr = (d.daily && (d.daily.rain_sum || d.daily.precipitation_sum)) || [];
    const sn = (d.daily && d.daily.snowfall_sum) || [];
    const tx = (d.daily && d.daily.temperature_2m_max) || [];
    const flH = ((d.hourly && d.hourly.freezinglevel_height) || []).filter(v => v != null && Number.isFinite(v));
    const rH = ((d.hourly && d.hourly.rain) || []).map(v => Number(v) || 0);

    let max24 = 0;
    for (let i = 24; i <= rH.length; i++) {
      let s = 0;
      for (let j = i - 24; j < i; j++) s += rH[j];
      if (s > max24) max24 = s;
    }
    const ec24 = 144.0;
    const sum7 = pr.slice(0, 7).reduce((a, b) => a + (Number(b) || 0), 0);
    const f5 = pr.slice(7).reduce((a, b) => a + (Number(b) || 0), 0);
    const snow12 = sn.reduce((a, b) => a + (Number(b) || 0), 0);
    const flMax = flH.length ? Math.max(...flH) : null;

    let riverHtml = '';
    if (flRes && flRes.ok) {
      const fd = await flRes.json();
      const qSim = (fd.daily && fd.daily.river_discharge) || [];
      const qMed = (fd.daily && fd.daily.river_discharge_median) || [];
      const qNow = qSim[7] ?? qSim[6];
      const qPeak = Math.max(...qMed.slice(7).filter(v => v != null), qNow || 0);
      riverHtml = `<span>Receiving river GloFAS (now / 14d)</span><b>${fmt(qNow, 1)} / ${fmt(qPeak, 1)} m³/s</b>`;
    }

    if (S.sel !== reqId || S.selKind !== 'lake') return;
    box.innerHTML = `<div class="kv">
      <span>Liquid rain past 7d / next 5d</span><b>${fmt(sum7, 1)} / ${fmt(f5, 1)} mm</b>
      <span>12d snowfall total</span><b>${fmt(snow12, 1)} cm</b>
      <span>Max 24h liquid rain vs D–H</span><b>${fmt(max24, 1)} / ${fmt(ec24, 0)} mm (${fmt((100 * max24) / ec24, 0)}%)</b>
      <span>Peak 0 °C freezing level</span><b>${fmt(flMax, 0)} m (lake ${fmt(p.z, 0)} m)</b>
      <span>Max air temp today (${fmt(d.elevation, 0)} m grid)</span><b>${fmt(tx[7], 1)} °C</b>
      ${riverHtml}
    </div>` + sparkline(days, pr);
  } catch (err) {
    if (S.sel === reqId) {
      box.innerHTML = `<span class="loading">Live weather unavailable (${esc(err.message)})</span>`;
    }
  }
}

function sparkline(days, pr) {
  if (!pr || !pr.length) return '';
  const w = 330;
  const h = 46;
  const m = Math.max(1, ...pr.map(v => Number(v) || 0));
  const bw = w / pr.length;
  const bars = pr.map((v, i) => {
    const val = Number(v) || 0;
    const bh = (val / m) * (h - 12);
    const past = i < 7;
    const dayStr = esc(days && days[i] != null ? days[i] : '');
    return `<rect x="${(i * bw + 1).toFixed(1)}" y="${(h - 2 - bh).toFixed(1)}" width="${Math.max(2, bw - 2).toFixed(1)}" height="${bh.toFixed(1)}" fill="${past ? 'var(--chart-sim)' : 'var(--chart-med)'}" opacity="${past ? '0.92' : '0.72'}"><title>${dayStr}: ${fmt(val, 1)} mm</title></rect>`;
  }).join('');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="12-day precipitation sparkline">${bars}
    <line x1="${(7 * bw).toFixed(1)}" y1="0" x2="${(7 * bw).toFixed(1)}" y2="${h}" stroke="var(--chart-axis)" stroke-dasharray="2 2"/>
  </svg><div class="band">Blue = past 7d observed, teal = 5d forecast, dashed = today (peak ${fmt(m, 1)} mm/d)</div>`;
}

function selectRiver(id, fly) {
  const b = S.rivers.find(x => x.id === id);
  if (!b) return;
  const prevLakeId = S.selKind === 'lake' ? S.sel : null;
  S.sel = id;
  S.selKind = 'river';
  if (prevLakeId) updateLakeSelectionStyle(prevLakeId, null);
  ensureRightVisible();
  if (fly) map.setView([b.lat, b.lon], 9);

  const c = b.climatology || {};
  const bName = getLang() === 'ne' && b.name_ne ? `${b.name_ne} (${b.name})` : b.name;
  const years = c.years || (S.riversMeta && S.riversMeta.climatology_years) || 21;
  const el = document.getElementById('detailBody');

  el.innerHTML = `
    <h2>■ ${esc(bName)}</h2>
    <div class="muted">${esc(b.station)} · ${esc(tDistrict(b.district, S.districtsMeta))}, ${esc(tProvince(b.prov, S.districtsMeta))} · ${esc(b.dhm_ref || '')}</div>
    <div class="badge-row">
      <span class="hbadge ${FCLASS[b.status_now || 'normal'] || 'h-na'}">Now: ${esc(tRiverStatus(b.status_now || 'normal'))}</span>
      <span class="hbadge ${FCLASS[b.status_14d || 'normal'] || 'h-na'}">14d: ${esc(tRiverStatus(b.status_14d || 'normal'))}</span>
      ${b.grid_snap_warning ? '<span class="hbadge h-mod">⚠ Off-mainstem snap</span>' : ''}
    </div>

    ${b.grid_snap_warning ? `<div class="callout"><b>Grid-cell snapping warning:</b> ${esc(b.grid_snap_note || 'Cached GloFAS cell sits off-mainstem; click Refresh live or consult Nepal DHM.')}</div>` : ''}

    <section class="blk">
      <h3>GloFAS 60-day discharge hydrograph</h3>
      ${riverHydrographSvg(b)}
      <div class="kv field-gap">
        <span>Updated (NPT)</span><b>${esc(fmtNpt(b.fetched_utc || (S.riversMeta && S.riversMeta.updated_utc)))}</b>
        <span>Current simulated discharge</span><b>${fmt(b.current_m3s, 1)} m³/s</b>
        <span>vs long-term median (Q₅₀)</span><b>${b.climatology_unmatched ? '— (uncalibrated cell)' : `${b.anomaly_ratio ? '×' + fmt(b.anomaly_ratio, 2) : '—'} (${fmt(c.q50, 1)} m³/s)`}</b>
        <span>14-day ensemble median peak</span><b>${fmt(b.peak_14d_median_m3s, 1)} m³/s</b>
        <span>14-day ensemble p75 / max</span><b>${fmt(b.peak_14d_p75_m3s, 1)} / ${fmt(b.peak_14d_max_m3s, 1)} m³/s</b>
      </div>
    </section>

    <section class="blk">
      <h3>Basin flood thresholds (${fmt(years)}-year Gumbel EV1)</h3>
      ${b.climatology_unmatched
        ? '<p class="muted">Cached return-period thresholds belong to an off-mainstem grid cell and are withheld from live mainstem grading until the next weekly reanalysis refit.</p>'
        : `<div class="kv">
            <span>90th percentile high flow (Q₉₀)</span><b>${fmt(c.q90, 1)} m³/s</b>
            <span>2-year return level (Q₂)</span><b>${fmt(c.q2, 1)} m³/s</b>
            <span>5-year return level (Q₅)</span><b>${fmt(c.q5, 1)} m³/s</b>
            <span>20-year return level (Q₂₀)</span><b>${fmt(c.q20, 1)} m³/s</b>
          </div>`}
      <p class="muted">Return levels fitted by Gumbel EV1 method-of-moments to ${fmt(years)} annual maxima of Copernicus GloFAS-ERA5 daily discharge. Always consult Nepal DHM real-time river gauges (<a href="https://hydrology.gov.np/" target="_blank" rel="noopener noreferrer">hydrology.gov.np</a>).</p>
    </section>`;
}

function riverHydrographSvg(b) {
  const s = b.series || {};
  const times = s.time || [];
  const sim = s.discharge || [];
  const med = s.median || [];
  const p25 = s.p25 || [];
  const p75 = s.p75 || [];
  const mx = s.max || [];
  if (!times.length) return '<p class="muted">No time series loaded.</p>';

  const W = 350;
  const H = 140;
  const pL = 40;
  const pR = 8;
  const pT = 10;
  const pB = 22;
  const cW = W - pL - pR;
  const cH = H - pT - pB;
  const c = b.climatology || {};
  const showThresholds = !b.climatology_unmatched;
  const allVals = [...sim, ...med, ...p75, ...mx, (showThresholds ? c.q2 : 0) || 0].filter(v => v != null && Number.isFinite(v));
  const yMax = Math.max(10, ...allVals) * 1.08;
  const xOf = i => pL + (i / Math.max(1, times.length - 1)) * cW;
  const yOf = v => pT + cH - Math.min(1, Math.max(0, (v || 0) / yMax)) * cH;
  const idx0 = Math.min(s.today_index || 30, times.length - 1);

  const bandPts = [];
  for (let i = idx0; i < times.length; i++) if (p75[i] != null) bandPts.push(`${xOf(i).toFixed(1)},${yOf(p75[i]).toFixed(1)}`);
  for (let i = times.length - 1; i >= idx0; i--) if (p25[i] != null) bandPts.push(`${xOf(i).toFixed(1)},${yOf(p25[i]).toFixed(1)}`);

  const pathOf = (arr, iStart, iEnd) => {
    const pts = [];
    for (let i = iStart; i <= iEnd && i < arr.length; i++) {
      if (arr[i] != null) pts.push(`${pts.length ? 'L' : 'M'}${xOf(i).toFixed(1)},${yOf(arr[i]).toFixed(1)}`);
    }
    return pts.join(' ');
  };

  const tFirst = esc(String(times[0] || '').slice(5));
  const tLast = esc(String(times[times.length - 1] || '').slice(5));

  return `<svg class="hydro-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="60-day GloFAS discharge hydrograph">
    <line x1="${pL}" y1="${pT + cH}" x2="${W - pR}" y2="${pT + cH}" stroke="var(--chart-axis)"/>
    ${showThresholds && c.q2 && c.q2 <= yMax ? `<line x1="${pL}" y1="${yOf(c.q2).toFixed(1)}" x2="${W - pR}" y2="${yOf(c.q2).toFixed(1)}" stroke="var(--chart-q2)" stroke-dasharray="3 3" stroke-width="1.2"/>
      <text x="${W - pR - 2}" y="${(yOf(c.q2) - 3).toFixed(1)}" fill="var(--chart-q2)" font-size="8.5" font-weight="700" text-anchor="end" font-family="monospace">Q₂ ${fmt(c.q2, 0)}</text>` : ''}
    ${showThresholds && c.q5 && c.q5 <= yMax ? `<line x1="${pL}" y1="${yOf(c.q5).toFixed(1)}" x2="${W - pR}" y2="${yOf(c.q5).toFixed(1)}" stroke="var(--chart-q5)" stroke-dasharray="3 3" stroke-width="1.2"/>
      <text x="${W - pR - 2}" y="${(yOf(c.q5) - 3).toFixed(1)}" fill="var(--chart-q5)" font-size="8.5" font-weight="700" text-anchor="end" font-family="monospace">Q₅ ${fmt(c.q5, 0)}</text>` : ''}
    ${bandPts.length > 3 ? `<polygon points="${bandPts.join(' ')}" fill="var(--chart-med)" fill-opacity="0.22"/>` : ''}
    <path d="${pathOf(mx, idx0, times.length - 1)}" fill="none" stroke="var(--chart-max)" stroke-width="1.1" stroke-dasharray="2 2"/>
    <path d="${pathOf(sim, 0, idx0)}" fill="none" stroke="var(--chart-sim)" stroke-width="2.1"/>
    <path d="${pathOf(med.some(x => x != null) ? med : sim, idx0, times.length - 1)}" fill="none" stroke="var(--chart-med)" stroke-width="2.1"/>
    <line x1="${xOf(idx0).toFixed(1)}" y1="${pT}" x2="${xOf(idx0).toFixed(1)}" y2="${pT + cH}" stroke="var(--chart-axis)" stroke-dasharray="2 2"/>
    <text x="${pL - 4}" y="${pT + 8}" fill="var(--chart-text)" font-size="8.5" text-anchor="end" font-family="monospace">${fmt(yMax, 0)}</text>
    <text x="${pL - 4}" y="${pT + cH}" fill="var(--chart-text)" font-size="8.5" text-anchor="end" font-family="monospace">0</text>
    <text x="${pL}" y="${H - 5}" fill="var(--chart-text)" font-size="8.5" font-family="monospace">${tFirst}</text>
    <text x="${xOf(idx0).toFixed(1)}" y="${H - 5}" fill="var(--chart-text)" font-size="8.5" text-anchor="middle" font-family="monospace">today</text>
    <text x="${W - pR}" y="${H - 5}" fill="var(--chart-text)" font-size="8.5" text-anchor="end" font-family="monospace">${tLast}</text>
  </svg>
  <div class="band">Blue = past 30d GloFAS, teal = 30d median + p25–p75 band, dashed orange = ensemble max (m³/s)</div>`;
}

function selectNode(id, fly) {
  const nd = ((S.hydromet && S.hydromet.nodes) || []).find(x => x.id === id);
  if (!nd) return;
  const prevLakeId = S.selKind === 'lake' ? S.sel : null;
  S.sel = id;
  S.selKind = 'node';
  if (prevLakeId) updateLakeSelectionStyle(prevLakeId, null);
  ensureRightVisible();
  if (fly) map.setView([nd.lat, nd.lon], 9);

  const dh = nd.dh_combined || nd.dh_obs || {};
  const lv = dh.level || 'low';
  const el = document.getElementById('detailBody');
  el.innerHTML = `
    <h2>▲ ${esc(nd.name)}</h2>
    <div class="muted">${esc(nd.zone)} · ${esc(tDistrict(nd.district, S.districtsMeta))}, ${esc(tProvince(nd.prov, S.districtsMeta))} · ${fmt(nd.elev_m)} m</div>
    <div class="badge-row">
      <span class="hbadge ${DHCLASS[lv] || 'h-low'}">Dahal–Hasegawa: ${esc(tDhLevel(lv))} (${fmt((dh.max_ratio || 0) * 100, 0)}%)</span>
      <span class="hbadge h-info">Liquid rain only</span>
    </div>
    <section class="blk">
      <h3>12-day liquid rain &amp; slope saturation</h3>
      ${nd.daily_time && nd.daily_time.length ? sparkline(nd.daily_time, nd.daily_rain || nd.daily_precip || []) : ''}
      <div class="kv field-gap">
        <span>Updated (NPT)</span><b>${esc(fmtNpt(S.hydromet && S.hydromet.updated_utc))}</b>
        <span>Past 7-day liquid rain</span><b>${fmt(nd.rain_past_7d_mm, 1)} mm</b>
        <span>Next 5-day forecast rain</span><b>${fmt(nd.rain_next_5d_mm, 1)} mm</b>
        <span>Peak 24h observed / threshold</span><b>${fmt(nd.max_24h_obs_mm, 1)} / ${fmt(dh.ec_24h_mm, 0)} mm</b>
        <span>Peak 72h observed / threshold</span><b>${fmt(nd.max_72h_obs_mm, 1)} / ${fmt(dh.ec_72h_mm, 0)} mm</b>
        <span>0–7 cm topsoil moisture</span><b>${fmt(nd.soil_moisture_m3m3, 3)} m³/m³</b>
        <span>0 °C freezing level</span><b>${fmt(nd.freezing_level_m, 0)} m a.s.l.</b>
      </div>
      <p class="muted">Evaluated strictly on liquid rain against I = 73.90 D⁻⁰·⁷⁹ (Dahal &amp; Hasegawa 2008, Nepal Himalaya). Exceedance indicates regional rainfall capable of triggering shallow landslides, not site-specific failure certainty.</p>
    </section>`;
}

/* ==========================================================================
   14. Analytical Workbench Tabs (Lazy Data + Full Keyboard/ARIA Tables)
   ========================================================================== */
const WCOLS = [
  ['name', 'Lake', 't'],
  ['id', 'ID', 't'],
  ['district', 'District', 'dist'],
  ['prov', 'Province', 'prov'],
  ['area_km2', 'Area km²', 'n2'],
  ['z', 'm a.s.l.', 'n0'],
  ['hazard', 'Hazard', 'h'],
  ['impact', 'Impact', 'h'],
  ['risk', 'Risk', 'h'],
  ['pfv_Mm3', 'PFV Mm³', 'pfv'],
  ['qp_m3s', 'Qp m³/s', 'n0'],
  ['priority', 'Prio', 'b'],
  ['pop_high', 'People ≤1 km', 'n0'],
  ['n_hydropower', 'Hydro', 'n0'],
  ['fault_km', 'Fault km', 'n1'],
];

function sortVal(p, k) {
  if (k === 'hazard' || k === 'impact' || k === 'risk' || k === 'hazard_enum') return HORD[p[k]] ?? -1;
  if (k === 'priority') return p.priority ? 1 : 0;
  const v = p[k];
  return typeof v === 'number' ? v : (v == null ? -1e9 : String(v));
}

async function renderTab() {
  const b = document.getElementById('tabbody');
  if (!b) return;
  const tab = S.tab;

  // Lazy-fetch tab-specific JSONs before rendering
  const needMap = {
    landslides: ['landslides', 'landslide_review_queue'],
    cascades: ['cascades', 'exposure_isolation', 'tsho_rolpa_pilot'],
    live: ['bipad_official', 'faults', 'eq_history_m6'],
    sat: ['eo_sar'],
    glof: ['glof_history'],
    valid: ['validation', 'sensitivity'],
  };
  const needed = (needMap[tab] || []).filter(k => {
    if (k === 'landslides') return !S.landslides;
    if (k === 'landslide_review_queue') return !S.lsReviewQueue;
    if (k === 'cascades') return !S.cascades;
    if (k === 'exposure_isolation') return !S.exposureIso;
    if (k === 'tsho_rolpa_pilot') return !S.tshoRolpaPilot;
    if (k === 'bipad_official') return !S.bipad;
    if (k === 'eo_sar') return !S.eoSar;
    if (k === 'faults') return !S.faults;
    if (k === 'eq_history_m6') return !S.eqHist;
    if (k === 'glof_history') return !S.glofHist;
    if (k === 'validation') return !S.valid;
    if (k === 'sensitivity') return !S.sens;
    return false;
  });

  if (needed.length) {
    b.innerHTML = '<p class="loading">Loading observatory dataset…</p>';
    try {
      await Promise.all(needed.map(k => ensureData(k)));
    } catch (err) {
      if (S.tab === tab) {
        b.innerHTML = `<div class="callout bad">Failed to load dataset (${esc(err.message)}).</div>`;
      }
      return;
    }
    if (S.tab !== tab) return;
  }

  if (tab === 'watch') b.innerHTML = tabWatch();
  else if (tab === 'floods') b.innerHTML = tabFloods();
  else if (tab === 'landslides') b.innerHTML = tabLandslides();
  else if (tab === 'cascades') b.innerHTML = tabCascades();
  else if (tab === 'live') b.innerHTML = tabLive();
  else if (tab === 'sat') b.innerHTML = tabSat();
  else if (tab === 'glof') b.innerHTML = tabGlof();
  else if (tab === 'charts') b.innerHTML = tabCharts();
  else if (tab === 'valid') b.innerHTML = tabValid();
  else b.innerHTML = tabMethods();

  hydrateBars(b);
  wireTabInteractions(b);
}

function wireTabInteractions(b) {
  b.querySelectorAll('th[data-k]').forEach(th => {
    const activate = () => {
      const k = th.dataset.k;
      S.sort = { k, dir: S.sort.k === k ? -S.sort.dir : -1 };
      renderTab();
    };
    th.addEventListener('click', activate);
    th.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activate();
      }
    });
  });

  const bindRow = (selector, handler) => {
    b.querySelectorAll(selector).forEach(tr => {
      tr.addEventListener('click', e => {
        if (e.target && e.target.closest('a,button')) return;
        handler(tr);
      });
      tr.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handler(tr);
        }
      });
    });
  };

  bindRow('tr[data-lake]', tr => selectLake(tr.dataset.lake, true));
  bindRow('tr[data-river]', tr => selectRiver(tr.dataset.river, true));
  bindRow('tr[data-node]', tr => selectNode(tr.dataset.node, true));
  bindRow('tr[data-dist]', tr => selectDistrict(tr.dataset.dist, true));
  bindRow('tr[data-fly]', tr => {
    if (!tr.dataset.fly) return;
    const parts = tr.dataset.fly.split(',');
    if (parts.length < 2) return;
    const [la, lo, z] = parts.map(Number);
    if (Number.isFinite(la) && Number.isFinite(lo)) map.setView([la, lo], Number.isFinite(z) ? z : 11);
  });

  // Buttons inside tabs: fly to lake, open district, filter landslide types, toggle isolation view, inspect cascade graph
  b.querySelectorAll('button[data-open-lake]').forEach(btn => {
    btn.addEventListener('click', () => selectLake(btn.dataset.openLake, true));
  });
  b.querySelectorAll('button[data-open-dist]').forEach(btn => {
    btn.addEventListener('click', () => selectDistrict(btn.dataset.openDist, true));
  });
  b.querySelectorAll('button[data-ls-type]').forEach(btn => {
    btn.addEventListener('click', () => {
      S.lsTypeFilter = btn.dataset.lsType || 'all';
      renderTab();
    });
  });
  b.querySelectorAll('button[data-iso-view]').forEach(btn => {
    btn.addEventListener('click', () => {
      S.isoView = btn.dataset.isoView === 'districts' ? 'districts' : 'lakes';
      renderTab();
    });
  });

  const bindCascadeSelection = (selector, kind, attrKey) => {
    b.querySelectorAll(selector).forEach(el => {
      const pick = () => {
        S.cascadeSel = { kind, id: el.dataset[attrKey] };
        const insp = b.querySelector('#cascadeInspector');
        if (insp && S.cascades) {
          insp.innerHTML = renderCascadeInspector(S.cascades);
          insp.querySelectorAll('button[data-open-dist]').forEach(btn => {
            btn.addEventListener('click', () => selectDistrict(btn.dataset.openDist, true));
          });
        }
        b.querySelectorAll('.cg-node,.cg-edge-hit').forEach(x => x.classList.remove('is-selected'));
        el.classList.add('is-selected');
      };
      el.addEventListener('click', pick);
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          pick();
        }
      });
    });
  };
  bindCascadeSelection('[data-cg-node]', 'node', 'cgNode');
  bindCascadeSelection('[data-cg-edge]', 'edge', 'cgEdge');

  const dlCsv = b.querySelector('#dlCsv');
  if (dlCsv) dlCsv.addEventListener('click', downloadCsv);
  const dlGeo = b.querySelector('#dlGeo');
  if (dlGeo) dlGeo.addEventListener('click', downloadGeoJson);
}

function tabWatch() {
  const rows = (S.shown || []).map(f => f.properties).slice();
  rows.sort((a, b) => {
    const x = sortVal(a, S.sort.k);
    const y = sortVal(b, S.sort.k);
    return (x < y ? -1 : x > y ? 1 : 0) * S.sort.dir;
  });
  const top = rows.slice(0, 400);
  const maxPfv = Math.max(10, ...rows.map(r => r.pfv_Mm3 || 0));

  return `<div class="tbl-toolbar">
      <span class="muted"><b>${fmt(rows.length)}</b> lakes after filtering — showing top ${fmt(top.length)} sorted by <code>${esc(S.sort.k)}</code></span>
      <button type="button" class="btn sm" id="dlCsv">⬇ CSV</button>
      <button type="button" class="btn sm" id="dlGeo">⬇ GeoJSON</button>
    </div>
    <table><thead><tr>${WCOLS.map(([k, l]) => {
      const isCur = S.sort.k === k;
      const ariaSort = isCur ? (S.sort.dir < 0 ? 'descending' : 'ascending') : 'none';
      const arrow = isCur ? (S.sort.dir < 0 ? ' ↓' : ' ↑') : '';
      return `<th scope="col" tabindex="0" data-k="${k}" aria-sort="${ariaSort}">${esc(l)}${arrow}</th>`;
    }).join('')}</tr></thead><tbody>
    ${top.map(p => `<tr tabindex="0" data-lake="${esc(p.id)}" class="${p.id === S.sel && S.selKind === 'lake' ? 'sel' : ''}">${WCOLS.map(([k, , kind]) => {
      const v = p[k];
      if (kind === 'h') return `<td>${v ? `<span class="hbadge ${HCLASS[v] || 'h-na'}">${esc(tTier(v))}</span>` : '—'}</td>`;
      if (kind === 'b') return `<td>${v ? '<span class="hbadge h-vhigh">PFV ≥10</span>' : '<span class="band">—</span>'}</td>`;
      if (kind === 'dist') return `<td>${esc(tDistrict(v, S.districtsMeta))}</td>`;
      if (kind === 'prov') return `<td>${esc(tProvince(v, S.districtsMeta))}</td>`;
      if (kind === 't') return `<td>${esc(v || '—')}</td>`;
      if (kind === 'pfv') {
        const w = v > 0 ? Math.max(2, Math.round((v / maxPfv) * 44)) : 0;
        return `<td class="num">${w ? `<span class="minibar${p.priority ? ' prio' : ''}" data-w="${w}px"></span>` : ''}${fmt(v, 1)}</td>`;
      }
      return `<td class="num">${fmt(v, Number(kind.slice(1)))}</td>`;
    }).join('')}</tr>`).join('')}
    </tbody></table>`;
}

function downloadCsv() {
  const rows = (S.shown || []).map(f => f.properties);
  const keys = Object.keys(rows[0] || {});
  const csv = [keys.map(csvCell).join(',')]
    .concat(rows.map(r => keys.map(k => csvCell(r[k])).join(',')))
    .join('\n');
  triggerBlobDownload(new Blob([csv], { type: 'text/csv;charset=utf-8' }), 'nepal_traya_glacial_lakes.csv');
}

function downloadGeoJson() {
  const gj = { type: 'FeatureCollection', features: S.shown || [] };
  triggerBlobDownload(new Blob([JSON.stringify(gj)], { type: 'application/geo+json' }), 'nepal_traya_glacial_lakes.geojson');
}

function tabFloods() {
  if (!S.rivers.length) return '<p class="muted">GloFAS river flood layer not loaded.</p>';
  const snapCnt = S.rivers.filter(b => b.grid_snap_warning).length;
  const yrs = (S.riversMeta && S.riversMeta.climatology_years) || 21;
  const updatedStr = fmtNpt(S.riversMeta && S.riversMeta.updated_utc);
  const ageStr = fmtAge(S.riversMeta && S.riversMeta.updated_utc);

  return `${snapCnt ? `<div class="callout"><b>⚠ Grid-cell snapping disclosure:</b> ${esc(t('gridSnapNotice', { n: snapCnt }))}</div>` : ''}
    <div class="tbl-toolbar">
      <span class="muted"><b>Copernicus EMS GloFAS</b> across Nepal's 10 major river outlets (${fmt(yrs)}-year Gumbel EV1 · updated ${esc(updatedStr)}, ${esc(ageStr)}). Click any row to inspect its 60-day hydrograph.</span>
    </div>
    <table><thead><tr>
      <th scope="col">River Basin</th><th scope="col">Outlet Corridor</th><th scope="col">Province</th>
      <th scope="col">Now m³/s</th><th scope="col">vs Q₅₀</th><th scope="col">14d Med</th>
      <th scope="col">14d p75</th><th scope="col">14d Max</th><th scope="col">Q₂</th>
      <th scope="col">Q₅</th><th scope="col">Q₂₀</th><th scope="col">Status</th>
    </tr></thead><tbody>
    ${S.rivers.map(b => {
      const c = b.climatology || {};
      const st = riverHeadlineStatus(b);
      const bName = getLang() === 'ne' && b.name_ne ? `${b.name_ne} (${b.name})` : b.name;
      const unm = Boolean(b.climatology_unmatched);
      return `<tr tabindex="0" data-river="${esc(b.id)}" class="${b.id === S.sel && S.selKind === 'river' ? 'sel' : ''}">
        <td><b>${esc(bName)}</b> ${b.grid_snap_warning ? '<span class="hbadge h-mod" title="Cached cell off-mainstem">⚠ snap</span>' : ''}</td>
        <td>${esc(b.station)}</td>
        <td>${esc(tProvince(b.prov, S.districtsMeta))}</td>
        <td class="num">${fmt(b.current_m3s, 1)}</td>
        <td class="num">${!unm && b.anomaly_ratio ? '×' + fmt(b.anomaly_ratio, 2) : '—'}</td>
        <td class="num"><b>${fmt(b.peak_14d_median_m3s, 1)}</b></td>
        <td class="num">${fmt(b.peak_14d_p75_m3s, 1)}</td>
        <td class="num">${fmt(b.peak_14d_max_m3s, 1)}</td>
        <td class="num">${unm ? '—' : fmt(c.q2, 0)}</td>
        <td class="num">${unm ? '—' : fmt(c.q5, 0)}</td>
        <td class="num">${unm ? '—' : fmt(c.q20, 0)}</td>
        <td><span class="hbadge ${FCLASS[st] || 'h-na'}">${esc(tRiverStatus(st))}</span></td>
      </tr>`;
    }).join('')}
    </tbody></table>`;
}

function idCurveSvg(nodes) {
  const W = 380;
  const H = 200;
  const pL = 44;
  const pR = 12;
  const pT = 12;
  const pB = 28;
  const cW = W - pL - pR;
  const cH = H - pT - pB;
  const xMin = Math.log10(5);
  const xMax = Math.log10(240);
  const yMin = Math.log10(0.05);
  const yMax = Math.log10(60);
  const xOf = d => pL + ((Math.log10(d) - xMin) / (xMax - xMin)) * cW;
  const yOf = iv => pT + cH - ((Math.log10(Math.max(0.05, iv)) - yMin) / (yMax - yMin)) * cH;
  const dhLine = [5, 12, 24, 72, 168, 240].map((d, k) => `${k ? 'L' : 'M'}${xOf(d).toFixed(1)},${yOf(73.9 * Math.pow(d, -0.79)).toFixed(1)}`).join(' ');
  const gzLine = [5, 12, 24, 72, 168, 240].map((d, k) => `${k ? 'L' : 'M'}${xOf(d).toFixed(1)},${yOf(2.2 * Math.pow(d, -0.44)).toFixed(1)}`).join(' ');

  return `<svg class="id-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Dahal and Hasegawa rainfall intensity-duration threshold diagram">
    ${[6, 24, 72, 168].map(d => `<line x1="${xOf(d).toFixed(1)}" y1="${pT}" x2="${xOf(d).toFixed(1)}" y2="${pT + cH}" stroke="var(--chart-grid)" stroke-dasharray="2 2"/>
      <text x="${xOf(d).toFixed(1)}" y="${H - 8}" fill="var(--chart-text)" font-size="9" text-anchor="middle" font-family="monospace">${d}h</text>`).join('')}
    ${[0.1, 0.5, 2, 10, 40].map(iv => `<line x1="${pL}" y1="${yOf(iv).toFixed(1)}" x2="${W - pR}" y2="${yOf(iv).toFixed(1)}" stroke="var(--chart-grid)" stroke-dasharray="2 2"/>
      <text x="${pL - 5}" y="${(yOf(iv) + 3).toFixed(1)}" fill="var(--chart-text)" font-size="9" text-anchor="end" font-family="monospace">${iv}</text>`).join('')}
    <path d="${dhLine}" fill="none" stroke="var(--chart-threshold)" stroke-width="2.2"/>
    <path d="${gzLine}" fill="none" stroke="var(--chart-q2)" stroke-width="1.5" stroke-dasharray="4 3"/>
    ${nodes.map(n => {
      const i24 = (n.max_24h_obs_mm || 0) / 24;
      const i72 = (n.max_72h_obs_mm || 0) / 72;
      let dots = '';
      if (i24 >= 0.05) dots += `<circle cx="${xOf(24).toFixed(1)}" cy="${yOf(i24).toFixed(1)}" r="3.4" fill="var(--chart-sim)"><title>${esc(n.name)} 24h: ${fmt(i24, 2)} mm/h</title></circle>`;
      if (i72 >= 0.05) dots += `<circle cx="${xOf(72).toFixed(1)}" cy="${yOf(i72).toFixed(1)}" r="3.4" fill="var(--chart-med)"><title>${esc(n.name)} 72h: ${fmt(i72, 2)} mm/h</title></circle>`;
      return dots;
    }).join('')}
    <text x="${W - pR - 4}" y="${pT + 14}" fill="var(--chart-threshold)" font-size="9.5" text-anchor="end" font-weight="700">Dahal &amp; Hasegawa (2008): I = 73.9 D⁻⁰·⁷⁹</text>
    <text x="${W - pR - 4}" y="${pT + 27}" fill="var(--chart-q2)" font-size="9" text-anchor="end" font-weight="600">Guzzetti et al. (2008): I = 2.2 D⁻⁰·⁴⁴</text>
    <text x="12" y="${pT + cH / 2}" fill="var(--chart-text)" font-size="9" transform="rotate(-90 12 ${pT + cH / 2})" text-anchor="middle">Mean intensity I (mm/h)</text>
  </svg>`;
}

function renderLandslideReviewQueue(rq) {
  const isNe = getLang() === 'ne';
  const nScanned = (rq && rq.n_records_scanned) || (S.landslides || []).length;
  const cands = (rq && Array.isArray(rq.candidates)) ? rq.candidates : [];
  const params = (rq && rq.parameters) || { max_km: 1.5, max_days: 3, undated_cross_source_max_km: 0.35 };

  const bodyHtml = cands.length
    ? `<div class="tbl-scroll"><table><thead><tr>
        <th scope="col">Candidate ID</th><th scope="col">Record A</th><th scope="col">Record B</th>
        <th scope="col">Dist km</th><th scope="col">Δ Days</th><th scope="col">Title Sim</th>
        <th scope="col">Reason</th><th scope="col">Status</th>
      </tr></thead><tbody>
      ${cands.slice(0, 100).map(c => `<tr>
        <td class="mono">${esc(c.candidate_id)}</td>
        <td class="wrap-cell"><b>${esc(c.record_a_title || c.record_a_id)}</b><div class="band">${esc(c.record_a_source || '')} · ${fmtNullDate(c.record_a_date_utc)}</div></td>
        <td class="wrap-cell"><b>${esc(c.record_b_title || c.record_b_id)}</b><div class="band">${esc(c.record_b_source || '')} · ${fmtNullDate(c.record_b_date_utc)}</div></td>
        <td class="num">${fmt(c.distance_km, 2)}</td>
        <td class="num">${c.days_apart != null ? fmt(c.days_apart, 1) : `<span class="val-unknown">${esc(t('unknownVal'))}</span>`}</td>
        <td class="num">${fmt((c.title_similarity || 0) * 100, 0)}%</td>
        <td>${esc(c.reason || 'proximity')}</td>
        <td><span class="hbadge h-mod">${esc(c.review_status || 'pending_review')}</span></td>
      </tr>`).join('')}
      </tbody></table></div>`
    : `<p class="muted">${esc(t('lsReviewEmpty', { n: fmt(nScanned) }))}</p>`;

  return `
    <details class="review-queue-panel">
      <summary>
        <span>▸ ${esc(t('lsReviewQueueTitle'))} <span class="mono">(${fmt(cands.length)} ${isNe ? 'समीक्षा बाँकी' : 'pending'} / ${fmt(nScanned)} ${isNe ? 'जाँच गरिएको' : 'scanned'})</span></span>
        <span class="badge-screening">${esc(t('lsReviewPolicyBadge'))}</span>
      </summary>
      <div class="review-queue-body">
        <div class="band field-gap">Rules: dated pairs ≤ <b>${fmt(params.max_km, 1)} km</b> &amp; ≤ <b>${fmt(params.max_days, 0)} d</b> · undated cross-source ≤ <b>${fmt(params.undated_cross_source_max_km, 2)} km</b> · <code>auto_merged: false</code></div>
        <div class="field-gap">${bodyHtml}</div>
      </div>
    </details>`;
}

function tabLandslides() {
  const isNe = getLang() === 'ne';
  const nodes = (S.hydromet && S.hydromet.nodes) || [];
  const allEvs = S.landslides || [];
  const meta = S.lsMeta || {};
  const countsByType = meta.counts_by_type || {
    landslide_event: 0,
    landslide_scar: allEvs.length,
    susceptibility_zone: 0,
    hazard_report: 0,
    coseismic_failure: 0,
  };
  const nBipad = meta.n_bipad || 0;
  const nCoolr = meta.n_nasa_coolr || 0;
  const nOsm = meta.n_osm || 0;
  const activeFilter = S.lsTypeFilter || 'all';
  const filtered = activeFilter === 'all'
    ? allEvs
    : allEvs.filter(e => (e.feature_type || 'landslide_scar') === activeFilter);
  const evs = filtered.slice(0, 150);

  return `${(nCoolr === 0 && nBipad === 0) ? `<div class="callout"><b>${esc(meta.coverage_note || t('coolrZeroNotice', { n: fmt(nOsm || allEvs.length) }))}</b></div>` : ''}
    <div class="split-2">
      <div>
        <h4>Nepal Himalaya Liquid-Rain I–D Threshold Diagram</h4>
        ${idCurveSvg(nodes)}
        <p class="muted field-gap">Plots 24 h (blue) and 72 h (teal) liquid-rain intensities across 24 sentinel zones against Dahal &amp; Hasegawa (2008). Updated ${esc(fmtNpt(S.hydromet && S.hydromet.updated_utc))} (${esc(fmtAge(S.hydromet && S.hydromet.updated_utc))}).</p>
        ${meta.null_semantics_note ? `<div class="callout info"><b>Epistemic Null Policy:</b> ${esc(meta.null_semantics_note)}</div>` : ''}
      </div>
      <div>
        <h4>Physiographic Rainfall–Landslide Watch (24 Sentinel Nodes) <span class="badge-screening">${esc(t('modelledBadge'))}</span></h4>
        <div class="tbl-scroll"><table><thead><tr>
          <th scope="col">Station</th><th scope="col">District</th><th scope="col">Past 7d mm</th>
          <th scope="col">Next 5d mm</th><th scope="col">Max 24h</th><th scope="col">Soil</th>
          <th scope="col">0 °C level</th><th scope="col">D–H Status</th>
        </tr></thead><tbody>
        ${nodes.map(n => {
          const dh = n.dh_combined || n.dh_obs || {};
          const lv = dh.level || 'low';
          return `<tr tabindex="0" data-node="${esc(n.id)}" class="${n.id === S.sel && S.selKind === 'node' ? 'sel' : ''}">
            <td><b>${esc(n.name)}</b></td>
            <td>${esc(tDistrict(n.district, S.districtsMeta))}</td>
            <td class="num">${fmt(n.rain_past_7d_mm, 1)}</td>
            <td class="num">${fmt(n.rain_next_5d_mm, 1)}</td>
            <td class="num">${fmt(n.max_24h_obs_mm, 1)}</td>
            <td class="num">${fmt(n.soil_moisture_m3m3, 2)}</td>
            <td class="num">${fmt(n.freezing_level_m, 0)} m</td>
            <td><span class="hbadge ${DHCLASS[lv] || 'h-low'}">${esc(tDhLevel(lv))} (${fmt((dh.max_ratio || 0) * 100, 0)}%)</span></td>
          </tr>`;
        }).join('')}
        </tbody></table></div>

        <div class="tbl-toolbar field-gap">
          <h4>5-Type Landslide Inventory (${fmt(allEvs.length)} total · BIPAD: ${fmt(nBipad)} · COOLR: ${fmt(nCoolr)} · OSM: ${fmt(nOsm)})</h4>
          <a class="btn sm pri" href="data/landslide_inventory.geojson" download="landslide_inventory.geojson">${esc(t('lsDownloadGeojson'))}</a>
        </div>

        <div class="ls-type-bar" role="group" aria-label="Filter landslide inventory by 5 canonical feature types">
          <button type="button" class="ls-type-chip${activeFilter === 'all' ? ' on' : ''}" data-ls-type="all">
            <span>${esc(t('lsTypeAll'))}</span><span class="ls-type-count">${fmt(allEvs.length)}</span>
          </button>
          ${LS_TYPE_ORDER.map(ft => `<button type="button" class="ls-type-chip${activeFilter === ft ? ' on' : ''}" data-ls-type="${esc(ft)}">
            <span>${esc(tLandslideType(ft))}</span><span class="ls-type-count">${fmt(countsByType[ft] || 0)}</span>
          </button>`).join('')}
        </div>

        <div class="tbl-scroll"><table><thead><tr>
          <th scope="col">Date</th><th scope="col">Type</th><th scope="col">Location / Title</th>
          <th scope="col">District</th><th scope="col">Source</th><th scope="col">Trigger</th>
          <th scope="col">Fatalities</th><th scope="col">Injuries</th>
        </tr></thead><tbody>
        ${evs.length ? evs.map(e => {
          const ttl = (isNe && e.title_ne) ? e.title_ne : (e.title || 'Landslide record');
          const dtVal = e.event_date_utc || e.date;
          return `<tr tabindex="0" data-fly="${safeFlyAttr(e.lat, e.lon, 12)}">
            <td class="mono">${fmtNullDate(dtVal)}</td>
            <td>${badgeLsType(e.feature_type)}</td>
            <td class="wrap-cell">${esc(ttl)}${e.verified === true ? ' <span class="hbadge h-low">✓</span>' : ''}</td>
            <td>${esc(tDistrict(e.district || e.admin, S.districtsMeta))}</td>
            <td>${esc(e.source || '—')}</td>
            <td>${esc(e.trigger || '—')}</td>
            <td class="num">${fmtNullCount(e.fatalities)}</td>
            <td class="num">${fmtNullCount(e.injuries)}</td>
          </tr>`;
        }).join('') : `<tr><td colspan="8" class="muted">${isNe ? 'यस प्रकारमा हाल ० अभिलेख छन्।' : '0 records currently loaded in this feature type.'}</td></tr>`}
        </tbody></table></div>

        ${renderLandslideReviewQueue(S.lsReviewQueue)}
      </div>
    </div>`;
}

/* ==========================================================================
   14b. Cascades, Road-Cut Hospital Isolation & Tsho Rolpa 2D Pilot Tab
   ========================================================================== */
function svgWrapTwoLines(text, maxChars = 28) {
  const s = String(text || '').trim();
  if (s.length <= maxChars) return [s];
  const words = s.split(/\s+/);
  let line1 = '';
  let idx = 0;
  while (idx < words.length && (line1 + (line1 ? ' ' : '') + words[idx]).length <= maxChars) {
    line1 += (line1 ? ' ' : '') + words[idx];
    idx++;
  }
  if (!line1) {
    line1 = s.slice(0, maxChars);
    const rest = s.slice(maxChars);
    return [line1, rest.length > maxChars ? rest.slice(0, maxChars - 1) + '…' : rest];
  }
  const rest = words.slice(idx).join(' ');
  return rest ? [line1, rest.length > maxChars + 2 ? rest.slice(0, maxChars + 1) + '…' : rest] : [line1];
}

const CASCADE_NODE_POS = {
  c1_heavy_rain_dh: { x: 24, y: 38 },
  c1_dated_landslides: { x: 24, y: 90 },
  c1_debris_dam_valley_flood: { x: 344, y: 64 },
  c1_road_bridge_isolation: { x: 664, y: 64 },

  c2_recent_eq_m45: { x: 24, y: 164 },
  c2_coseismic_slope_moraine: { x: 344, y: 164 },
  c2_corridor_access_cut: { x: 664, y: 164 },

  c3_glof_high_susceptibility: { x: 24, y: 244 },
  c3_glof_thermal_seismic_driver: { x: 24, y: 298 },
  c3_glof_bridge_hydro_impact: { x: 344, y: 271 },
  c3_hospital_access_disruption: { x: 664, y: 271 },
};

function buildCascadeGraphSvg(cas) {
  const isNe = getLang() === 'ne';
  const nodes = (cas && Array.isArray(cas.nodes)) ? cas.nodes : [];
  const edges = (cas && Array.isArray(cas.edges)) ? cas.edges : [];
  const nodeW = 232;
  const nodeH = 46;
  const sel = S.cascadeSel || {};

  const evStroke = ev => (ev === 'observed' ? 'var(--cg-obs)' : ev === 'forecast' ? 'var(--cg-fc)' : 'var(--cg-mod)');
  const evDash = ev => (ev === 'observed' ? '' : ev === 'forecast' ? '6 3' : '2 3');
  const evMarker = ev => (ev === 'observed' ? 'url(#cg-arrow-obs)' : ev === 'forecast' ? 'url(#cg-arrow-fc)' : 'url(#cg-arrow-mod)');

  const edgesSvg = edges.map(ed => {
    const p1 = CASCADE_NODE_POS[ed.from];
    const p2 = CASCADE_NODE_POS[ed.to];
    if (!p1 || !p2) return '';
    const x1 = p1.x + nodeW;
    const y1 = p1.y + nodeH / 2;
    const x2 = p2.x - 5;
    const y2 = p2.y + nodeH / 2;
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    const col = evStroke(ed.evidence_type);
    const dash = evDash(ed.evidence_type);
    const sw = ed.active ? 2.6 : 1.5;
    const op = ed.active ? 1.0 : 0.62;
    const isSel = sel.kind === 'edge' && sel.id === ed.rule_id;
    return `<g class="cg-edge-hit${isSel ? ' is-selected' : ''}" tabindex="0" role="button" data-cg-edge="${esc(ed.rule_id)}" aria-label="${esc(ed.rule_id)} (${esc(tEvidenceType(ed.evidence_type))})">
      <path d="M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}" fill="none" stroke="${col}" stroke-width="${sw}" ${dash ? `stroke-dasharray="${dash}"` : ''} opacity="${op}" marker-end="${evMarker(ed.evidence_type)}"/>
      <rect class="cg-pill-rect" x="${(mx - 27).toFixed(1)}" y="${(my - 9).toFixed(1)}" width="54" height="18" rx="9" fill="var(--panel)" stroke="${col}" stroke-width="${ed.active ? 1.8 : 1.1}"/>
      <text x="${mx.toFixed(1)}" y="${(my + 3.2).toFixed(1)}" text-anchor="middle" fill="${col}" font-size="8.5" font-weight="700" font-family="monospace">${esc(ed.rule_id)}</text>
    </g>`;
  }).join('');

  const nodesSvg = nodes.map(nd => {
    const pos = CASCADE_NODE_POS[nd.id];
    if (!pos) return '';
    const label = isNe ? (nd.label_ne || nd.label_en) : (nd.label_en || nd.id);
    const lines = svgWrapTwoLines(label, isNe ? 24 : 30);
    const isSel = sel.kind === 'node' && sel.id === nd.id;
    const dotCol = (nd.severity === 'critical' || nd.severity === 'high')
      ? 'var(--bad)'
      : (nd.active ? 'var(--warn)' : evStroke(nd.evidence_type));
    const txtSvg = lines.length === 1
      ? `<text x="${pos.x + 14}" y="${pos.y + 26}" fill="var(--ink)" font-size="10.2" font-weight="600">${esc(lines[0])}</text>`
      : `<text x="${pos.x + 14}" y="${pos.y + 20}" fill="var(--ink)" font-size="9.8" font-weight="600">${esc(lines[0])}</text>
         <text x="${pos.x + 14}" y="${pos.y + 33}" fill="var(--ink)" font-size="9.8" font-weight="600">${esc(lines[1])}</text>`;
    return `<g class="cg-node${nd.active ? ' is-active' : ''}${isSel ? ' is-selected' : ''}" tabindex="0" role="button" data-cg-node="${esc(nd.id)}" aria-label="${esc(label)}">
      <rect class="cg-box" x="${pos.x}" y="${pos.y}" width="${nodeW}" height="${nodeH}" rx="6"/>
      <circle cx="${pos.x + 8}" cy="${pos.y + 12}" r="3.4" fill="${dotCol}"/>
      ${txtSvg}
      <text x="${pos.x + nodeW - 6}" y="${pos.y + 11}" text-anchor="end" fill="${evStroke(nd.evidence_type)}" font-size="8" font-weight="700" font-family="monospace">${esc(tEvidenceType(nd.evidence_type).toUpperCase())}</text>
    </g>`;
  }).join('');

  return `<svg class="cascade-svg" viewBox="0 0 920 364" role="img" aria-label="Directed multi-hazard cascade screening graph">
    <defs>
      <marker id="cg-arrow-obs" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--cg-obs)"/>
      </marker>
      <marker id="cg-arrow-fc" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--cg-fc)"/>
      </marker>
      <marker id="cg-arrow-mod" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--cg-mod)"/>
      </marker>
    </defs>

    <text x="140" y="16" text-anchor="middle" fill="var(--chart-text)" font-size="9.5" font-weight="700" font-family="monospace">STAGE 1 · TRIGGER</text>
    <text x="460" y="16" text-anchor="middle" fill="var(--chart-text)" font-size="9.5" font-weight="700" font-family="monospace">STAGE 2 · INTERMEDIATE MECHANISM</text>
    <text x="780" y="16" text-anchor="middle" fill="var(--chart-text)" font-size="9.5" font-weight="700" font-family="monospace">STAGE 3 · CORRIDOR &amp; HOSPITAL IMPACT</text>

    <rect x="12" y="26" width="896" height="116" rx="8" fill="var(--panel2)" fill-opacity="0.42" stroke="var(--line)" stroke-dasharray="3 3"/>
    <text x="20" y="34" fill="var(--ink3)" font-size="8.2" font-weight="700" font-family="monospace">CHAIN 1 · RAINFALL → LANDSLIDE / DEBRIS DAM → ROAD ISOLATION</text>

    <rect x="12" y="150" width="896" height="72" rx="8" fill="var(--panel2)" fill-opacity="0.42" stroke="var(--line)" stroke-dasharray="3 3"/>
    <text x="20" y="160" fill="var(--ink3)" font-size="8.2" font-weight="700" font-family="monospace">CHAIN 2 · M≥4.5 EARTHQUAKE → COSEISMIC SLOPE / MORAINE → ACCESS CUT</text>

    <rect x="12" y="230" width="896" height="124" rx="8" fill="var(--panel2)" fill-opacity="0.42" stroke="var(--warn-bd)" stroke-dasharray="3 3"/>
    <text x="20" y="240" fill="var(--warn)" font-size="8.2" font-weight="700" font-family="monospace">CHAIN 3 · GLOF SUSCEPTIBILITY (+ THERMAL/SEISMIC) → BRIDGES &amp; HYDRO → HOSPITAL ISOLATION</text>

    ${edgesSvg}
    ${nodesSvg}
  </svg>`;
}

function badgeCascadeSeverity(sev, baselineCls = 'h-na') {
  const s = String(sev || 'baseline').toLowerCase();
  if (s === 'critical') return 'h-vhigh';
  if (s === 'high') return 'h-high';
  if (s === 'moderate' || s === 'watch') return 'h-mod';
  return baselineCls;
}

function cascadeCardSeverityClass(sev) {
  const s = String(sev || 'baseline').toLowerCase();
  if (s === 'critical' || s === 'high') return 'is-alert';
  if (s === 'moderate' || s === 'watch') return 'is-watch';
  return '';
}

function renderCascadeInspector(cas) {
  const isNe = getLang() === 'ne';
  const nodes = (cas && Array.isArray(cas.nodes)) ? cas.nodes : [];
  const edges = (cas && Array.isArray(cas.edges)) ? cas.edges : [];
  const nodeById = new Map(nodes.map(n => [n.id, n]));
  const sel = S.cascadeSel || {};

  if (sel.kind === 'node') {
    const nd = nodeById.get(sel.id) || nodes[0];
    if (!nd) return `<p class="muted">${esc(t('cascClickHint'))}</p>`;
    const label = isNe ? (nd.label_ne || nd.label_en) : nd.label_en;
    const metrics = nd.metrics || {};
    const metricRows = Object.entries(metrics)
      .filter(([, v]) => typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
      .map(([k, v]) => `<span>${esc(k.replaceAll('_', ' '))}</span><b>${esc(String(v))}</b>`)
      .join('');
    const dists = Array.isArray(nd.affected_districts) ? nd.affected_districts : [];
    const ndBadgeCls = badgeCascadeSeverity(nd.severity, nd.active ? 'h-mod' : 'h-na');
    const ndStatusLabel = nd.active
      ? (nd.severity && nd.severity !== 'baseline' ? `Active (${nd.severity})` : 'Active Watch')
      : 'Baseline';
    return `
      <h5>${esc(label)}</h5>
      <div class="badge-row">
        ${badgeEvidence(nd.evidence_type)}
        <span class="hbadge ${ndBadgeCls}">${esc(ndStatusLabel)}</span>
        <span class="hbadge h-info">${esc(nd.stage || '')}</span>
      </div>
      ${metricRows ? `<div class="kv">${metricRows}</div>` : ''}
      ${dists.length ? `<div class="band field-gap">Affected districts (${fmt(dists.length)}):</div>
        <div class="district-chips">${dists.slice(0, 12).map(d => `<button type="button" class="district-chip" data-open-dist="${esc(d)}">${esc(tDistrict(d, S.districtsMeta))}</button>`).join('')}${dists.length > 12 ? `<span class="band">+${fmt(dists.length - 12)}</span>` : ''}</div>` : '<p class="muted field-gap">0 districts currently triggered on this node.</p>'}`;
  }

  const ed = edges.find(e => e.rule_id === sel.id) || edges.find(e => e.active) || edges[0];
  if (!ed) return `<p class="muted">${esc(t('cascClickHint'))}</p>`;
  const fromNd = nodeById.get(ed.from);
  const toNd = nodeById.get(ed.to);
  const fromLbl = fromNd ? (isNe ? (fromNd.label_ne || fromNd.label_en) : fromNd.label_en) : ed.from;
  const toLbl = toNd ? (isNe ? (toNd.label_ne || toNd.label_en) : toNd.label_en) : ed.to;
  const sup = ed.supporting_evidence || {};
  const supDists = Array.isArray(sup.affected_districts) ? sup.affected_districts : (Array.isArray(sup.districts) ? sup.districts : []);

  return `
    <h5>${esc(t('cascInspectorTitle'))} · <code>${esc(ed.rule_id)}</code></h5>
    <div class="badge-row">
      ${badgeEvidence(ed.evidence_type)}
      <span class="hbadge ${ed.active ? 'h-mod' : 'h-na'}">${ed.active ? 'Active' : 'Baseline'}</span>
      <span class="hbadge h-info">Confidence: ${esc(ed.confidence || 'moderate')}</span>
    </div>
    <div class="muted"><b>${esc(fromLbl)}</b> → <b>${esc(toLbl)}</b></div>
    <div class="callout info field-gap"><b>Physical Trigger Rule:</b> <code>${esc(ed.trigger_rule)}</code></div>
    <p class="muted"><b>Uncertainty:</b> ${esc(ed.uncertainty_note)}</p>
    ${supDists.length ? `<div class="band">Affected districts (${fmt(supDists.length)}):</div>
      <div class="district-chips">${supDists.slice(0, 12).map(d => `<button type="button" class="district-chip" data-open-dist="${esc(d)}">${esc(tDistrict(d, S.districtsMeta))}</button>`).join('')}${supDists.length > 12 ? `<span class="band">+${fmt(supDists.length - 12)}</span>` : ''}</div>` : ''}`;
}

function renderExposureIsolationSection(ei) {
  if (!ei) return '<p class="muted">Exposure &amp; road-cut isolation screening dataset unavailable.</p>';
  const sum = ei.summary || {};
  const unc = ei.uncertainty_and_coverage_limits || {};
  const view = S.isoView === 'districts' ? 'districts' : 'lakes';

  let tblHtml = '';
  if (view === 'lakes') {
    const lakeEntries = Object.values(ei.lakes || {}).sort((a, b) => {
      const pA = a.hazard_susceptibility_static && a.hazard_susceptibility_static.priority ? 1 : 0;
      const pB = b.hazard_susceptibility_static && b.hazard_susceptibility_static.priority ? 1 : 0;
      if (pA !== pB) return pB - pA;
      const isoA = (a.road_cut_hospital_isolation && a.road_cut_hospital_isolation.upstream_settlements_potentially_isolated) || 0;
      const isoB = (b.road_cut_hospital_isolation && b.road_cut_hospital_isolation.upstream_settlements_potentially_isolated) || 0;
      return isoB - isoA;
    }).slice(0, 45);

    tblHtml = `<div class="tbl-scroll"><table><thead><tr>
      <th scope="col">Lake / Corridor</th><th scope="col">District</th><th scope="col">Published Hazard</th>
      <th scope="col">Isolation Risk</th><th scope="col">Bridges (Veh / ≤250m)</th><th scope="col">Isolated Settlements</th>
      <th scope="col">Nearest Hosp (med/max)</th><th scope="col">Hydro MW</th><th scope="col">Critical Bridges / Settlements</th>
    </tr></thead><tbody>
    ${lakeEntries.map(lk => {
      const hz = lk.hazard_susceptibility_static || {};
      const exp = lk.corridor_exposure_screening || {};
      const iso = lk.road_cut_hospital_isolation || {};
      const rCls = iso.corridor_disruption_risk === 'high' ? 'h-vhigh' : iso.corridor_disruption_risk === 'moderate' ? 'h-mod' : 'h-low';
      const brNames = (iso.critical_bridge_examples || []).slice(0, 2).map(x => x.name).filter(Boolean).join(', ');
      const stNames = (iso.isolated_settlement_examples || []).slice(0, 2).map(x => x.name).filter(Boolean).join(', ');
      return `<tr tabindex="0" data-lake="${esc(lk.lake_id)}">
        <td><b>${esc(lk.name || lk.lake_id)}</b>${hz.priority ? ' <span class="hbadge h-vhigh">PFV ≥10</span>' : ''}</td>
        <td>${esc(tDistrict(lk.district, S.districtsMeta))}</td>
        <td><span class="hbadge ${HCLASS[hz.hazard] || 'h-na'}">${esc(tTier(hz.hazard))}</span></td>
        <td><span class="hbadge ${rCls}">${esc(iso.corridor_disruption_risk || 'low')}</span></td>
        <td class="num"><b>${fmt(iso.bridges_at_corridor_crossing)}</b> <span class="band">(${fmt(iso.vehicular_bridges_at_crossing)} / ${fmt(iso.critical_channel_bridges_250m)})</span></td>
        <td class="num"><b>${fmt(iso.upstream_settlements_potentially_isolated)}</b> / ${fmt(exp.settlements)}</td>
        <td class="num">${iso.nearest_hospital_km != null ? `${fmt(iso.nearest_hospital_km, 1)} / ${fmt(iso.nearest_hospital_max_km, 1)} km` : '—'}</td>
        <td class="num">${exp.hydropower_mw_tagged ? fmt(exp.hydropower_mw_tagged, 1) : '—'}</td>
        <td class="wrap-cell"><span class="band">${esc([brNames ? `Bridges: ${brNames}` : '', stNames ? `Settlements: ${stNames}` : ''].filter(Boolean).join(' · ') || '—')}</span></td>
      </tr>`;
    }).join('')}
    </tbody></table></div>`;
  } else {
    const riskRank = { high: 3, moderate: 2, low: 1, none: 0 };
    const distRows = (ei.districts || []).slice().sort((a, b) => {
      const d = (riskRank[b.district_isolation_risk] ?? 0) - (riskRank[a.district_isolation_risk] ?? 0);
      if (d !== 0) return d;
      return (b.unique_settlements_potentially_isolated || 0) - (a.unique_settlements_potentially_isolated || 0);
    });

    tblHtml = `<div class="tbl-scroll"><table><thead><tr>
      <th scope="col">District</th><th scope="col">Province</th><th scope="col">Isolation Risk</th>
      <th scope="col">Corridors (High)</th><th scope="col">Bridges (Vehicular)</th><th scope="col">Isolated / Corridor Settlements</th>
      <th scope="col">Nearest Hosp (med/max)</th><th scope="col">Health (Hosp)</th><th scope="col">Hydro MW</th>
    </tr></thead><tbody>
    ${distRows.map(d => {
      const rCls = d.district_isolation_risk === 'high' ? 'h-vhigh' : d.district_isolation_risk === 'moderate' ? 'h-mod' : d.district_isolation_risk === 'low' ? 'h-low' : 'h-na';
      return `<tr tabindex="0" data-dist="${esc(d.name)}">
        <td><b>${esc(tDistrict(d.name, S.districtsMeta))}</b></td>
        <td>${esc(tProvince(d.prov, S.districtsMeta))}</td>
        <td><span class="hbadge ${rCls}">${esc(d.district_isolation_risk)}</span></td>
        <td class="num">${fmt(d.n_routed_corridors)} <span class="band">(${fmt(d.n_high_disruption_corridors)})</span></td>
        <td class="num">${fmt(d.unique_bridges_at_crossings)} <span class="band">(${fmt(d.unique_vehicular_bridges_at_crossings)})</span></td>
        <td class="num"><b>${fmt(d.unique_settlements_potentially_isolated)}</b> / ${fmt(d.unique_settlements_in_1km_corridors)}</td>
        <td class="num">${d.nearest_hospital_km != null ? `${fmt(d.nearest_hospital_km, 1)} / ${fmt(d.nearest_hospital_max_km, 1)} km` : '—'}</td>
        <td class="num">${fmt(d.unique_health_facilities_in_corridors)} (${fmt(d.unique_hospitals_in_corridors)})</td>
        <td class="num">${d.hydropower_mw_exposed ? fmt(d.hydropower_mw_exposed, 1) : '—'}</td>
      </tr>`;
    }).join('')}
    </tbody></table></div>`;
  }

  return `
    <section class="v2-section">
      <div class="v2-section-head">
        <h4><span>⛓ ${esc(t('isoSectionTitle'))}</span> ${badgeDataClass('static_assessment')}</h4>
        <div class="seg-toggle" role="group" aria-label="Toggle corridor vs district isolation view">
          <button type="button" class="seg-btn${view === 'lakes' ? ' on' : ''}" data-iso-view="lakes">${esc(t('isoTabLakes'))}</button>
          <button type="button" class="seg-btn${view === 'districts' ? ' on' : ''}" data-iso-view="districts">${esc(t('isoTabDistricts'))}</button>
        </div>
      </div>

      <div class="corridor-disclaimer">
        <span class="hbadge h-mod">${esc(t('isoCorridorBadge'))}</span>
        <div class="muted field-gap">${esc(unc.osm_completeness_caveat || ei.methodology_notice || '')}</div>
      </div>

      <div class="mini-kpis">
        <div class="mini-kpi"><div class="mini-kpi-lbl">Routed Corridors</div><div class="mini-kpi-val">${fmt(sum.n_routed_lakes_analyzed)}</div></div>
        <div class="mini-kpi"><div class="mini-kpi-lbl">High Disruption Corridors</div><div class="mini-kpi-val text-bad">${fmt(sum.corridor_disruption_risk_counts && sum.corridor_disruption_risk_counts.high)}</div></div>
        <div class="mini-kpi"><div class="mini-kpi-lbl">High-Isolation Districts</div><div class="mini-kpi-val text-bad">${fmt(sum.district_isolation_risk_counts && sum.district_isolation_risk_counts.high)} / 77</div></div>
        <div class="mini-kpi"><div class="mini-kpi-lbl">Settlements Potentially Isolated</div><div class="mini-kpi-val">${fmt(sum.total_unique_settlements_potentially_isolated)}</div></div>
        <div class="mini-kpi"><div class="mini-kpi-lbl">Crossing Bridges (OSM)</div><div class="mini-kpi-val">${fmt(sum.total_unique_bridges_at_crossings)}</div></div>
        <div class="mini-kpi"><div class="mini-kpi-lbl">Tagged Hydropower</div><div class="mini-kpi-val">${fmt(sum.total_unique_hydropower_mw_in_corridors, 1)} MW</div></div>
      </div>

      ${tblHtml}
    </section>`;
}

function renderTshoRolpaPilotSection(trp) {
  if (!trp) return '';
  const isNe = getLang() === 'ne';
  const lid = trp.lake_identification || {};
  const inv = trp.traya_inventory_parameters || {};
  const pub = trp.published_peer_reviewed_benchmarks || {};
  const bathy = pub.bathymetry_and_geometry || {};
  const eng = pub.engineering_mitigation_2000 || {};
  const reqs = trp.pre_simulation_2d_requirements || {};
  const cps = Array.isArray(trp.valley_checkpoints) ? trp.valley_checkpoints : [];
  const scns = Array.isArray(trp.breach_scenario_framework) ? trp.breach_scenario_framework : [];
  const volRange = Array.isArray(bathy.surveyed_volume_Mm3_range) ? bathy.surveyed_volume_Mm3_range : [];

  return `
    <section class="v2-section">
      <div class="v2-section-head">
        <h4><span>🏔 ${esc(t('pilotTitle'))}</span> <span class="dc-badge dc-static">${esc(t('pilotBadge'))}</span></h4>
        <div class="btn-row">
          <button type="button" class="btn sm pri" data-open-lake="${esc(lid.matched_inventory_id || 'GL_27.86029_86.47725')}">${esc(t('pilotFlyLake'))}</button>
          <a class="btn sm" href="${esc(TSHO_ROLPA_PLAN_URL)}" target="_blank" rel="noopener noreferrer">${esc(t('pilotStudyPlanLink'))}</a>
        </div>
      </div>

      <div class="pilot-card">
        <div class="badge-row">
          <span class="hbadge h-vhigh">Hazard: ${esc(tTier(inv.hazard_published || 'very high'))}</span>
          <span class="hbadge h-info">Target Solvers: ${esc((trp.target_solvers || ['LISFLOOD-FP', 'BASEMENT']).join(' · '))}</span>
          <span class="hbadge h-mod">Ice-Cored Moraine · SLA ${fmt(inv.sla_max_angle_deg, 1)}°</span>
          <span class="band">${esc(lid.river_basin || 'Rolwaling Khola → Tama Koshi → Sun Koshi')}</span>
        </div>
        <p class="muted field-gap">${esc(trp.status_note || '')}</p>

        <div class="pilot-grid">
          <div class="pilot-box">
            <h5>Published Rolwaling Bathymetry &amp; Parameters</h5>
            <div class="kv">
              <span>Elevation / Area</span><b>${fmt(lid.elevation_m, 0)} m · ${fmt(inv.area_km2, 2)} km²</b>
              <span>Surveyed Volume (Yamada/ICIMOD)</span><b>${volRange.length === 2 ? `${fmt(volRange[0], 1)}–${fmt(volRange[1], 1)} Mm³` : '76.6–85.9 Mm³'}</b>
              <span>Surveyed Max / Mean Depth</span><b>${fmt(bathy.surveyed_max_depth_m, 0)} / ${fmt(bathy.surveyed_mean_depth_m, 1)} m</b>
              <span>TRĀYA PFV (Fujita 2013)</span><b>${fmt(inv.pfv_Mm3, 2)} Mm³ (Hp ${fmt(inv.hp_m, 1)} m)</b>
              <span>Veh Median Qp (95% CI)</span><b>${fmt(inv.veh_qp_median_m3s, 0)} m³/s</b>
            </div>
            <p class="band field-gap">${esc((bathy.comparison_with_traya_empirical_scaling && bathy.comparison_with_traya_empirical_scaling.volume_bias_note) || '')}</p>
          </div>

          <div class="pilot-box">
            <h5>2000 Engineering Spillway Lowering History</h5>
            <div class="kv">
              <span>Intervention</span><b>${esc(eng.intervention || '3.0 m open gated spillway')}</b>
              <span>Completed</span><b>${fmt(eng.completion_year, 0)}</b>
              <span>Agencies</span><b>${esc(eng.implementing_agencies || 'Nepal DHM / WECS')}</b>
            </div>
            <p class="muted field-gap">${esc(eng.residual_risk_note || '')}</p>
          </div>

          <div class="pilot-box">
            <h5>2D Hydrodynamic Prerequisites (Pre-Simulation)</h5>
            <ul class="trig-list">
              ${(reqs.required_inputs_for_lisflood_basement || []).slice(0, 4).map(item => `<li>${esc(item)}</li>`).join('')}
            </ul>
          </div>
        </div>

        <h5 class="field-gap">4-Tier Breach Scenario Framework (Pre-Simulation Boundary Hydrographs)</h5>
        <div class="tbl-scroll"><table><thead><tr>
          <th scope="col">Scenario</th><th scope="col">Breach Fraction</th><th scope="col">Approx Depth</th>
          <th scope="col">TRĀYA Qp (m³/s)</th><th scope="col">Published Analog</th><th scope="col">2D Solver Role</th>
        </tr></thead><tbody>
        ${scns.map(sc => `<tr>
          <td><b>${esc(sc.scenario_id)}</b><div class="band">${esc(sc.label)}</div></td>
          <td class="num">${fmt((sc.breach_fraction || 0) * 100, 0)}%</td>
          <td class="num">${fmt(sc.approx_breach_depth_m, 1)} m</td>
          <td class="num"><b>${fmt(sc.traya_empirical_qp_m3s, 0)}</b></td>
          <td class="wrap-cell">${esc(sc.published_analog || '')}</td>
          <td class="wrap-cell">${esc(sc.target_2d_solver_role || '')}</td>
        </tr>`).join('')}
        </tbody></table></div>

        <h5 class="field-gap">Rolwaling–Tama Koshi Downstream Checkpoints (${fmt(cps.length)} benchmarks — click row to fly)</h5>
        <div class="tbl-scroll"><table><thead><tr>
          <th scope="col">Checkpoint</th><th scope="col">District</th><th scope="col">River km</th>
          <th scope="col">Elev m</th><th scope="col">Arrival (10 / 5 / 2 m/s)</th><th scope="col">Operational Significance</th>
        </tr></thead><tbody>
        ${cps.map(cp => {
          const arr = cp.first_order_arrival_bracket || {};
          const cpName = isNe && cp.name_ne ? `${cp.name_ne} (${cp.name})` : cp.name;
          return `<tr tabindex="0" data-fly="${safeFlyAttr(cp.lat, cp.lon, 12)}">
            <td><b>${esc(cpName)}</b>${cp.capacity_mw ? ` <span class="hbadge h-high">${fmt(cp.capacity_mw, 0)} MW</span>` : ''}</td>
            <td>${esc(tDistrict(cp.district, S.districtsMeta))}</td>
            <td class="num"><b>${fmt(cp.along_river_km, 1)}</b></td>
            <td class="num">${cp.approx_elev_m != null ? fmt(cp.approx_elev_m, 0) : '—'}</td>
            <td class="num mono">${fmt(arr.fast_10ms_min, 0)}m / <b>${fmt(arr.observed_ref_5ms_min, 0)}m</b> / ${fmt(arr.slow_2ms_min, 0)}m</td>
            <td class="wrap-cell">${esc(cp.significance || '')}</td>
          </tr>`;
        }).join('')}
        </tbody></table></div>
      </div>
    </section>`;
}

function tabCascades() {
  const isNe = getLang() === 'ne';
  const cas = S.cascades;
  if (!cas) return '<p class="muted">Cascade dataset unavailable.</p>';

  const sum = cas.summary || {};
  const chains = Object.values(cas.chains || {});
  const edges = Array.isArray(cas.edges) ? cas.edges : [];
  const activeScenarios = Array.isArray(cas.active_scenarios) ? cas.active_scenarios : [];
  const headSevCls = badgeCascadeSeverity(sum.highest_severity, 'h-low');

  return `
    <section class="v2-section">
      <div class="v2-section-head">
        <h4><span>⇶ ${esc(t('cascGraphTitle'))}</span> <span class="hbadge ${headSevCls}">${esc(sum.highest_severity || 'baseline')}</span></h4>
        <div class="badge-row">
          <span class="band mono">${fmt(sum.n_chains)} chains · ${fmt(sum.n_nodes)} nodes · ${fmt(sum.n_edges)} rules (${fmt(sum.n_active_edges)} active / ${fmt(sum.n_active_dynamic_edges)} dynamic)</span>
        </div>
      </div>

      <div class="callout info"><b>Epistemic Scope:</b> ${esc(cas.epistemic_notice || '')}</div>

      <div class="cascade-layout">
        <div>
          <div class="cascade-svg-wrap">
            ${buildCascadeGraphSvg(cas)}
          </div>
          <div class="cascade-legend">
            <span><span class="cg-leg-swatch"></span><b>${esc(t('evObserved'))}</b> (solid)</span>
            <span><span class="cg-leg-swatch fc"></span><b>${esc(t('evForecast'))}</b> (dashed)</span>
            <span><span class="cg-leg-swatch mod"></span><b>${esc(t('evModelled'))}</b> (dotted)</span>
            <span class="band">${esc(t('cascClickHint'))}</span>
          </div>
        </div>
        <div id="cascadeInspector" class="cascade-inspector" aria-live="polite">
          ${renderCascadeInspector(cas)}
        </div>
      </div>

      <h4 class="field-gap">${esc(t('cascScenariosTitle'))}</h4>
      <div class="cascade-cards">
        ${chains.map(ch => {
          const chEdges = edges.filter(e => e.chain_id === ch.chain_id);
          const scn = activeScenarios.find(x => x.chain_id === ch.chain_id);
          const dists = Array.isArray(ch.affected_districts) ? ch.affected_districts : [];
          const ttl = isNe ? (ch.title_ne || ch.title_en) : ch.title_en;
          const sumTxt = isNe ? (ch.summary_ne || ch.summary_en) : ch.summary_en;
          const cardCls = cascadeCardSeverityClass(ch.severity);
          const cardBadgeCls = badgeCascadeSeverity(ch.severity, 'h-na');
          return `<article class="cascade-card ${cardCls}">
            <h5>${esc(ttl)}</h5>
            <div class="badge-row">
              <span class="hbadge ${cardBadgeCls}">${esc(ch.severity || 'baseline')}</span>
              ${ch.dynamic_active ? '<span class="hbadge h-high">Dynamic Trigger Active</span>' : '<span class="hbadge h-info">No Dynamic Trigger Today</span>'}
              ${scn && scn.confidence ? `<span class="band">Conf: <b>${esc(scn.confidence)}</b></span>` : ''}
            </div>
            <p class="muted">${esc(sumTxt)}</p>
            <div class="badge-row">
              ${chEdges.map(ed => `<button type="button" class="district-chip" data-cg-edge="${esc(ed.rule_id)}"><code>${esc(ed.rule_id)}</code> · ${esc(tEvidenceType(ed.evidence_type))}${ed.active ? ' ●' : ''}</button>`).join('')}
            </div>
            ${dists.length ? `<div class="district-chips">
              ${dists.slice(0, 8).map(d => `<button type="button" class="district-chip" data-open-dist="${esc(d)}">${esc(tDistrict(d, S.districtsMeta))}</button>`).join('')}
              ${dists.length > 8 ? `<span class="band">+${fmt(dists.length - 8)} more</span>` : ''}
            </div>` : ''}
          </article>`;
        }).join('')}
      </div>
    </section>

    ${renderExposureIsolationSection(S.exposureIso)}
    ${renderTshoRolpaPilotSection(S.tshoRolpaPilot)}`;
}

function tabLive() {
  const gf = S.gf;
  const gfUrl = gf ? safeUrl(gf.url, ['*.usgs.gov']) : '';
  const gfHead = gf ? `<div class="callout ${gf.landslide_alert === 'red' ? 'bad' : gf.landslide_alert === 'green' ? 'info' : ''}">
    <b>USGS ground-failure alert for ${esc(gf.event)}</b> — landslide alert <b>${esc(gf.landslide_alert || 'n/a')}</b>,
    aggregate hazard ${esc(gf.landslide_value || '—')}, exposed population ${esc(gf.landslide_pop || '—')};
    liquefaction alert ${esc(gf.liq_alert || 'n/a')}.
    ${gfUrl ? `<a href="${esc(gfUrl)}" target="_blank" rel="noopener noreferrer">USGS event page ↗</a>.` : ''}
    <div class="band">Operational USGS Nowicki Jessee et al. (2018) coseismic landslide &amp; Zhu et al. (2017) liquefaction model.</div>
  </div>` : '';

  const eqTbl = S.live.length
    ? `<table><thead><tr>
        <th scope="col">Time (NPT)</th><th scope="col">M</th><th scope="col">Depth km</th>
        <th scope="col">Place</th><th scope="col">Lakes ≤50 km</th><th scope="col">USGS</th>
      </tr></thead><tbody>
      ${S.live.slice(0, 100).map(f => {
        const c = f.geometry.coordinates;
        const p = f.properties || {};
        const nNear = S.lakes.filter(l => hav(c[0], c[1], l.properties.lon, l.properties.lat) <= 50).length;
        const u = safeUrl(p.url, ['*.usgs.gov']);
        return `<tr tabindex="0" data-fly="${safeFlyAttr(c[1], c[0], 9)}">
          <td class="mono">${esc(fmtNpt(p.time))}</td>
          <td class="num"><b>${fmt(p.mag, 1)}</b></td>
          <td class="num">${fmt(c[2], 1)}</td>
          <td>${esc(p.place || '')}</td>
          <td class="num">${fmt(nNear)}</td>
          <td>${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">open ↗</a>` : '—'}</td>
        </tr>`;
      }).join('')}
      </tbody></table>`
    : '<p class="muted">No live USGS earthquakes in the selected window inside the Nepal bounding box, or the feed is offline. Also check official Nepal DMG/NEMRC bulletins at <a href="https://seismonepal.gov.np/" target="_blank" rel="noopener noreferrer">seismonepal.gov.np</a>.</p>';

  const faultNote = (S.faultsMeta && S.faultsMeta.coverage_note)
    || (S.summary && S.summary.active_faults && S.summary.active_faults.coverage_note)
    || '';
  const faults = S.faults || [];
  const m6 = S.eqHist || [];

  return `${renderOfficialAuthorityPanel({ compact: false })}
    <div class="screening-lane-head">
      <b>${esc(t('openDataSeismicHead'))}</b>
      <div class="badge-row">
        <span class="badge-screening">${esc(t('screeningBadge'))}</span>
        ${badgeDataClass(S.liveStatus === 'live' ? 'live_observation' : 'cached')}
      </div>
    </div>
    ${gfHead}
    ${faultNote ? `<div class="callout info"><b>Fault map scope:</b> ${esc(faultNote)}</div>` : ''}
    <div class="split-2">
      <div>
        <h4>GEM Active Surface Fault Traces (${fmt(faults.length)} traces)</h4>
        <table><thead><tr><th scope="col">Structure</th><th scope="col">Kinematics</th><th scope="col">Dip</th><th scope="col">Slip mm/yr</th></tr></thead><tbody>
        ${faults.slice(0, 30).map(f => {
          const p = f.properties || {};
          return `<tr><td>${esc(p.name)}</td><td>${esc(p.slip_type)}</td><td class="num">${p.dip_deg != null ? fmt(p.dip_deg, 0) + '°' : '—'}</td><td class="num">${p.slip_rate_mm_yr != null ? fmt(p.slip_rate_mm_yr, 1) : '—'}</td></tr>`;
        }).join('')}
        </tbody></table>
      </div>
      <div>
        <h4>Live USGS Earthquakes — Nepal Region (${fmt(S.live.length)} · ${esc(S.eqWindow)})</h4>
        ${eqTbl}
        <h4 class="field-gap">Historical M≥6 Earthquakes in Nepal Region (${fmt(m6.length)} events)</h4>
        <table><thead><tr><th scope="col">Year</th><th scope="col">M</th><th scope="col">Depth km</th><th scope="col">Place</th></tr></thead><tbody>
        ${m6.map(e => `<tr tabindex="0" data-fly="${safeFlyAttr(e.lat, e.lon, 8)}">
          <td class="num">${new Date(e.time).getUTCFullYear()}</td>
          <td class="num"><b>${fmt(e.mag, 1)}</b></td>
          <td class="num">${fmt(e.depth_km, 0)}</td>
          <td>${esc(e.place)}</td>
        </tr>`).join('')}
        </tbody></table>
      </div>
    </div>`;
}

function renderSentinel1SarSection(eo) {
  if (!eo || !Array.isArray(eo.lakes)) return '';
  const prov = eo.provenance || {};
  const dClass = prov.data_class || 'cached';

  return `
    <section class="sar-panel" aria-label="${esc(t('sarSectionTitle'))}">
      <div class="official-lane-head">
        <div class="official-lane-title">
          <span>📡 ${esc(t('sarSectionTitle'))}</span>
          <span class="dc-badge dc-hist">${esc(t('sarRadarBadge'))}</span>
        </div>
        <div class="badge-row">
          ${badgeDataClass(dClass)}
          <span class="band mono">S1 SAR: ${fmt(eo.n_s1_covered)}/${fmt(eo.n_priority_lakes)} · S2: ${fmt(eo.n_s2_covered)}/${fmt(eo.n_priority_lakes)} · ${esc(fmtNpt(prov.retrieved_at_utc, false))}</span>
        </div>
      </div>
      <p class="muted">C-band Synthetic Aperture Radar (Sentinel-1 GRD, Interferometric Wide Swath <code>VV/VH</code>) penetrates June–September monsoon cloud cover day and night over Tsho Rolpa and Nepal's high-hazard moraine-dammed lakes. ${esc(prov.notes || '')}</p>
      <div class="tbl-scroll field-gap"><table><thead><tr>
        <th scope="col">Priority Lake</th><th scope="col">District</th><th scope="col">Elev m</th>
        <th scope="col">SAR Mode &amp; Pol</th><th scope="col">Platform &amp; Orbit</th><th scope="col">Latest S1 Pass (NPT)</th>
        <th scope="col">Latest S2 Optical</th><th scope="col">Copernicus Links</th>
      </tr></thead><tbody>
      ${eo.lakes.map(lk => {
        const s1 = lk.sentinel1;
        const s2 = lk.sentinel2;
        const fallbackS1Url = safeUrl(
          `https://browser.dataspace.copernicus.eu/?zoom=14&lat=${Number(lk.lat).toFixed(4)}&lng=${Number(lk.lon).toFixed(4)}&datasetId=S1_AWS_IW_VVVH`,
          ['browser.dataspace.copernicus.eu']
        );
        const s1Url = safeUrl(s1 && s1.copernicus_browser_url, ['browser.dataspace.copernicus.eu']) || fallbackS1Url;
        const s2Url = safeUrl(s2 && s2.copernicus_browser_url, ['browser.dataspace.copernicus.eu']);
        const pols = (s1 && Array.isArray(s1.polarizations) && s1.polarizations.length) ? s1.polarizations : ['VV', 'VH'];
        const modeTxt = (s1 && s1.instrument_mode) ? s1.instrument_mode : 'IW';
        return `<tr tabindex="0" data-lake="${esc(lk.id)}" class="${lk.id === S.sel && S.selKind === 'lake' ? 'sel' : ''}">
          <td><b>${esc(lk.name)}</b></td>
          <td>${esc(tDistrict(lk.district, S.districtsMeta))}</td>
          <td class="num">${fmt(lk.z_m, 0)}</td>
          <td><span class="orbit-chip">${esc(modeTxt)}</span> ${pols.map(p => `<span class="pol-chip">${esc(p)}</span>`).join('')}</td>
          <td>${s1
            ? `<span class="mono">${esc(s1.platform || 'sentinel-1')}</span>${s1.orbit_state ? ` <span class="orbit-chip">${esc(s1.orbit_state)}</span>` : ''}`
            : `<span class="val-unknown">${esc(t('sarAwaitingLive'))}</span>`}</td>
          <td class="mono">${s1 && s1.datetime ? esc(fmtNpt(s1.datetime)) : `<span class="val-unknown">—</span>`}</td>
          <td class="mono">${s2 && s2.datetime ? `${esc(fmtNpt(s2.datetime, false))} (${s2.cloud_cover_pct != null ? fmt(s2.cloud_cover_pct, 1) + '%' : '—'})` : '—'}</td>
          <td>
            ${s1Url ? `<a href="${esc(s1Url)}" target="_blank" rel="noopener noreferrer">${esc(t('sarOpenBrowser'))}</a>` : '—'}
            ${s2Url ? ` · <a href="${esc(s2Url)}" target="_blank" rel="noopener noreferrer">${esc(t('sarOpenS2'))}</a>` : ''}
          </td>
        </tr>`;
      }).join('')}
      </tbody></table></div>
    </section>`;
}

function tabSat() {
  const pls = (S.hydromet && S.hydromet.priority_lakes) || [];
  const hmLakeTs = S.hydromet && (S.hydromet.priority_lakes_updated_utc || S.hydromet.updated_utc);
  return `${renderSentinel1SarSection(S.eoSar)}
  <h4>Cryosphere 0 °C Freezing-Level &amp; Optical Sentinel-2 L2A Watch (20 Priority Lakes)</h4>
  <div class="muted field-gap">
    Weekly <b>Copernicus Sentinel-2 L2A</b> cloud-screened STAC scenes (Element84 Earth Search) and <b>Open-Meteo 0 °C freezing-level altitude</b> across Nepal's 16 priority (PFV ≥ 10 Mm³) and documented ice-cored lakes (thermal/precip updated ${esc(fmtNpt(hmLakeTs))}). Click any row to fly to the lake.
  </div>
  <div class="tbl-scroll field-gap"><table><thead><tr>
    <th scope="col">Lake</th><th scope="col">District</th><th scope="col">Elev m</th><th scope="col">PFV Mm³</th>
    <th scope="col">0 °C max</th><th scope="col">Thermal margin</th><th scope="col">12d rain / snow</th>
    <th scope="col">Clearest S2</th><th scope="col">Cloud %</th><th scope="col">Copernicus</th>
  </tr></thead><tbody>
  ${pls.map(lk => {
    const s2 = lk.sentinel2 || {};
    const cUrl = safeUrl(s2.copernicus_browser_url, ['browser.dataspace.copernicus.eu']);
    return `<tr tabindex="0" data-lake="${esc(lk.id)}" class="${lk.id === S.sel && S.selKind === 'lake' ? 'sel' : ''}">
      <td><b>${esc(lk.name)}</b> ${lk.ice_cored ? '<span class="hbadge h-info">ice-core</span>' : ''}</td>
      <td>${esc(tDistrict(lk.district, S.districtsMeta))}</td>
      <td class="num">${fmt(lk.z_m, 0)}</td>
      <td class="num">${fmt(lk.pfv_Mm3, 1)}</td>
      <td class="num">${fmt(lk.freezing_level_max_m, 0)} m</td>
      <td class="num ${lk.warm_rain_on_ice ? 'text-bad' : ''}">${lk.freezing_margin_m > 0 ? '+' : ''}${fmt(lk.freezing_margin_m, 0)} m</td>
      <td class="num">${fmt(lk.liquid_rain_12d_mm, 1)} mm / ${fmt(lk.snowfall_12d_cm, 1)} cm</td>
      <td class="mono">${esc(fmtNpt(s2.datetime, false))}</td>
      <td class="num">${s2.cloud_cover_pct != null ? fmt(s2.cloud_cover_pct, 1) + '%' : '—'}</td>
      <td>${cUrl ? `<a href="${esc(cUrl)}" target="_blank" rel="noopener noreferrer">open ↗</a>` : '—'}</td>
    </tr>`;
  }).join('')}
  </tbody></table></div>`;
}

function tabGlof() {
  const g = (S.glofHist || []).slice().sort((a, b) => (b.year || 0) - (a.year || 0));
  return `<p class="muted">${fmt(g.length)} historical GLOF records for Nepal in HMAGLOFDB v4.0 (ICIMOD, Shrestha et al. 2023). Click any row to centre on the source lake.</p>
    <table><thead><tr>
      <th scope="col">Year</th><th scope="col">Lake</th><th scope="col">Glacier</th><th scope="col">Basin</th>
      <th scope="col">Type</th><th scope="col">Mechanism / Driver</th><th scope="col">Lives</th><th scope="col">Discharge m³/s</th>
    </tr></thead><tbody>
    ${g.map(e => `<tr tabindex="0" data-fly="${safeFlyAttr(e.lat, e.lon, 11)}">
      <td class="num">${e.year ? fmt(e.year) : '—'}</td>
      <td><b>${esc(e.lake)}</b></td>
      <td>${esc(e.glacier)}</td>
      <td>${esc(e.basin)}</td>
      <td>${esc(e.lake_type)}</td>
      <td>${esc([e.mechanism, e.driver].filter(x => x && x !== 'Unknown').join(' · ') || 'Unknown')}</td>
      <td class="num">${e.lives ? fmt(e.lives) : '—'}</td>
      <td class="num">${e.discharge ? fmt(e.discharge) : '—'}</td>
    </tr>`).join('')}
    </tbody></table>`;
}

function tabCharts() {
  const P = S.lakes.map(f => f.properties);

  // 1. Provincial summary covering all 7 canonical provinces
  const byProv = {};
  ((S.districtsMeta && S.districtsMeta.provinces) || []).forEach(pr => {
    byProv[pr.name] = { n: 0, pri: 0, pfv: 0 };
  });
  P.forEach(p => {
    const pr = p.prov || 'Unassigned';
    if (!byProv[pr]) byProv[pr] = { n: 0, pri: 0, pfv: 0 };
    byProv[pr].n++;
    if (p.priority) byProv[pr].pri++;
    byProv[pr].pfv += Number(p.pfv_Mm3) || 0;
  });
  const provRows = Object.entries(byProv).sort((a, b) => b[1].pfv - a[1].pfv);
  const maxProvPfv = Math.max(1, ...provRows.map(r => r[1].pfv));

  // 2. PFV vs Area log-log SVG (expanded bounds: covers 100% of positive-PFV lakes, zero clipping)
  const pos = P.filter(p => p.pfv_Mm3 > 0 && p.area_km2 > 0);
  const W = 360;
  const H = 195;
  const pL = 42;
  const pR = 12;
  const pT = 12;
  const pB = 26;
  const cW = W - pL - pR;
  const cH = H - pT - pB;
  const xMin = -3.0;
  const xMax = 0.8;
  const yMin = -2.2;
  const yMax = 2.2;
  const xOf = a => pL + ((Math.log10(Math.max(0.001, a)) - xMin) / (xMax - xMin)) * cW;
  const yOf = v => pT + cH - ((Math.log10(Math.max(0.0065, v)) - yMin) / (yMax - yMin)) * cH;

  // 3. Hypsometry covering ALL 1,429 lakes (z: 2454–5898 m -> 2400–6000 m, zero dropped lakes)
  const bins = [2400, 3200, 3800, 4400, 4800, 5200, 5600, 6200];
  const bCounts = bins.slice(0, -1).map((lo, i) => {
    const hi = bins[i + 1];
    const sub = P.filter(p => p.z >= lo && (i === bins.length - 2 ? p.z <= hi : p.z < hi));
    return {
      lbl: `${(lo / 1000).toFixed(1)}–${(hi / 1000).toFixed(1)}k`,
      n: sub.length,
      pri: sub.filter(x => x.priority).length,
      pf: lo >= 4800,
    };
  });
  const totalBinned = bCounts.reduce((a, b) => a + b.n, 0);
  const maxBin = Math.max(1, ...bCounts.map(b => b.n));

  return `<div class="chart-grid">
    <div class="chart-card">
      <h4>Potential Flood Volume vs Lake Area (${fmt(pos.length)} SLA lakes)</h4>
      <svg class="scatter-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Log-log scatter plot of potential flood volume versus lake area">
        ${[0.01, 0.1, 1, 10, 100].map(v => `<line x1="${pL}" y1="${yOf(v).toFixed(1)}" x2="${W - pR}" y2="${yOf(v).toFixed(1)}" stroke="var(--chart-grid)" stroke-dasharray="2 2"/>
          <text x="${pL - 4}" y="${(yOf(v) + 3).toFixed(1)}" fill="var(--chart-text)" font-size="8.5" text-anchor="end" font-family="monospace">${v}</text>`).join('')}
        <line x1="${pL}" y1="${yOf(10).toFixed(1)}" x2="${W - pR}" y2="${yOf(10).toFixed(1)}" stroke="var(--chart-threshold)" stroke-dasharray="3 3" stroke-width="1.3"/>
        <text x="${pL + 4}" y="${(yOf(10) - 4).toFixed(1)}" fill="var(--chart-threshold)" font-size="9" font-weight="700" font-family="monospace">10 Mm³ priority threshold</text>
        <line x1="${xOf(0.002).toFixed(1)}" y1="${yOf(55 * Math.pow(0.002, 1.25)).toFixed(1)}" x2="${xOf(4.8).toFixed(1)}" y2="${yOf(55 * Math.pow(4.8, 1.25)).toFixed(1)}" stroke="var(--chart-axis)" stroke-dasharray="2 2"/>
        ${pos.map(p => `<circle cx="${xOf(p.area_km2).toFixed(1)}" cy="${yOf(p.pfv_Mm3).toFixed(1)}" r="${p.priority ? 3.8 : 2.0}" fill="${p.priority ? 'var(--chart-threshold)' : (p.hp_m >= p.dm_fujita_m ? 'var(--chart-sim)' : 'var(--chart-q2)')}" opacity="0.85">
          <title>${esc(p.name || p.id)}: A=${fmt(p.area_km2, 3)} km², PFV=${fmt(p.pfv_Mm3, 2)} Mm³</title></circle>`).join('')}
        <text x="${W / 2}" y="${H - 5}" fill="var(--chart-text)" font-size="9" text-anchor="middle" font-family="monospace">Lake area A (0.001–6 km², log) · dashed = 55A¹·²⁵ cap</text>
      </svg>
    </div>

    <div class="chart-card">
      <h4>Provincial Cumulative PFV &amp; Priority Lakes (All 7 Provinces)</h4>
      <div class="bar-list">
        ${provRows.map(([pr, v]) => `<div>
          <div class="bar-row-head">
            <span><b>${esc(tProvince(pr, S.districtsMeta))}</b> <span class="band">(${fmt(v.n)} lakes, ${fmt(v.pri)} prio)</span></span>
            <span class="mono">${fmt(v.pfv, 1)} Mm³</span>
          </div>
          <div class="bar-track"><div class="bar-fill${v.pri ? ' prio' : ''}" data-w="${v.pfv > 0 ? Math.max(1.5, (100 * v.pfv) / maxProvPfv).toFixed(1) : 0}%"></div></div>
        </div>`).join('')}
      </div>
    </div>

    <div class="chart-card">
      <h4>Glacial Lake Hypsometry (${fmt(totalBinned)} / ${fmt(P.length)} lakes · ≥4.8 km Permafrost)</h4>
      <div class="hypso-wrap">
        ${bCounts.map(b => `<div class="hypso-col">
          <span class="mono hypso-num">${fmt(b.n)}</span>
          <div class="hypso-bar${b.pf ? ' pf' : ''}" data-h="${Math.max(3, Math.round((112 * b.n) / maxBin))}px" title="${esc(b.lbl)} m: ${fmt(b.n)} lakes (${fmt(b.pri)} priority)"></div>
          <span class="mono hypso-lbl">${esc(b.lbl)}</span>
        </div>`).join('')}
      </div>
      <div class="band field-gap">Blue bars ≥ 4,800 m lie inside the Himalayan mountain permafrost belt (Gruber 2012). All ${fmt(totalBinned)} lakes plotted with zero elevation clipping.</div>
    </div>
  </div>`;
}

function tabValid() {
  const v = S.valid;
  const s = S.sens;
  if (!v) return '<p class="muted">Validation results unavailable.</p>';

  const lims = Array.isArray(v.known_limitations) ? v.known_limitations : [];
  const sensHtml = s ? `
    <h4>Parameter &amp; Decision-Tree Sensitivity Analysis (n = ${fmt(s.sample_size)} lakes ≥ ${fmt(s.sample_min_area_km2, 2)} km²)</h4>
    <div class="callout info"><b>Saturation note:</b> ${esc(s.saturation_note || '')}</div>
    <table><thead><tr>
      <th scope="col">Variant</th><th scope="col">SLA lakes</th><th scope="col">Priority</th>
      <th scope="col">Total PFV Mm³</th><th scope="col">Δ PFV %</th><th scope="col">Hp-lim mean ratio</th>
      <th scope="col">Hp-lim IQR</th><th scope="col">Priority Δ</th>
    </tr></thead><tbody>
    ${(s.variants || []).map(row => `<tr>
      <td>${esc(row.variant)}</td>
      <td class="num">${fmt(row.n_with_sla)}</td>
      <td class="num">${fmt(row.n_priority)}</td>
      <td class="num">${fmt(row.total_pfv_Mm3, 1)}</td>
      <td class="num">${row.delta_pfv_pct > 0 ? '+' : ''}${fmt(row.delta_pfv_pct, 1)}%</td>
      <td class="num">${row.hp_limited_weighted_mean_ratio != null ? '×' + fmt(row.hp_limited_weighted_mean_ratio, 2) : '—'}</td>
      <td class="num">${Array.isArray(row.hp_limited_iqr_ratio) ? `[${fmt(row.hp_limited_iqr_ratio[0], 2)}, ${fmt(row.hp_limited_iqr_ratio[1], 2)}]` : '—'}</td>
      <td class="num">${fmt(row.priority_set_changed)}</td>
    </tr>`).join('')}
    </tbody></table>
    ${s.hazard_reading ? `<p class="cite">Rounce et al. (2016) tree interpretation sensitivity: <b>${fmt(s.hazard_reading.n_lakes_differing)} of ${fmt(s.hazard_reading.n_lakes)} lakes</b> shift class between general (very high: ${fmt(s.hazard_reading.general['very high'])}) and enumerated (very high: ${fmt(s.hazard_reading.enumerated['very high'])}) readings.</p>` : ''}
  ` : '';

  return `<div class="prose">
    ${lims.length ? `<h4>Known Scientific &amp; Data Limitations (${fmt(lims.length)} disclosures)</h4>
      <div class="lim-grid">${lims.map(item => `<div class="lim-card"><b>${esc(item.title)}</b><span>${esc(item.detail)}</span></div>`).join('')}</div>` : ''}

    <h4>Reproduction of published hazard assessments (Rounce et al. 2016 Table 5)</h4>
    <p class="cite">Agreement — Avalanche: <b>${esc(v.rounce_agreement && v.rounce_agreement.avalanche)}</b> · Rockfall: <b>${esc(v.rounce_agreement && v.rounce_agreement.rockfall)}</b> · SLA production (4-cell): <b>${esc(v.rounce_agreement && v.rounce_agreement.sla_threshold)}</b> (unfiltered: ${esc(v.rounce_agreement && v.rounce_agreement.sla_threshold_unfiltered)}).</p>
    <table><thead><tr>
      <th scope="col">Lake</th><th scope="col">Ava (ours)</th><th scope="col">Ava (pub)</th>
      <th scope="col">Rock (ours)</th><th scope="col">Rock (pub)</th><th scope="col">SLA° ours</th>
      <th scope="col">SLA° pub</th><th scope="col">Prod SLA agrees</th>
    </tr></thead><tbody>
    ${(v.rounce || []).map(r => `<tr>
      <td>${esc(r.lake)}</td><td>${r.ava ? 'yes' : 'no'}</td><td>${r.ava_pub ? 'yes' : 'no'}</td>
      <td>${r.rock ? 'yes' : 'no'}</td><td>${r.rock_pub ? 'yes' : 'no'}</td>
      <td class="num">${fmt(r.sla, 1)}</td><td class="num">${fmt(r.sla_pub, 1)}</td>
      <td>${r.sla_agree ? '<span class="text-ok">yes</span>' : '<span class="text-bad">no</span>'}</td>
    </tr>`).join('')}
    </tbody></table>
    <p class="cite">${esc(v.rounce_note || '')}</p>

    <h4>Reproduction of potential-flood-volume arithmetic (Fujita et al. 2013 Table 1)</h4>
    <table><thead><tr>
      <th scope="col">Lake</th><th scope="col">Area km²</th><th scope="col">Hp m</th>
      <th scope="col">Dm pub</th><th scope="col">Dm ours</th><th scope="col">PFV pub</th>
      <th scope="col">PFV ours</th><th scope="col">Observed FV</th><th scope="col">PFV ÷ obs</th>
    </tr></thead><tbody>
    ${(v.fujita1 || []).map(r => `<tr>
      <td>${esc(r.lake)}</td><td class="num">${fmt(r.area, 2)}</td><td class="num">${fmt(r.hp)}</td>
      <td class="num">${fmt(r.dm_pub)}</td><td class="num">${fmt(r.dm_ours, 1)}</td>
      <td class="num">${fmt(r.pfv_pub, 1)}</td><td class="num">${fmt(r.pfv_ours, 1)}</td>
      <td class="num">${r.fv_obs == null ? '—' : fmt(r.fv_obs, 1)}</td>
      <td class="num">${r.pfv_over_fv == null ? '—' : '×' + fmt(r.pfv_over_fv, 2)}</td>
    </tr>`).join('')}
    </tbody></table>

    <h4>Lake-by-lake PFV comparison (Fujita et al. 2013 Table 2, Nepal)</h4>
    <p>Agreement: ${esc(v.fujita_agreement && v.fujita_agreement.zero)} zero-PFV lakes, ${esc(v.fujita_agreement && v.fujita_agreement.large)} above ${fmt(v.fujita_large_threshold)} Mm³ within ×3, <b>${esc(v.fujita_agreement && v.fujita_agreement.small)} below ${fmt(v.fujita_large_threshold)} Mm³ (30 m DEM resolution limit)</b>.</p>
    <table><thead><tr>
      <th scope="col">Lake</th><th scope="col">PFV pub</th><th scope="col">PFV ours</th>
      <th scope="col">Ratio</th><th scope="col">SLA ours km²</th><th scope="col">Hp ours m</th><th scope="col">Agrees</th>
    </tr></thead><tbody>
    ${(v.fujita2 || []).map(r => `<tr>
      <td>${esc(r.lake)}</td><td class="num">${fmt(r.pfv_pub, 1)}</td><td class="num">${fmt(r.pfv_ours, 2)}</td>
      <td class="num">${r.ratio == null ? '—' : '×' + fmt(r.ratio, 2)}</td>
      <td class="num">${fmt(r.sla_km2, 3)}</td><td class="num">${fmt(r.hp, 1)}</td>
      <td>${r.both_zero ? '<span class="text-ok">both zero</span>' : r.within3 ? '<span class="text-ok">within ×3</span>' : '<span class="text-bad">no</span>'}</td>
    </tr>`).join('')}
    </tbody></table>

    ${sensHtml}

    <h4>Measured &amp; reconstructed outbursts</h4>
    <table><thead><tr>
      <th scope="col">Event</th><th scope="col">Observed</th><th scope="col">Our median</th>
      <th scope="col">95% interval</th><th scope="col">Within</th><th scope="col">Source</th>
    </tr></thead><tbody>
    ${(v.events || []).map(e => `<tr>
      <td>${esc(e.event)}</td><td class="num">${esc(e.observed)}</td>
      <td class="num">${fmt(e.p50)}</td><td class="num">${fmt(e.lo)}–${fmt(e.hi)}</td>
      <td>${e.within ? '<span class="text-ok">yes</span>' : '<span class="text-bad">no</span>'}</td>
      <td class="cite">${esc(e.source)}</td>
    </tr>`).join('')}
    </tbody></table>

    <h4>Internal &amp; multi-hazard consistency checks (${fmt((v.checks || []).filter(c => c.pass).length)}/${fmt((v.checks || []).length)})</h4>
    <table><thead><tr><th scope="col">Check</th><th scope="col">Result</th></tr></thead><tbody>
    ${(v.checks || []).map(c => `<tr>
      <td>${esc(c.name)}</td>
      <td>${c.pass ? '<span class="text-ok">PASS</span>' : '<span class="text-bad">FAIL</span>'} <span class="band">${esc(c.detail)}</span></td>
    </tr>`).join('')}
    </tbody></table>
  </div>`;
}

function tabMethods() {
  const s = S.summary || {};
  const th = s.thresholds || {};
  const yrs = (S.riversMeta && S.riversMeta.climatology_years) || (s.river_basins && s.river_basins.climatology_years) || 21;
  const refs = [
    ['Rounce, D.R. et al. (2016)', 'Hydrol. Earth Syst. Sci. 20, 3455–3475', 'https://doi.org/10.5194/hess-20-3455-2016', 'GLOF hazard, impact & risk decision trees; avalanche & rockfall runout'],
    ['Fujita, K. et al. (2013)', 'Nat. Hazards Earth Syst. Sci. 13, 1827–1839', 'https://doi.org/10.5194/nhess-13-1827-2013', 'Steep lakefront area (10°), potential lowering height Hp & PFV ≥ 10 Mm³ triage'],
    ['Veh, G., Korup, O., Walz, A. (2020)', 'PNAS 117(2), 907–912', 'https://doi.org/10.1073/pnas.1914898117', 'Bayesian depth–area posterior & dimensionless dam-break peak discharge'],
    ["Walder, J.S., O'Connor, J.E. (1997)", 'Water Resour. Res. 33(10), 2337–2348', 'https://doi.org/10.1029/97WR01616', 'Dimensionless peak-discharge scaling'],
    ['Huggel, C. et al. (2004)', 'Can. Geotech. J. 41(6), 1068–1083', 'https://doi.org/10.1139/T04-053', 'Volume-dependent ice-avalanche reach angle'],
    ['Dahal, R.K., Hasegawa, S. (2008)', 'Geomorphology 100(3–4), 429–443', 'https://doi.org/10.1016/j.geomorph.2008.01.014', 'Nepal Himalaya rainfall intensity–duration landslide threshold I = 73.90 D⁻⁰·⁷⁹'],
    ['Guzzetti, F. et al. (2008)', 'Landslides 5(1), 3–17', 'https://doi.org/10.1007/s10346-007-0112-1', 'Global rainfall intensity–duration baseline threshold'],
    ['Kirschbaum, D.B., Stanley, T. (2018)', "Earth's Future 6, 531–550", 'https://doi.org/10.1002/2017EF000715', 'NASA COOLR / GLC landslide inventory framework'],
    ['Harrigan, S. et al. (2020)', 'Earth Syst. Sci. Data 12, 2043–2060', 'https://doi.org/10.5194/essd-12-2043-2020', 'Copernicus EMS GloFAS-ERA5 global river discharge reanalysis'],
    ['Alfieri, L. et al. (2013)', 'Hydrol. Earth Syst. Sci. 17, 1161–1175', 'https://doi.org/10.5194/hess-17-1161-2013', 'GloFAS ensemble flood forecasting & return-period framework'],
    ['Styron, R., Pagani, M. (2020)', 'Earthquake Spectra 36(1_suppl), 160–180', 'https://doi.org/10.1177/8755293020944182', 'GEM Global Active Faults Database'],
    ['Nowicki Jessee, M.A. et al. (2018)', 'J. Geophys. Res. Earth Surf. 123, 1835–1859', 'https://doi.org/10.1029/2017JF004494', 'USGS operational coseismic landslide model'],
    ['Gruber, S. (2012)', 'The Cryosphere 6, 221–233', 'https://doi.org/10.5194/tc-6-221-2012', 'Global high-resolution mountain permafrost zonation'],
    ['Shrestha, F. et al. (2023)', 'Earth Syst. Sci. Data 15(9), 3941–3961', 'https://doi.org/10.5194/essd-15-3941-2023', 'HMAGLOFDB v4.0 recorded GLOF database'],
  ];

  return `<div class="prose">
    <h4>Multi-hazard screening architecture &amp; 7-day automated refresh</h4>
    <p><b>Nepal TRĀYA (त्राय)</b> integrates static 30 m DEM terrain screening with an automated <b>7-day GitHub Actions refresh pipeline</b> (<code>.github/workflows/weekly-refresh.yml</code>) and on-demand keyless browser feeds:</p>
    <ul>
      <li><b>Glacial Lake Outburst Floods (GLOFs):</b> D8 mass-movement routing (${fmt(th.avalanche_slope && th.avalanche_slope[0])}–${fmt(th.avalanche_slope && th.avalanche_slope[1])}° ice avalanche; &gt;${fmt(th.rockfall_slope)}° rockfall), Fujita et al. (2013) steep lakefront depression (&gt;${fmt(th.sla_threshold)}°) and PFV, Veh et al. (2020) Bayesian depth &amp; Walder–O'Connor peak discharge Qp, and 120 km HydroRIVERS corridor routing using perpendicular point-to-segment exposure matching (≤1,000 m).</li>
      <li><b>Fluvial Floods (Copernicus GloFAS):</b> 30-day reanalysis + 30-day ensemble river discharge across Nepal's 10 major river outlets, graded against ${fmt(yrs)}-year Gumbel EV1 return periods (Q₂, Q₅, Q₂₀), with explicit grid-snap quality flags.</li>
      <li><b>Rainfall &amp; Coseismic Landslides:</b> Rolling 24 h, 72 h, and 168 h liquid rainfall (<code>rain_sum</code>) across 24 physiographic zones screened against Dahal &amp; Hasegawa (2008) (I = 73.90 D⁻⁰·⁷⁹), paired with mapped landslide records and live USGS Nowicki Jessee (2018) ground-failure alerts.</li>
      <li><b>Cryosphere &amp; Satellite EO:</b> Weekly Copernicus Sentinel-1 SAR (C-band IW VV/VH all-weather monsoon radar) and Sentinel-2 L2A cloud-screened STAC scenes (Element84 Earth Search), 10 m EOX cloudless mosaic, daily NASA EOSDIS GIBS overlays, and 0 °C freezing-level isotherm tracking.</li>
      <li><b>Governance, Cascades &amp; 2D Pilot Documentation:</b>
        <a href="${esc(DATA_LICENSES_URL)}" target="_blank" rel="noopener noreferrer">DATA_LICENSES.md ↗</a> ·
        <a href="${esc(MODEL_CARDS_URL)}" target="_blank" rel="noopener noreferrer">docs/MODEL_CARDS.md ↗</a> ·
        <a href="${esc(INST_SPEC_URL)}" target="_blank" rel="noopener noreferrer">docs/INSTITUTIONAL_INTEGRATION_SPEC.md ↗</a> ·
        <a href="${esc(TSHO_ROLPA_PLAN_URL)}" target="_blank" rel="noopener noreferrer">docs/TSHO_ROLPA_2D_STUDY_PLAN.md ↗</a>
      </li>
    </ul>

    <div class="callout bad">
      <b>Critical statutory &amp; scientific notice:</b>
      <ul>
        <li>TRĀYA is NOT an operational early warning system. Always follow official warnings from <a href="https://hydrology.gov.np/" target="_blank" rel="noopener noreferrer">Nepal DHM</a>, <a href="https://seismonepal.gov.np/" target="_blank" rel="noopener noreferrer">DMG / NEMRC</a>, and <a href="https://bipadportal.gov.np/" target="_blank" rel="noopener noreferrer">NDRRMA BIPAD</a>.</li>
        <li>30 m DEM resolution under-detects small steep lakefronts (&lt;5 Mm³); PFV = 0 does not guarantee dam stability.</li>
        <li>Peak discharge Qp spans ~2 orders of magnitude (95% interval); 1 km exposure buffers are search corridors, not 2D hydrodynamic flood extents.</li>
      </ul>
    </div>

    <h4>Peer-reviewed methods cited</h4>
    <ul>${refs.map(r => {
      const doiUrl = safeUrl(r[2]);
      return `<li><b>${esc(r[0])}</b> ${esc(r[1])} ${doiUrl ? `<a href="${esc(doiUrl)}" target="_blank" rel="noopener noreferrer">doi ↗</a>` : ''} — <span class="cite">${esc(r[3])}</span></li>`;
    }).join('')}</ul>

    <h4>Open-access datasets &amp; licences</h4>
    <ul>${(s.sources || []).map(d => {
      const srcUrl = safeUrl(d.url);
      return `<li><b>${esc(d.name)}</b> — ${esc(d.detail)}. ${srcUrl ? `<a href="${esc(srcUrl)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ''} <span class="cite">(${esc(d.licence)})</span></li>`;
    }).join('')}</ul>
  </div>`;
}

/* ==========================================================================
   15. Emergency Modal, Keyboard Accessibility & Event Wiring
   ========================================================================== */
let lastFocusedBeforeModal = null;

function openEmergencyModal() {
  const modal = document.getElementById('emergencyModal');
  if (!modal) return;
  lastFocusedBeforeModal = document.activeElement;
  modal.hidden = false;
  const closeBtn = document.getElementById('btnCloseEmergency');
  if (closeBtn) closeBtn.focus();
}

function closeEmergencyModal() {
  const modal = document.getElementById('emergencyModal');
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  if (lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') {
    lastFocusedBeforeModal.focus();
  }
}

async function openSourceHealthModal() {
  const modal = document.getElementById('sourceHealthModal');
  const body = document.getElementById('sourceHealthBody');
  if (!modal || !body) return;
  lastFocusedBeforeModal = document.activeElement;
  modal.hidden = false;
  const closeBtn = document.getElementById('btnCloseSourceHealth');
  if (closeBtn) closeBtn.focus();

  if (!S.manifest || !S.kpiBaseline) {
    body.innerHTML = `<p class="loading">${esc(t('shLoading'))}</p>`;
    try {
      await Promise.all([ensureData('manifest'), ensureData('kpi_baseline')]);
      updateSourceHealthButton();
    } catch (err) {
      if (!modal.hidden) {
        body.innerHTML = `<div class="callout bad">Failed to load provenance manifest (${esc(err.message)}).</div>`;
      }
      return;
    }
  }
  if (!modal.hidden) renderSourceHealthModal();
}

function closeSourceHealthModal() {
  const modal = document.getElementById('sourceHealthModal');
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  if (lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') {
    lastFocusedBeforeModal.focus();
  }
}

function renderSourceHealthModal() {
  const body = document.getElementById('sourceHealthBody');
  if (!body) return;
  const mf = S.manifest;
  const kpi = S.kpiBaseline;
  if (!mf) {
    body.innerHTML = '<p class="muted">Provenance manifest unavailable.</p>';
    return;
  }

  const health = mf.overall_health || 'degraded';
  const hCls = health === 'healthy' ? 'sla-available' : health === 'stale' ? 'sla-unavailable' : 'sla-stale';
  const sc = mf.source_counts || {};
  const checksumCount = mf.input_checksums ? Object.keys(mf.input_checksums).length : 0;

  const ffDet = (kpi && kpi.feed_freshness_detail) || {};
  const provDet = (kpi && kpi.provenance_completeness_detail) || {};
  const lsMat = (kpi && kpi.landslide_maturity) || {};
  const expCov = (kpi && kpi.exposure_coverage) || {};
  const natTot = (expCov && expCov.national_totals) || {};
  const casSum = (kpi && kpi.cascade_summary) || {};
  const sources = Array.isArray(mf.sources) ? mf.sources : [];

  body.innerHTML = `
    <div class="sh-meta-bar">
      <div>
        <b>${esc(t('shOverallHealth'))}:</b>
        <span class="sla-badge ${hCls}">${esc(tHealthState(health))}</span>
        <span class="band mono"> · Build ${esc(fmtNpt(mf.build_utc))} · SHA <code>${esc(mf.git_sha || '—')}</code> · ${fmt(checksumCount)} SHA-256 checksums</span>
      </div>
      <div class="sh-meta-links">
        <a href="${esc(DATA_LICENSES_URL)}" target="_blank" rel="noopener noreferrer">${esc(t('shViewLicenses'))}</a>
        <a href="${esc(MODEL_CARDS_URL)}" target="_blank" rel="noopener noreferrer">MODEL_CARDS.md ↗</a>
        <a href="${esc(INST_SPEC_URL)}" target="_blank" rel="noopener noreferrer">INSTITUTIONAL_SPEC.md ↗</a>
      </div>
    </div>

    ${kpi ? `
    <div class="scorecard-grid" role="region" aria-label="KPI Baseline Scorecard">
      <div class="score-card">
        <span class="score-lbl">${esc(t('shKpiFreshness'))}</span>
        <span class="score-val">${fmt(kpi.feed_freshness_pct, 1)}%</span>
        <span class="score-sub">${fmt(ffDet.within_sla)}/${fmt(ffDet.active_sources)} active within SLA · ${fmt(ffDet.stale_or_expired)} stale · ${fmt(ffDet.unavailable_active)} unavailable · ${fmt(ffDet.institutional_stubs)} MOU stubs</span>
      </div>
      <div class="score-card">
        <span class="score-lbl">${esc(t('shKpiProvenance'))}</span>
        <span class="score-val text-ok">${fmt(kpi.provenance_completeness_pct, 1)}%</span>
        <span class="score-sub">${fmt(provDet.complete_datasets)}/${fmt(provDet.total_datasets)} datasets carry source, NPT timestamp, licence &amp; 6-state class</span>
      </div>
      <div class="score-card">
        <span class="score-lbl">${esc(t('shKpiLandslide'))}</span>
        <span class="score-val">${fmt(lsMat.dated_events)} <span class="band">dated</span> / ${fmt(lsMat.undated_scars)} <span class="band">scars</span></span>
        <span class="score-sub">${fmt(lsMat.dated_share_pct, 1)}% dated · ${fmt(lsMat.duplicate_candidates)} review queue · null-not-0: ${lsMat.null_casualty_integrity_ok ? '<b class="text-ok">Verified ✓</b>' : '<b class="text-bad">Check</b>'}</span>
      </div>
      <div class="score-card">
        <span class="score-lbl">${esc(t('shKpiExposure'))}</span>
        <span class="score-val">${fmt(expCov.n_provinces_covered)}P · ${fmt(expCov.n_districts_covered)}D</span>
        <span class="score-sub">${fmt(natTot.total_unique_bridges_at_crossings)} bridges · ${fmt(natTot.total_unique_settlements_potentially_isolated)} isolated · ${fmt(casSum.active_pathways)}/${fmt(casSum.total_pathways)} cascades</span>
      </div>
    </div>` : ''}

    <div class="muted field-gap">
      Operational feeds: <b>${fmt(sc.available)}/${fmt(sc.operational)}</b> available · <b>${fmt(sc.fallback_used)}</b> fallback cached · <b>${fmt(sc.institutional_stubs)}</b> institutional MOU stubs (direct DHM/NEMRC/DoR pending formal agreements).
    </div>

    <div class="tbl-scroll field-gap">
      <table>
        <thead>
          <tr>
            <th scope="col">${esc(t('shColDataset'))}</th>
            <th scope="col">${esc(t('shColClass'))}</th>
            <th scope="col">${esc(t('shColUpdated'))}</th>
            <th scope="col">${esc(t('shColSla'))}</th>
            <th scope="col">${esc(t('shColFallback'))}</th>
            <th scope="col">${esc(t('shColRecords'))}</th>
            <th scope="col">${esc(t('shColLicense'))}</th>
          </tr>
        </thead>
        <tbody>
          ${sources.map(src => {
            const isMou = Boolean(src.requires_institutional_agreement);
            return `<tr>
              <td class="wrap-cell">
                <b>${esc(src.source)}</b>
                ${isMou ? `<span class="fb-tag is-mou">${esc(t('shMouRequired'))}</span>` : ''}
                <div class="band mono">${esc(src.dataset)}</div>
                ${src.notes ? `<div class="band">${esc(src.notes)}</div>` : ''}
              </td>
              <td>${badgeDataClass(src.data_class)}</td>
              <td class="mono">
                ${esc(fmtNpt(src.retrieved_at_utc))}
                ${src.observation_time_utc ? `<div class="band">obs: ${esc(fmtNpt(src.observation_time_utc, false))}</div>` : ''}
              </td>
              <td>
                ${badgeSla(src.status)}
                <div class="band mono">SLA ${fmt(src.sla_hours)}h</div>
              </td>
              <td>
                ${src.fallback_used
                  ? `<span class="fb-tag is-fallback">${esc(t('shFallback'))}</span>`
                  : `<span class="fb-tag">${esc(t('shDirect'))}</span>`}
              </td>
              <td class="num">${fmt(src.record_count)}</td>
              <td class="wrap-cell">
                <span class="band">${esc(src.license_ref)}</span>
                <div><a href="${esc(DATA_LICENSES_URL)}" target="_blank" rel="noopener noreferrer">${esc(t('shViewLicenses'))}</a></div>
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}

function switchTab(tabKey, focusTab = false) {
  S.tab = tabKey;
  document.querySelectorAll('#tabs button[role="tab"]').forEach(btn => {
    const isSel = btn.dataset.tab === tabKey;
    btn.setAttribute('aria-selected', isSel ? 'true' : 'false');
    btn.setAttribute('tabindex', isSel ? '0' : '-1');
    if (isSel && focusTab) btn.focus();
  });
  const tb = document.getElementById('tabbody');
  if (tb) tb.setAttribute('aria-labelledby', `tab-${tabKey}`);
  document.getElementById('bottom').classList.remove('collapsed');
  if (window.matchMedia('(max-width: 760px)').matches) {
    setMobilePane('bottom');
  }
  renderTab();
  setTimeout(() => map.invalidateSize(), 180);
}

function refresh() {
  readFilters();
  S.colourBy = document.getElementById('colourBy').value;
  drawLegend();
  renderLakes();
}

const debouncedRefresh = debounce(refresh, 160);
const debouncedDistrictFilter = debounce(val => populateDistrictSelect(val), 120);

function wireEvents() {
  // Lake filters & colour-by
  ['fPriority', 'fOnlyRouted', 'fAva', 'fSla', 'fIce', 'fContact', 'fPast', 'fProv', 'colourBy', 'lLakes'].forEach(id => {
    document.getElementById(id).addEventListener('change', refresh);
  });
  ['fArea', 'fSearch'].forEach(id => {
    document.getElementById(id).addEventListener('input', debouncedRefresh);
  });
  document.getElementById('btnResetFilters').addEventListener('click', resetFilters);

  // District triage & Near Me
  document.getElementById('districtSearch').addEventListener('input', e => debouncedDistrictFilter(e.target.value));
  document.getElementById('districtSearch').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const sel = document.getElementById('fDistrict');
      const opts = Array.from(sel.options).filter(o => o.value);
      if (opts.length >= 1) {
        selectDistrict(opts[0].value, true);
      }
    }
  });
  document.getElementById('fDistrict').addEventListener('change', e => {
    if (e.target.value) selectDistrict(e.target.value, true);
    else {
      clearDistrictHighlight();
      renderDefaultInspector();
    }
  });
  document.getElementById('btnNearMe').addEventListener('click', locateNearMe);
  document.getElementById('btnClearDistrict').addEventListener('click', () => {
    clearDistrictHighlight();
    renderDefaultInspector();
  });

  // Route & exposure checkboxes only re-draw selected lake route
  ['lRoute', 'lExp'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      if (S.selKind === 'lake' && S.sel && S.routes && S.routes[S.sel]) {
        drawSelectedLakeRoute(S.routes[S.sel]);
      }
    });
  });

  // Independent overlay toggles (zero full-layer tear-down!)
  const overlayHandlers = {
    lRivers: [gRivers, drawRiversLayer],
    lFaults: [gFaults, drawFaultsLayer],
    lNodes: [gNodes, drawNodesLayer],
    lLandslides: [gLs, drawLandslidesLayer],
    lHydro: [gHydro, drawHydroLayer],
    lEqHist: [gEqH, drawEqHistLayer],
    lGlof: [gGlof, drawGlofLayer],
    lGdacs: [gGdacs, drawGdacsLayer],
    lEq: [gEq, drawEq],
    lMmi: [gMmi, drawMmi],
  };

  Object.entries(overlayHandlers).forEach(([id, [grp, drawFn]]) => {
    document.getElementById(id).addEventListener('change', () => {
      const on = document.getElementById(id).checked;
      if (on) {
        grp.addTo(map);
        drawFn();
      } else {
        map.removeLayer(grp);
        grp.clearLayers();
      }
    });
  });

  document.getElementById('eqWindow').addEventListener('change', () => loadEq(true));

  // NASA GIBS controls
  ['satLayer', 'satDate'].forEach(id => document.getElementById(id).addEventListener('change', updateSatOverlay));
  document.getElementById('satOp').addEventListener('input', () => {
    const op = Number(document.getElementById('satOp').value) / 100;
    document.getElementById('satOpLbl').textContent = `${Math.round(op * 100)}%`;
    if (activeGibsTile) activeGibsTile.setOpacity(op);
  });
  document.getElementById('satPrev').addEventListener('click', () => shiftSatDate(-1));
  document.getElementById('satNext').addEventListener('click', () => shiftSatDate(1));
  document.getElementById('satOff').addEventListener('click', () => {
    document.getElementById('satLayer').value = 'none';
    updateSatOverlay();
  });

  // Bottom tabs with full WAI-ARIA ArrowLeft/ArrowRight/Home/End keyboard navigation
  const tabBtns = Array.from(document.querySelectorAll('#tabs button[role="tab"]'));
  tabBtns.forEach((btn, idx) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    btn.addEventListener('keydown', e => {
      let nextIdx = null;
      if (e.key === 'ArrowRight') nextIdx = (idx + 1) % tabBtns.length;
      else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + tabBtns.length) % tabBtns.length;
      else if (e.key === 'Home') nextIdx = 0;
      else if (e.key === 'End') nextIdx = tabBtns.length - 1;
      if (nextIdx !== null) {
        e.preventDefault();
        switchTab(tabBtns[nextIdx].dataset.tab, true);
      }
    });
  });

  // Mobile segmented drawer tabs
  document.querySelectorAll('#mobileTabs button[data-mobile-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      setMobilePane(btn.dataset.mobileTab);
      if (btn.dataset.mobileTab === 'bottom') renderTab();
    });
  });

  // KPI strip semantic buttons
  document.querySelectorAll('#kpiStrip .kpi').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.goto));
  });

  // Workbench dock size buttons
  document.getElementById('dockMin').addEventListener('click', () => {
    const b = document.getElementById('bottom');
    b.classList.add('collapsed');
    b.classList.remove('expanded');
    setTimeout(() => map.invalidateSize(), 180);
  });
  document.getElementById('dockMid').addEventListener('click', () => {
    const b = document.getElementById('bottom');
    b.classList.remove('collapsed', 'expanded');
    setTimeout(() => map.invalidateSize(), 180);
  });
  document.getElementById('dockMax').addEventListener('click', () => {
    const b = document.getElementById('bottom');
    b.classList.add('expanded');
    b.classList.remove('collapsed');
    setTimeout(() => map.invalidateSize(), 180);
  });

  // Desktop left/right drawer toggles
  document.getElementById('btnToggleLeft').addEventListener('click', e => {
    const hidden = document.getElementById('mainGrid').classList.toggle('hide-left');
    e.currentTarget.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    setTimeout(() => map.invalidateSize(), 180);
  });
  document.getElementById('btnToggleRight').addEventListener('click', e => {
    const hidden = document.getElementById('mainGrid').classList.toggle('hide-right');
    e.currentTarget.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    setTimeout(() => map.invalidateSize(), 180);
  });

  // KPI toggle
  document.getElementById('btnKpi').addEventListener('click', e => {
    const hidden = document.getElementById('kpiStrip').classList.toggle('hidden');
    e.currentTarget.setAttribute('aria-expanded', hidden ? 'false' : 'true');
    setTimeout(() => map.invalidateSize(), 180);
  });

  // Theme toggle
  document.getElementById('btnTheme').addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('traya.theme', next); } catch { /* ignore */ }
    renderTab();
  });

  // Bilingual EN | नेपाली toggle
  document.getElementById('btnLang').addEventListener('click', () => {
    setLang(getLang() === 'en' ? 'ne' : 'en');
    applyStaticTranslations();
    populateProvinceAndDistrictDropdowns();
    drawLegend();
    updateFilterCount();
    updateStatusPills();
    drawRiversLayer();
    if (document.getElementById('lNodes').checked) drawNodesLayer();
    if (document.getElementById('lLandslides').checked) drawLandslidesLayer();
    if (S.selKind === 'district' && S.selDistrict) renderDistrictByName(S.selDistrict);
    else if (S.selKind === 'river' && S.sel) selectRiver(S.sel, false);
    else if (S.selKind === 'node' && S.sel) selectNode(S.sel, false);
    else if (S.selKind === 'lake' && S.sel) {
      const f = S.lakeById.get(S.sel);
      if (f) renderLakeDetail(f.properties, S.routes ? S.routes[S.sel] : null, f, false);
    } else {
      renderDefaultInspector();
    }
    const shModal = document.getElementById('sourceHealthModal');
    if (shModal && !shModal.hidden) renderSourceHealthModal();
    renderTab();
  });

  // Live refresh & alert buttons
  document.getElementById('btnRefreshLive').addEventListener('click', refreshAllLiveInBrowser);
  document.getElementById('btnStaleRefresh').addEventListener('click', refreshAllLiveInBrowser);
  document.getElementById('btnCloseToast').addEventListener('click', () => setToast(''));

  // Source Health & Provenance modal
  document.getElementById('btnSourceHealth').addEventListener('click', openSourceHealthModal);
  document.getElementById('btnCloseSourceHealth').addEventListener('click', closeSourceHealthModal);
  document.getElementById('sourceHealthModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeSourceHealthModal();
  });

  // Emergency drawer modal
  document.getElementById('btnEmergency').addEventListener('click', openEmergencyModal);
  document.getElementById('btnEmergencyInline').addEventListener('click', openEmergencyModal);
  document.getElementById('btnCloseEmergency').addEventListener('click', closeEmergencyModal);
  document.getElementById('emergencyModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeEmergencyModal();
  });

  // Region zoom presets
  document.querySelectorAll('#regionBar .hud-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#regionBar .hud-btn').forEach(x => x.classList.remove('on'));
      btn.classList.add('on');
      const [la, lo, z] = btn.dataset.v.split(',').map(Number);
      map.setView([la, lo], z);
    });
  });

  // Global keyboard shortcuts ('/' search, 'Escape' dismiss modal/popups)
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      closeEmergencyModal();
      closeSourceHealthModal();
      map.closePopup();
      return;
    }
    if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
      e.preventDefault();
      document.getElementById('fSearch').focus();
    }
  });

  // Pause live polling while tab hidden; refresh on resume if stale > 5 min
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && S.liveFetchedAt && ageHours(S.liveFetchedAt) > (5 / 60)) {
      loadEq(false);
    }
  });
}

/* ==========================================================================
   16. Fast Startup Bootstrap (Only 5 Core JSONs Loaded Initially)
   ========================================================================== */
async function init() {
  applyStaticTranslations();
  wireEvents();
  setBasemapPill(null);

  try {
    const [summary, districtsMeta, lakesCore, riversWatch, hydrometWeekly] = await Promise.all([
      fetchJson('data/summary.json'),
      fetchJson('data/districts.json'),
      fetchJson('data/lakes_core.json'),
      fetchJson('data/rivers_watch.json'),
      fetchJson('data/hydromet_weekly.json'),
    ]);

    S.summary = summary;
    S.districtsMeta = districtsMeta;
    S.districts = (districtsMeta && districtsMeta.districts) || [];
    S.lakes = unpackLakesCore(lakesCore);
    S.lakeById.clear();
    S.lakes.forEach(f => S.lakeById.set(f.properties.id, f));

    S.riversMeta = riversWatch;
    S.rivers = (riversWatch && riversWatch.basins) || [];
    S.hydromet = hydrometWeekly;
    S.hmLakeById = {};
    ((hydrometWeekly && hydrometWeekly.priority_lakes) || []).forEach(x => {
      S.hmLakeById[x.id] = x;
      if (x.sentinel2) S.stacCache[x.id] = x.sentinel2;
    });

    // Update top KPI counters
    document.getElementById('k-lakes').textContent = fmt(S.lakes.length);
    document.getElementById('k-prio').textContent = `${fmt(S.lakes.filter(f => f.properties.priority).length)} priority`;
    document.getElementById('k-sat').textContent = `${fmt(((hydrometWeekly && hydrometWeekly.priority_lakes) || []).length)} lakes`;
    const eoSum = summary && summary.eo_sar;
    if (eoSum) {
      document.getElementById('k-sat-sub').textContent = `S1 SAR (${fmt(eoSum.n_s1_covered)}/${fmt(eoSum.n_priority_lakes)}) · S2 (${fmt(eoSum.n_s2_covered)}/${fmt(eoSum.n_priority_lakes)}) · 0 °C`;
    }
    const nFaults = (summary && summary.active_faults && summary.active_faults.n_traces) || 70;
    document.getElementById('k-eq-sub').textContent = `NDRRMA BIPAD · USGS + ${fmt(nFaults)} GEM traces`;
    const cascSum = summary && summary.cascades;
    const isoSum = summary && summary.exposure_isolation;
    const kCasc = document.getElementById('k-casc');
    const kCascSub = document.getElementById('k-casc-sub');
    if (kCasc && cascSum) {
      kCasc.textContent = `${fmt(cascSum.n_chains)} chains · ${fmt(cascSum.n_active_scenarios)} watch`;
    }
    if (kCascSub && isoSum) {
      kCascSub.textContent = `${fmt(isoSum.total_unique_settlements_potentially_isolated)} isolated · ${fmt(isoSum.total_unique_bridges_at_crossings)} bridges`;
    }

    populateProvinceAndDistrictDropdowns();
    updateStatusPills();
    renderDefaultInspector();
    refresh();
    drawRiversLayer();
    renderTab();

    // Start live USGS Nepal-region feed & periodic 5-min poll (paused when hidden)
    loadEq(true);
    setInterval(() => loadEq(false), 5 * 60 * 1000);

    // Restore deep-linked lake, district, or tab from URL hash
    const h = location.hash.slice(1);
    if (h.startsWith('lake=')) {
      const lid = decodeURIComponent(h.slice(5));
      setTimeout(() => selectLake(lid, true), 120);
    } else if (h.startsWith('district=')) {
      const dname = decodeURIComponent(h.slice(9));
      setTimeout(() => selectDistrict(dname, true), 120);
    } else if (h.startsWith('tab=')) {
      const tb = decodeURIComponent(h.slice(4));
      if (document.getElementById(`tab-${tb}`)) switchTab(tb);
    }
  } catch (err) {
    const bp = document.getElementById('pill-build');
    if (bp) {
      bp.className = 'pill err';
      bp.innerHTML = '<span class="dot"></span>data failed to load';
    }
    const detailEl = document.getElementById('detailBody');
    if (detailEl) {
      detailEl.innerHTML = `<div class="callout bad"><b>Unable to load observatory JSON data</b> (${esc(err.message)}). Serve this repository over HTTP (e.g., <code>python -m http.server</code>) rather than opening <code>file://</code> directly.</div>`;
    }
  }
}

init();
