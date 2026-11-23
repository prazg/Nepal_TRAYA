/**
 * Nepal TRĀYA (त्राय) — Offline Community Landslide Report Queue & Privacy Module
 *
 * Governance & Privacy Guarantees (TRAYA-008 / Community Field Pilot):
 * - Strictly non-operational sandbox (`governance_mode: "pilot_sandbox_post_mou"`,
 *   `moderation_status: "pending_agency_review"`, `feature_type: "hazard_report"`,
 *   `auto_merged: false`).
 * - 100% client-side EXIF/GPS/camera metadata stripping via offscreen `<canvas>` JPEG re-encoding.
 * - Deterministic client-side PII redaction matching `src/moderation.py::redact_pii`
 *   (Nepal mobile/landline numbers, emails, citizenship/driving-license/NID/passport IDs,
 *   and social `@handles`).
 * - Bit-identical SHA-256 `dedup_fingerprint` matching `src/moderation.py::compute_dedup_fingerprint`
 *   via Web Crypto `crypto.subtle.digest` with a FIPS 180-4 pure-JS SHA-256 fallback.
 * - Strict `null`-not-`0` casualty enforcement (`fatalities`, `injuries`) for unverified reports.
 * - Native IndexedDB (`traya_field_reports_v1`, store `reports`) with transparent
 *   `localStorage` (and in-memory) fallback for constrained or private-browsing devices.
 * - Exported moderation bundles conform 100% to `schemas/community_report.v1.schema.json`.
 * - Zero external dependencies, zero innerHTML sinks, strict CSP compatible.
 */

export const REPORT_DB_NAME = 'traya_field_reports_v1';
export const REPORT_DB_VERSION = 1;
export const REPORT_STORE_NAME = 'reports';
export const FALLBACK_STORAGE_KEY = 'traya_field_reports_v1_fallback';
export const GOVERNANCE_MODE = 'pilot_sandbox_post_mou';
export const DEFAULT_MODERATION_STATUS = 'pending_agency_review';
export const COMMUNITY_REPORT_SCHEMA_REF = 'schemas/community_report.v1.schema.json';

const DATED_DUP_MAX_KM = 1.5;
const DATED_DUP_MAX_DAYS = 3.0;
const UNDATED_DUP_MAX_KM = 0.5;

const CANONICAL_PROVINCES = new Set([
  'Koshi Province',
  'Madhesh Province',
  'Bagmati Province',
  'Gandaki Province',
  'Lumbini Province',
  'Karnali Province',
  'Sudurpashchim Province',
]);

const VALID_TIME_PRECISIONS = new Set(['exact_hour', 'day', 'month', 'year', 'unknown']);
const VALID_PII_TAGS = new Set(['phone', 'email', 'id', 'handle']);

const MEMORY_FALLBACK = new Map();

/* ==========================================================================
   1. Client-Side PII Redaction (mirrors src/moderation.py::redact_pii)
   ========================================================================== */

// Ordered carefully: emails before @handles; Nepal phones before generic IDs.
// Avoids regex lookbehind so older rural mobile Safari/WebKit browsers work cleanly.
const PII_RULES = [
  {
    kind: 'email',
    token: '[REDACTED_EMAIL]',
    re: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    keepPrefix: false,
  },
  {
    kind: 'phone',
    token: '[REDACTED_PHONE]',
    // International Nepal +977 / 00977 mobile & landline (with optional (0) or 0)
    re: /(^|[^\w])(?:\+977|00977)[\s-]*(?:\(0\)|0)?[\s-]*(?:9[678]\d(?:[\s-]?\d){7}|1[\s-]?\d{3}[\s-]?\d{4}|(?:11|[2-9]\d)[\s-]?\d{3}[\s-]?\d{3})(?![\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'phone',
    token: '[REDACTED_PHONE]',
    // 10-digit Nepal mobile: 98xxxxxxxx, 97xxxxxxxx, 96xxxxxxxx (ASCII)
    re: /(^|[^.\d])9[678]\d(?:[\s-]?\d){7}(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'phone',
    token: '[REDACTED_PHONE]',
    // Kathmandu landline: 01-xxxxxxx / 01 xxxxxxx / 01xxxxxxx
    re: /(^|[^.\d])01[\s-]?\d{3}[\s-]?\d{4}(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'phone',
    token: '[REDACTED_PHONE]',
    // Regional Nepal STD landlines: 011-xxxxxx or 0[2-9][0-9]-xxxxxx
    re: /(^|[^.\d])0(?:11|[2-9]\d)[\s-]\d{3}[\s-]?\d{3}(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'phone',
    token: '[REDACTED_PHONE]',
    // Devanagari Nepal mobile/landline digits
    re: /(^|[^.\d\u0966-\u096f])(?:\+९७७[\s-]?)?(?:९[६७८][\u0966-\u096f](?:[\s-]?[\u0966-\u096f]){7}|०१[\s-]?[\u0966-\u096f]{3}[\s-]?[\u0966-\u096f]{4})(?![.\d\u0966-\u096f])/g,
    keepPrefix: true,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Labeled citizenship / NID / driving license / passport / voter ID
    re: /\b(?:citizenship|nagarikta|nid|national\s+id|driving\s+licen[cs]e|licen[cs]e|lic\.?|passport|voter\s*id)\s*(?:no\.?|number|num\.?|id)?\s*[:#-]?\s*[A-Za-z]{0,3}\d[\d\/-]{4,18}\b/gi,
    keepPrefix: false,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Devanagari labeled citizenship ID
    re: /नागरिकता\s*(?:नं\.?|नम्बर|प्रमाणपत्र\s*नं\.?)?\s*[:#-]?\s*[\d\u0966-\u096f][\d\u0966-\u096f\/-]{4,18}/g,
    keepPrefix: false,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Formatted Nepal citizenship number (e.g., 27-01-74-01234 or 27/01/74/01234)
    re: /(^|[^.\d])\d{2}[-\/]\d{2}[-\/]\d{2,4}[-\/]\d{4,6}(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Formatted Nepal driving license number (e.g., 01-06-00123456)
    re: /(^|[^.\d])\d{2}-\d{2}-\d{6,9}(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Formatted Nepal National ID (e.g., 123-456-789-0)
    re: /(^|[^.\d])\d{3}-\d{3}-\d{3}-\d(?![.\d])/g,
    keepPrefix: true,
  },
  {
    kind: 'id',
    token: '[REDACTED_ID]',
    // Standalone 10-16 digit numeric ID (excluding decimals, hex hashes, and hotlines)
    re: /(^|[^A-Za-z0-9._-])\d{10,16}(?![A-Za-z0-9._-])/g,
    keepPrefix: true,
  },
  {
    kind: 'handle',
    token: '[REDACTED_HANDLE]',
    // Social media @handles (applied after email redaction)
    re: /(^|[^A-Za-z0-9._%+-])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}\b/g,
    keepPrefix: true,
  },
];

/**
 * Deterministically strip Nepal PII (emails, Nepal mobile/landline phones,
 * citizenship/license/NID numeric IDs, and social `@handles`) from text.
 * Matches `src/moderation.py::redact_pii` categories (`email`, `phone`, `id`, `handle`)
 * and is idempotent on already-redacted strings.
 *
 * @param {string} inputText
 * @returns {{ text: string, redactions: string[], redactionCounts: Record<string, number>, piiRedacted: boolean }}
 */
export function redactPii(inputText) {
  let cleaned = String(inputText == null ? '' : inputText);
  const redactions = [];
  const counts = { email: 0, phone: 0, id: 0, handle: 0, total: 0 };

  if (!cleaned) {
    return { text: '', redactions, redactionCounts: counts, piiRedacted: false };
  }

  for (const rule of PII_RULES) {
    rule.re.lastIndex = 0;
    cleaned = cleaned.replace(rule.re, (...args) => {
      counts[rule.kind] += 1;
      counts.total += 1;
      if (!redactions.includes(rule.kind)) {
        redactions.push(rule.kind);
      }
      return rule.keepPrefix ? `${args[1]}${rule.token}` : rule.token;
    });
  }

  return {
    text: cleaned,
    redactions,
    redactionCounts: counts,
    piiRedacted: counts.total > 0,
  };
}

/* ==========================================================================
   2. Client-Side EXIF/GPS Metadata Stripping via Offscreen Canvas
   ========================================================================== */

function decodeBase64ToBytes(b64) {
  if (typeof globalThis.atob === 'function') {
    const bin = globalThis.atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) {
      out[i] = bin.charCodeAt(i);
    }
    return out;
  }
  if (typeof Buffer !== 'undefined') {
    return new Uint8Array(Buffer.from(b64, 'base64'));
  }
  return utf8ToBytes(b64);
}

function computeDataUrlBytes(dataUrl) {
  const commaIdx = dataUrl.indexOf(',');
  if (commaIdx < 0) return 0;
  const b64 = dataUrl.slice(commaIdx + 1);
  let padding = 0;
  if (b64.endsWith('==')) padding = 2;
  else if (b64.endsWith('=')) padding = 1;
  return Math.max(0, Math.floor((b64.length * 3) / 4) - padding);
}

function computeDataUrlSha256Hex(dataUrl) {
  const commaIdx = dataUrl.indexOf(',');
  if (commaIdx < 0) return null;
  const b64 = dataUrl.slice(commaIdx + 1);
  return sha256FallbackHex(decodeBase64ToBytes(b64));
}

function loadViaImageElement(blob) {
  return new Promise((resolve, reject) => {
    const urlApi = globalThis.URL || globalThis.webkitURL;
    if (!urlApi || typeof urlApi.createObjectURL !== 'function' || typeof Image !== 'function') {
      reject(new Error('Browser image decoding APIs are unavailable.'));
      return;
    }
    const objUrl = urlApi.createObjectURL(blob);
    const img = new Image();
    const cleanup = () => {
      try {
        urlApi.revokeObjectURL(objUrl);
      } catch {
        // ignore revoke errors
      }
    };
    img.onload = () => {
      cleanup();
      resolve({
        source: img,
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
        close: () => {},
      });
    };
    img.onerror = () => {
      cleanup();
      reject(new Error('Unable to decode image file for EXIF stripping.'));
    };
    img.decoding = 'async';
    img.src = objUrl;
  });
}

async function decodeImageSource(blob) {
  if (typeof globalThis.createImageBitmap === 'function') {
    try {
      const bitmap = await globalThis.createImageBitmap(blob);
      return {
        source: bitmap,
        width: bitmap.width || 0,
        height: bitmap.height || 0,
        close: () => {
          try {
            bitmap.close();
          } catch {
            // ignore bitmap close errors
          }
        },
      };
    } catch {
      // Fall back to Image + immediately-revoked object URL
    }
  }
  return loadViaImageElement(blob);
}

/**
 * Decode a File/Blob onto an offscreen `<canvas>` and re-encode as a clean
 * JPEG data URL so 100% of EXIF, GPS coordinates, timestamps, thumbnails,
 * XMP, and device serial metadata are permanently stripped before storage.
 *
 * @param {File|Blob} file
 * @param {number} [maxDim=1024]
 * @param {number} [quality=0.78]
 * @returns {Promise<{ dataUrl: string, width: number, height: number, bytes: number, exifStripped: true, sha256: string }>}
 */
export async function stripImageExif(file, maxDim = 1024, quality = 0.78) {
  if (!file || typeof file !== 'object' || typeof file.size !== 'number') {
    throw new TypeError('stripImageExif expects a File or Blob image input.');
  }
  if (file.type && !String(file.type).toLowerCase().startsWith('image/')) {
    throw new TypeError(`Unsupported non-image MIME type: ${file.type}`);
  }
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
    throw new Error('Canvas EXIF stripping requires a browser document context.');
  }

  const safeMaxDim = Number.isFinite(Number(maxDim)) && Number(maxDim) >= 64
    ? Math.min(4096, Math.round(Number(maxDim)))
    : 1024;
  const safeQuality = Number.isFinite(Number(quality))
    ? Math.min(0.95, Math.max(0.1, Number(quality)))
    : 0.78;

  const decoded = await decodeImageSource(file);
  try {
    const srcW = decoded.width;
    const srcH = decoded.height;
    if (!srcW || !srcH) {
      throw new Error('Decoded image has zero dimensions.');
    }

    const scale = Math.min(1, safeMaxDim / Math.max(srcW, srcH));
    const targetW = Math.max(1, Math.round(srcW * scale));
    const targetH = Math.max(1, Math.round(srcH * scale));

    const canvas = document.createElement('canvas');
    canvas.width = targetW;
    canvas.height = targetH;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('2D canvas context unavailable for EXIF stripping.');
    }

    // Fill white backdrop so transparent PNGs/WebPs serialize cleanly as JPEG
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, targetW, targetH);
    ctx.drawImage(decoded.source, 0, 0, targetW, targetH);

    // Re-encoding via Canvas JPEG discards 100% of EXIF, GPS, XMP, IPTC & ICC segments
    const dataUrl = canvas.toDataURL('image/jpeg', safeQuality);
    const bytes = computeDataUrlBytes(dataUrl);
    const sha256 = computeDataUrlSha256Hex(dataUrl);

    // Release canvas backing buffer immediately on memory-constrained mobile devices
    canvas.width = 0;
    canvas.height = 0;

    return {
      dataUrl,
      width: targetW,
      height: targetH,
      bytes,
      exifStripped: true,
      sha256,
    };
  } finally {
    decoded.close();
  }
}

/* ==========================================================================
   3. Deterministic SHA-256 Deduplication Fingerprint (SubtleCrypto + Pure-JS)
   ========================================================================== */

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function utf8ToBytes(str) {
  if (typeof TextEncoder === 'function') {
    return new TextEncoder().encode(str);
  }
  const encoded = unescape(encodeURIComponent(str));
  const out = new Uint8Array(encoded.length);
  for (let i = 0; i < encoded.length; i += 1) {
    out[i] = encoded.charCodeAt(i);
  }
  return out;
}

function bytesToHex(bytes) {
  let hex = '';
  for (let i = 0; i < bytes.length; i += 1) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}

/**
 * Pure-JS FIPS 180-4 SHA-256 fallback for insecure HTTP/file contexts where
 * `crypto.subtle` is unavailable. Produces bit-identical output to Web Crypto
 * and Python `hashlib.sha256`.
 */
function sha256FallbackHex(bytes) {
  const len = bytes.length;
  const bitLenHi = Math.floor((len * 8) / 0x100000000);
  const bitLenLo = (len * 8) >>> 0;
  const paddedLen = Math.ceil((len + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(bytes);
  padded[len] = 0x80;

  const view = new DataView(padded.buffer);
  view.setUint32(paddedLen - 8, bitLenHi, false);
  view.setUint32(paddedLen - 4, bitLenLo, false);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;

  const w = new Uint32Array(64);

  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      w[i] = view.getUint32(offset + i * 4, false);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = ((w[i - 15] >>> 7) | (w[i - 15] << 25))
        ^ ((w[i - 15] >>> 18) | (w[i - 15] << 14))
        ^ (w[i - 15] >>> 3);
      const s1 = ((w[i - 2] >>> 17) | (w[i - 2] << 15))
        ^ ((w[i - 2] >>> 19) | (w[i - 2] << 13))
        ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let i = 0; i < 64; i += 1) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ ((~e) & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map(v => v.toString(16).padStart(8, '0'))
    .join('');
}

function buildCanonicalDedupString(lon, lat, eventDateIso, trigger) {
  const lo = Number(lon);
  const la = Number(lat);
  const lonQ = Number.isFinite(lo) ? lo.toFixed(3) : 'nan';
  const latQ = Number.isFinite(la) ? la.toFixed(3) : 'nan';

  let dateKey = 'undated';
  if (eventDateIso != null && String(eventDateIso).trim()) {
    const s = String(eventDateIso).trim();
    const ms = Date.parse(s);
    if (Number.isFinite(ms)) {
      dateKey = new Date(ms).toISOString().slice(0, 10);
    } else if (s.length >= 4) {
      dateKey = s.slice(0, 10);
    }
  }

  const trigNorm = String(trigger || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_') || 'unknown';

  // Exact canonical format matching src/moderation.py::compute_dedup_fingerprint
  return `traya_community_report_v1|${lonQ}|${latQ}|${dateKey}|${trigNorm}`;
}

/**
 * Compute deterministic SHA-256 hex deduplication fingerprint matching
 * `src/moderation.py::compute_dedup_fingerprint`.
 *
 * @param {number} lon
 * @param {number} lat
 * @param {string|null|undefined} eventDateIso
 * @param {string|null|undefined} trigger
 * @returns {Promise<string>} 64-character lowercase hex SHA-256 digest
 */
export async function computeDedupFingerprint(lon, lat, eventDateIso, trigger) {
  const canonical = buildCanonicalDedupString(lon, lat, eventDateIso, trigger);
  const bytes = utf8ToBytes(canonical);

  if (
    globalThis.crypto &&
    globalThis.crypto.subtle &&
    typeof globalThis.crypto.subtle.digest === 'function'
  ) {
    try {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
      return bytesToHex(new Uint8Array(digest));
    } catch {
      // Fall through to pure-JS SHA-256
    }
  }
  return sha256FallbackHex(bytes);
}

/* ==========================================================================
   4. Proximity & Temporal Duplicate Candidate Detection (Flag-Only)
   ========================================================================== */

function haversineKm(lon1, lat1, lon2, lat2) {
  const R = 6371.0088;
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
}

function extractLonLat(rec) {
  if (!rec || typeof rec !== 'object') return null;
  const props = rec.properties && typeof rec.properties === 'object' ? rec.properties : rec;
  let lon = props.lon ?? props.lng ?? props.longitude;
  let lat = props.lat ?? props.latitude;
  if ((lon == null || lat == null) && rec.geometry && Array.isArray(rec.geometry.coordinates)) {
    [lon, lat] = rec.geometry.coordinates;
  }
  const lo = Number(lon);
  const la = Number(lat);
  if (!Number.isFinite(lo) || !Number.isFinite(la)) return null;
  return { lon: lo, lat: la };
}

function extractDateInfo(rec) {
  if (!rec || typeof rec !== 'object') return { iso: null, ms: null };
  const props = rec.properties && typeof rec.properties === 'object' ? rec.properties : rec;
  const precision = String(props.time_precision || props.date_precision || '').trim().toLowerCase();
  if (precision === 'unknown') return { iso: null, ms: null };
  const raw = props.event_date_utc || props.eventDateIso || props.date || null;
  if (!raw) return { iso: null, ms: null };
  const s = String(raw).trim();
  if (!s) return { iso: null, ms: null };
  let iso = s;
  if (/^\d{4}$/.test(s)) iso = `${s}-01-01T00:00:00Z`;
  else if (/^\d{4}-\d{2}$/.test(s)) iso = `${s}-01T00:00:00Z`;
  else if (/^\d{4}-\d{2}-\d{2}$/.test(s)) iso = `${s}T00:00:00Z`;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return { iso: null, ms: null };
  return { iso, ms };
}

function unpackInventoryList(inventoryEvents) {
  if (Array.isArray(inventoryEvents)) return inventoryEvents;
  if (!inventoryEvents || typeof inventoryEvents !== 'object') return [];
  if (inventoryEvents.type === 'FeatureCollection' && Array.isArray(inventoryEvents.features)) {
    return inventoryEvents.features;
  }
  if (Array.isArray(inventoryEvents.events)) return inventoryEvents.events;
  if (Array.isArray(inventoryEvents.records)) return inventoryEvents.records;
  if (Array.isArray(inventoryEvents.items)) return inventoryEvents.items;
  return [];
}

/**
 * Flag potential duplicates against both the local offline queue and the loaded
 * TRĀYA landslide inventory without ever blocking offline capture.
 *
 * Proximity rules:
 * - Both dated: `<= 1.5 km` AND `<= 3 days`.
 * - Either/both undated: `<= 0.5 km`.
 * - Also flags exact `dedup_fingerprint` collisions.
 *
 * @param {object} candidate
 * @param {Array<object>} [existingLocalReports=[]]
 * @param {Array<object>|object} [inventoryEvents=[]]
 * @returns {Array<object>} Sorted advisory duplicate candidates (`auto_merged: false`)
 */
export function findLocalAndInventoryDuplicates(
  candidate,
  existingLocalReports = [],
  inventoryEvents = []
) {
  const candCoords = extractLonLat(candidate);
  if (!candCoords) return [];

  const candDate = extractDateInfo(candidate);
  const candId = String(candidate?.report_id || candidate?.id || '').trim();
  const candFp = String(candidate?.dedup_fingerprint || '').trim();
  const matches = [];

  const inspectList = (items, sourceScope) => {
    for (const rawItem of items) {
      if (!rawItem || typeof rawItem !== 'object') continue;
      const props = rawItem.properties && typeof rawItem.properties === 'object'
        ? rawItem.properties
        : rawItem;
      const otherId = String(props.report_id || props.id || '').trim();
      if (candId && otherId && candId === otherId) continue;

      const otherCoords = extractLonLat(rawItem);
      if (!otherCoords) continue;

      const distKm = haversineKm(
        candCoords.lon,
        candCoords.lat,
        otherCoords.lon,
        otherCoords.lat
      );
      const otherDate = extractDateInfo(rawItem);
      const otherFp = String(props.dedup_fingerprint || '').trim();

      let deltaDays = null;
      let reason = null;

      if (candFp && otherFp && candFp === otherFp) {
        if (candDate.ms != null && otherDate.ms != null) {
          deltaDays = Math.abs(candDate.ms - otherDate.ms) / 86400000;
        }
        reason = 'exact_dedup_fingerprint_match';
      } else if (candDate.ms != null && otherDate.ms != null) {
        deltaDays = Math.abs(candDate.ms - otherDate.ms) / 86400000;
        if (distKm <= DATED_DUP_MAX_KM && deltaDays <= DATED_DUP_MAX_DAYS) {
          reason = 'dated_spatiotemporal_proximity';
        }
      } else if (distKm <= UNDATED_DUP_MAX_KM) {
        reason = 'undated_spatial_proximity';
      }

      if (reason) {
        const matchId = otherId || `${sourceScope}_${otherCoords.lat.toFixed(4)}_${otherCoords.lon.toFixed(4)}`;
        const distRounded = Number(distKm.toFixed(3));
        const daysRounded = deltaDays === null ? null : Number(deltaDays.toFixed(2));
        const titleStr = String(
          props.title || props.description_redacted || props.notes || props.source || 'Existing landslide record'
        ).slice(0, 120);
        const sourceStr = String(
          props.source || (sourceScope === 'local_queue' ? 'Local Offline Queue' : 'TRĀYA Inventory')
        );
        const providerId = String(
          props.provider_id || (sourceScope === 'local_queue' ? 'community_field' : 'unknown')
        );
        const featureType = String(
          props.feature_type || (sourceScope === 'local_queue' ? 'hazard_report' : 'landslide_event')
        );

        matches.push({
          sourceScope,
          report_id: candId || '',
          inventory_event_id: matchId,
          inventory_source: sourceStr,
          inventory_provider_id: providerId,
          inventory_feature_type: featureType,
          inventory_title: titleStr,
          inventory_date_utc: otherDate.iso,
          distance_km: distRounded,
          days_apart: daysRounded,
          reason,
          review_status: 'pending_review',
          auto_merged: false,
        });
      }
    }
  };

  inspectList(Array.isArray(existingLocalReports) ? existingLocalReports : [], 'local_queue');
  inspectList(unpackInventoryList(inventoryEvents), 'inventory');

  matches.sort((a, b) => a.distance_km - b.distance_km);
  return matches;
}

/* ==========================================================================
   5. Record Normalization & Strict Null-Not-0 Schema Enforcement
   ========================================================================== */

function strictUnverifiedCount(val) {
  // Unverified community observations MUST NEVER emit 0 for casualty fields.
  if (val == null || val === '' || typeof val === 'boolean') return null;
  const num = Number(val);
  if (!Number.isFinite(num) || num <= 0) return null;
  return Math.round(num);
}

function normalizeIsoTimestampUtc(val, fallbackIso) {
  const s = String(val == null ? '' : val).trim();
  if (s) {
    const ms = Date.parse(s);
    if (Number.isFinite(ms)) {
      return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
    }
  }
  return fallbackIso;
}

function normalizeEventDateAndPrecision(rawDate, rawPrecision) {
  const s = String(rawDate == null ? '' : rawDate).trim();
  const precIn = String(rawPrecision == null ? '' : rawPrecision).trim().toLowerCase();

  if (!s || precIn === 'unknown') {
    return { event_date_utc: null, time_precision: 'unknown' };
  }
  if (/^\d{4}$/.test(s)) {
    return {
      event_date_utc: `${s}-01-01T00:00:00Z`,
      time_precision: VALID_TIME_PRECISIONS.has(precIn) && precIn !== 'unknown' ? precIn : 'year',
    };
  }
  if (/^\d{4}-\d{2}$/.test(s)) {
    return {
      event_date_utc: `${s}-01T00:00:00Z`,
      time_precision: VALID_TIME_PRECISIONS.has(precIn) && precIn !== 'unknown' ? precIn : 'month',
    };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return {
      event_date_utc: `${s}T00:00:00Z`,
      time_precision: VALID_TIME_PRECISIONS.has(precIn) && precIn !== 'unknown' ? precIn : 'day',
    };
  }
  const ms = Date.parse(s);
  if (!Number.isFinite(ms)) {
    return { event_date_utc: null, time_precision: 'unknown' };
  }
  const hasExplicitHour = /T\d{2}:\d{2}/.test(s) && !/T00:00:00(\.0+)?Z?$/.test(s);
  const inferred = hasExplicitHour ? 'exact_hour' : 'day';
  const precision = VALID_TIME_PRECISIONS.has(precIn) && precIn !== 'unknown' ? precIn : inferred;
  return {
    event_date_utc: new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    time_precision: precision,
  };
}

function normalizeLocationSource(val) {
  const s = String(val == null ? 'manual_pin' : val).trim().toLowerCase();
  return s === 'gps' ? 'gps' : 'manual_pin';
}

function normalizeRoadBlocked(val) {
  if (val === true) return true;
  if (val === false) return false;
  const s = String(val == null ? '' : val).trim().toLowerCase();
  if (s === 'yes' || s === 'true' || s === 'partial' || s === '1') return true;
  if (s === 'no' || s === 'false' || s === '0') return false;
  return null;
}

function normalizeTrigger(val) {
  const s = String(val == null ? 'unknown' : val).trim().toLowerCase().replace(/\s+/g, '_');
  return s ? s.slice(0, 48) : 'unknown';
}

function sanitizeReportId(rawId) {
  const clean = String(rawId || '').trim().replace(/[^A-Za-z0-9_.:-]/g, '_');
  if (clean && /^[A-Za-z0-9_.:-]+$/.test(clean)) return clean;
  const ts = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  let rand = '';
  if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === 'function') {
    const buf = new Uint8Array(6);
    globalThis.crypto.getRandomValues(buf);
    rand = bytesToHex(buf);
  } else {
    rand = Math.random().toString(16).slice(2, 14).padEnd(12, '0');
  }
  return `cr_${ts}_${rand}`;
}

function sanitizePhotoMetadata(rawPhoto, explicitPhotoSha256) {
  if (rawPhoto && typeof rawPhoto === 'object') {
    const dataUrl = String(rawPhoto.dataUrl || rawPhoto.data_url || '').trim();
    if (dataUrl.startsWith('data:image/jpeg;base64,')) {
      const width = Number(rawPhoto.width);
      const height = Number(rawPhoto.height);
      const bytes = Number(rawPhoto.bytes);
      const sha = /^[0-9a-f]{64}$/.test(String(rawPhoto.sha256 || ''))
        ? String(rawPhoto.sha256)
        : computeDataUrlSha256Hex(dataUrl);
      return {
        photoAttached: true,
        photoSha256: sha,
        localPhoto: {
          mime_type: 'image/jpeg',
          width: Number.isFinite(width) && width > 0 ? Math.round(width) : null,
          height: Number.isFinite(height) && height > 0 ? Math.round(height) : null,
          bytes: Number.isFinite(bytes) && bytes > 0 ? Math.round(bytes) : computeDataUrlBytes(dataUrl),
          exif_stripped: true,
          sha256: sha,
          data_url: dataUrl,
        },
      };
    }
  }
  if (/^[0-9a-f]{64}$/.test(String(explicitPhotoSha256 || ''))) {
    return {
      photoAttached: true,
      photoSha256: String(explicitPhotoSha256),
      localPhoto: null,
    };
  }
  return { photoAttached: false, photoSha256: null, localPhoto: null };
}

function sanitizeDuplicateCandidatesForSchema(rawList, reportId) {
  if (!Array.isArray(rawList)) return [];
  const out = [];
  for (const item of rawList.slice(0, 10)) {
    if (!item || typeof item !== 'object') continue;
    const invId = String(item.inventory_event_id || item.matchId || '').trim();
    const dist = Number(item.distance_km ?? item.distanceKm);
    if (!invId || !Number.isFinite(dist) || dist < 0) continue;
    const daysRaw = item.days_apart ?? item.deltaDays;
    const days = daysRaw == null ? null : (Number.isFinite(Number(daysRaw)) && Number(daysRaw) >= 0 ? Number(daysRaw) : null);
    out.push({
      report_id: String(item.report_id || reportId),
      inventory_event_id: invId,
      inventory_source: item.inventory_source ?? item.source ?? null,
      inventory_provider_id: item.inventory_provider_id ?? null,
      inventory_feature_type: item.inventory_feature_type ?? item.featureType ?? null,
      inventory_title: item.inventory_title ?? item.title ?? null,
      inventory_date_utc: item.inventory_date_utc ?? item.eventDateUtc ?? null,
      distance_km: Number(dist.toFixed(3)),
      days_apart: days === null ? null : Number(days.toFixed(2)),
      reason: String(item.reason || 'spatial_proximity'),
      review_status: 'pending_review',
      auto_merged: false,
    });
  }
  return out;
}

function clampNepalCoord(val, min, max) {
  const num = Number(val);
  if (!Number.isFinite(num)) return null;
  if (num < min || num > max) return Number(num.toFixed(5));
  return Number(num.toFixed(5));
}

async function normalizeOfflineReportRecord(record) {
  const src = record && typeof record === 'object' ? record : {};
  const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const reportId = sanitizeReportId(src.report_id || src.id);

  const safeLon = clampNepalCoord(src.lon, 79.5, 88.8);
  const safeLat = clampNepalCoord(src.lat, 26.0, 31.0);

  const { event_date_utc, time_precision } = normalizeEventDateAndPrecision(
    src.event_date_utc ?? src.eventDateIso ?? src.date,
    src.time_precision ?? src.date_precision ?? src.datePrecision
  );

  const trigger = normalizeTrigger(src.trigger);
  const roadBlocked = normalizeRoadBlocked(src.road_blocked ?? src.roadBlocked);
  const locationSource = normalizeLocationSource(src.location_source ?? src.locationSource);

  const accRaw = Number(src.location_accuracy_m ?? src.accuracy_m ?? src.accuracyM);
  const locationAccuracyM = Number.isFinite(accRaw) && accRaw >= 0 ? Number(accRaw.toFixed(1)) : null;

  const rawDesc = String(src.description_redacted ?? src.notes ?? src.description ?? '');
  const descPii = redactPii(rawDesc);

  const provinceRaw = String(src.province || '').trim();
  const province = CANONICAL_PROVINCES.has(provinceRaw) ? provinceRaw : null;
  const district = String(src.district || '').trim() || null;
  const muniWardRaw = String(src.municipality_ward || src.municipalityWard || '').trim();
  const muniWardPii = redactPii(muniWardRaw);
  const municipalityWard = muniWardPii.text || null;

  const rawTitle = String(src.title || '').trim();
  const titlePii = redactPii(rawTitle);
  const safeTitle = titlePii.text || (district ? `Community landslide observation (${district})` : 'Community landslide observation');

  const rawTitleNe = src.title_ne != null ? String(src.title_ne).trim() : '';
  const titleNePii = rawTitleNe ? redactPii(rawTitleNe) : { text: '', redactions: [] };
  const safeTitleNe = titleNePii.text || null;

  const existingTags = Array.isArray(src.pii_redaction_tags || src.pii_redactions)
    ? (src.pii_redaction_tags || src.pii_redactions)
    : [];
  const piiTags = Array.from(
    new Set([
      ...existingTags.filter(tag => VALID_PII_TAGS.has(tag)),
      ...descPii.redactions,
      ...titlePii.redactions,
      ...titleNePii.redactions,
      ...muniWardPii.redactions,
    ])
  );

  const { photoAttached, photoSha256, localPhoto } = sanitizePhotoMetadata(
    src.photo,
    src.photo_sha256
  );

  const existingFp = String(src.dedup_fingerprint || '').trim();
  let fingerprint = /^[0-9a-f]{64}$/.test(existingFp) ? existingFp : '';
  if (!fingerprint && safeLon != null && safeLat != null) {
    fingerprint = await computeDedupFingerprint(safeLon, safeLat, event_date_utc, trigger);
  }

  const capturedAtUtc = normalizeIsoTimestampUtc(
    src.captured_at_utc ?? src.created_at_utc,
    nowIso
  );

  const duplicateCandidates = sanitizeDuplicateCandidatesForSchema(
    src.duplicate_candidates || src.duplicate_flags || src.duplicateFlags,
    reportId
  );

  return {
    report_id: reportId,
    feature_type: 'hazard_report',
    moderation_status: DEFAULT_MODERATION_STATUS,
    captured_at_utc: capturedAtUtc,
    event_date_utc,
    time_precision,
    location_source: locationSource,
    location_accuracy_m: locationAccuracyM,
    lon: safeLon,
    lat: safeLat,
    district,
    province,
    municipality_ward: municipalityWard,
    trigger,
    road_blocked: roadBlocked,
    fatalities: strictUnverifiedCount(src.fatalities),
    injuries: strictUnverifiedCount(src.injuries),
    description_redacted: descPii.text,
    title: safeTitle,
    title_ne: safeTitleNe,
    photo_attached: photoAttached,
    photo_sha256: photoAttached ? photoSha256 : null,
    exif_stripped: true,
    dedup_fingerprint: fingerprint || sha256FallbackHex(utf8ToBytes(reportId)),
    pii_redaction_applied: true,
    pii_redaction_tags: piiTags,
    offline_captured: src.offline_captured !== false,
    is_uat_fixture: src.is_uat_fixture === true,
    duplicate_candidates: duplicateCandidates,
    moderation_history: [],
    promoted_landslide_record: null,
    // Local-only EXIF-stripped JPEG preview (stripped out into bundle.photo_attachments on export)
    photo: localPhoto,
  };
}

/* ==========================================================================
   6. IndexedDB Persistence with Transparent localStorage / Memory Fallback
   ========================================================================== */

let cachedDbPromise = null;

function readFallbackList() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(FALLBACK_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
      }
    }
  } catch {
    // Fall through to in-memory store
  }
  return Array.from(MEMORY_FALLBACK.values());
}

function writeFallbackList(list) {
  MEMORY_FALLBACK.clear();
  for (const item of list) {
    if (item && item.report_id) MEMORY_FALLBACK.set(item.report_id, item);
  }
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(FALLBACK_STORAGE_KEY, JSON.stringify(list));
    }
  } catch {
    // Quota exceeded or restricted storage: in-memory fallback stays populated
  }
}

function sortReportsNewestFirst(list) {
  return [...list].sort((a, b) => {
    const ta = Date.parse(a?.captured_at_utc || a?.created_at_utc || '') || 0;
    const tb = Date.parse(b?.captured_at_utc || b?.created_at_utc || '') || 0;
    return tb - ta;
  });
}

/**
 * Open the native IndexedDB database (`traya_field_reports_v1`, store `reports`).
 * Resolves to `IDBDatabase` when available, or `null` if IndexedDB is blocked
 * or unsupported (queue operations transparently fall back to `localStorage`).
 *
 * @returns {Promise<IDBDatabase|null>}
 */
export function openReportDb() {
  if (typeof globalThis.indexedDB === 'undefined' || !globalThis.indexedDB) {
    return Promise.resolve(null);
  }
  if (cachedDbPromise) return cachedDbPromise;

  cachedDbPromise = new Promise(resolve => {
    try {
      const req = globalThis.indexedDB.open(REPORT_DB_NAME, REPORT_DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(REPORT_STORE_NAME)) {
          const store = db.createObjectStore(REPORT_STORE_NAME, { keyPath: 'report_id' });
          store.createIndex('captured_at_utc', 'captured_at_utc', { unique: false });
        }
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => {
          db.close();
          cachedDbPromise = null;
        };
        db.onclose = () => {
          cachedDbPromise = null;
        };
        resolve(db);
      };
      req.onerror = () => {
        cachedDbPromise = null;
        resolve(null);
      };
      req.onblocked = () => {
        cachedDbPromise = null;
        resolve(null);
      };
    } catch {
      cachedDbPromise = null;
      resolve(null);
    }
  });

  return cachedDbPromise;
}

/**
 * Normalize, redact PII, enforce strict null-not-0 semantics, and persist a
 * community field report into IndexedDB (or localStorage fallback).
 *
 * @param {object} record
 * @returns {Promise<object>} The saved, redacted report record
 */
export async function saveOfflineReport(record) {
  const normalized = await normalizeOfflineReportRecord(record);
  const db = await openReportDb();

  if (db) {
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(REPORT_STORE_NAME, 'readwrite');
        tx.objectStore(REPORT_STORE_NAME).put(normalized);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error || new Error('IndexedDB write failed'));
        tx.onabort = () => reject(tx.error || new Error('IndexedDB write aborted'));
      });
      return normalized;
    } catch {
      // Fall through to localStorage fallback if IndexedDB transaction fails
    }
  }

  const list = readFallbackList().filter(item => item?.report_id !== normalized.report_id);
  list.push(normalized);
  writeFallbackList(sortReportsNewestFirst(list));
  return normalized;
}

/**
 * List all queued offline reports sorted newest-first.
 *
 * @returns {Promise<Array<object>>}
 */
export async function listOfflineReports() {
  const db = await openReportDb();

  if (db) {
    try {
      const items = await new Promise((resolve, reject) => {
        const tx = db.transaction(REPORT_STORE_NAME, 'readonly');
        const req = tx.objectStore(REPORT_STORE_NAME).getAll();
        req.onsuccess = () => resolve(Array.isArray(req.result) ? req.result : []);
        req.onerror = () => reject(req.error || new Error('IndexedDB read failed'));
      });
      return sortReportsNewestFirst(items);
    } catch {
      // Fall through to localStorage fallback
    }
  }

  return sortReportsNewestFirst(readFallbackList());
}

/**
 * Delete a single queued offline report by `report_id`.
 *
 * @param {string} reportId
 * @returns {Promise<boolean>}
 */
export async function deleteOfflineReport(reportId) {
  const id = String(reportId || '').trim();
  if (!id) return false;
  const db = await openReportDb();

  if (db) {
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(REPORT_STORE_NAME, 'readwrite');
        tx.objectStore(REPORT_STORE_NAME).delete(id);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error || new Error('IndexedDB delete failed'));
        tx.onabort = () => reject(tx.error || new Error('IndexedDB delete aborted'));
      });
      return true;
    } catch {
      // Fall through to localStorage fallback
    }
  }

  const list = readFallbackList().filter(item => item?.report_id !== id);
  writeFallbackList(list);
  return true;
}

/**
 * Clear all queued offline reports from IndexedDB and fallback storage.
 *
 * @returns {Promise<boolean>}
 */
export async function clearOfflineReports() {
  const db = await openReportDb();

  if (db) {
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(REPORT_STORE_NAME, 'readwrite');
        tx.objectStore(REPORT_STORE_NAME).clear();
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error || new Error('IndexedDB clear failed'));
        tx.onabort = () => reject(tx.error || new Error('IndexedDB clear aborted'));
      });
    } catch {
      // Continue clearing fallback storage too
    }
  }

  writeFallbackList([]);
  return true;
}

/* ==========================================================================
   7. Governed Redacted Moderation Bundle Builder (DEOC / Agency Handover)
   ========================================================================== */

/**
 * Produce a clean JSON handover bundle ready for file download or DEOC/NDRRMA
 * human moderation.
 *
 * Every item in `bundle.reports` conforms strictly to
 * `schemas/community_report.v1.schema.json` (`additionalProperties: false`,
 * `feature_type: "hazard_report"`, `moderation_status: "pending_agency_review"`,
 * `exif_stripped: true`, `pii_redaction_applied: true`, strict `null`-not-`0`
 * `fatalities` and `injuries`). Any EXIF-stripped JPEG image previews are
 * separated into `bundle.photo_attachments` keyed by `report_id` and linked
 * via `photo_sha256`.
 *
 * @param {Array<object>} [reports=[]]
 * @returns {object}
 */
export function buildRedactedModerationBundle(reports = []) {
  const inputList = Array.isArray(reports) ? reports : [];
  const generatedAtUtc = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const photoAttachments = {};

  const sanitizedReports = inputList.map(raw => {
    const src = raw && typeof raw === 'object' ? raw : {};
    const reportId = sanitizeReportId(src.report_id || src.id);

    const descPii = redactPii(src.description_redacted ?? src.notes ?? src.description ?? '');
    const titlePii = redactPii(src.title ?? '');
    const rawTitleNe = src.title_ne != null ? String(src.title_ne).trim() : '';
    const titleNePii = rawTitleNe ? redactPii(rawTitleNe) : { text: '', redactions: [] };
    const muniPii = redactPii(src.municipality_ward ?? src.municipalityWard ?? '');

    const { event_date_utc, time_precision } = normalizeEventDateAndPrecision(
      src.event_date_utc ?? src.eventDateIso ?? src.date,
      src.time_precision ?? src.date_precision ?? src.datePrecision
    );

    const safeLon = clampNepalCoord(src.lon, 79.5, 88.8);
    const safeLat = clampNepalCoord(src.lat, 26.0, 31.0);
    const provinceRaw = String(src.province || '').trim();
    const province = CANONICAL_PROVINCES.has(provinceRaw) ? provinceRaw : null;
    const district = String(src.district || '').trim() || null;
    const trigger = normalizeTrigger(src.trigger);
    const roadBlocked = normalizeRoadBlocked(src.road_blocked ?? src.roadBlocked);
    const locationSource = normalizeLocationSource(src.location_source ?? src.locationSource);

    const accRaw = Number(src.location_accuracy_m ?? src.accuracy_m ?? src.accuracyM);
    const locationAccuracyM = Number.isFinite(accRaw) && accRaw >= 0 ? Number(accRaw.toFixed(1)) : null;

    const { photoAttached, photoSha256, localPhoto } = sanitizePhotoMetadata(
      src.photo,
      src.photo_sha256
    );
    if (localPhoto) {
      photoAttachments[reportId] = localPhoto;
    }

    const capturedAtUtc = normalizeIsoTimestampUtc(
      src.captured_at_utc ?? src.created_at_utc,
      generatedAtUtc
    );

    const existingTags = Array.isArray(src.pii_redaction_tags || src.pii_redactions)
      ? (src.pii_redaction_tags || src.pii_redactions)
      : [];
    const piiRedactionTags = Array.from(
      new Set([
        ...existingTags.filter(tag => VALID_PII_TAGS.has(tag)),
        ...descPii.redactions,
        ...titlePii.redactions,
        ...titleNePii.redactions,
        ...muniPii.redactions,
      ])
    );

    const existingFp = String(src.dedup_fingerprint || '').trim();
    const dedupFingerprint = /^[0-9a-f]{64}$/.test(existingFp)
      ? existingFp
      : (safeLon != null && safeLat != null
          ? sha256FallbackHex(
              utf8ToBytes(buildCanonicalDedupString(safeLon, safeLat, event_date_utc, trigger))
            )
          : sha256FallbackHex(utf8ToBytes(reportId)));

    const duplicateCandidates = sanitizeDuplicateCandidatesForSchema(
      src.duplicate_candidates || src.duplicate_flags || src.duplicateFlags,
      reportId
    );

    // Strictly conformant with schemas/community_report.v1.schema.json (additionalProperties: false)
    return {
      report_id: reportId,
      feature_type: 'hazard_report',
      moderation_status: DEFAULT_MODERATION_STATUS,
      captured_at_utc: capturedAtUtc,
      event_date_utc,
      time_precision,
      location_source: locationSource,
      lon: safeLon,
      lat: safeLat,
      district,
      province,
      trigger,
      road_blocked: roadBlocked,
      fatalities: strictUnverifiedCount(src.fatalities),
      injuries: strictUnverifiedCount(src.injuries),
      description_redacted: descPii.text,
      photo_attached: photoAttached,
      exif_stripped: true,
      dedup_fingerprint: dedupFingerprint,
      pii_redaction_applied: true,
      title: titlePii.text || (district ? `Community landslide observation (${district})` : 'Community landslide observation'),
      title_ne: titleNePii.text || null,
      municipality_ward: muniPii.text || null,
      location_accuracy_m: locationAccuracyM,
      photo_sha256: photoAttached ? photoSha256 : null,
      pii_redaction_tags: piiRedactionTags,
      offline_captured: src.offline_captured !== false,
      is_uat_fixture: src.is_uat_fixture === true,
      duplicate_candidates: duplicateCandidates,
      moderation_history: [],
      promoted_landslide_record: null,
    };
  });

  return {
    schema_version: 'community_report.v1',
    schema_ref: COMMUNITY_REPORT_SCHEMA_REF,
    bundle_type: 'traya_community_landslide_moderation_bundle',
    generated_at_utc: generatedAtUtc,
    governance_mode: GOVERNANCE_MODE,
    moderation_status: DEFAULT_MODERATION_STATUS,
    public_live_endpoint_enabled: false,
    exif_stripped: true,
    pii_redaction_applied: true,
    auto_merged: false,
    non_operational_disclaimer:
      'Unverified citizen/field screening observations queued offline in Nepal TRĀYA. Not an official Government of Nepal warning or statutory loss record; requires NDRRMA/DEOC/DHM human review prior to publication.',
    privacy_guarantees: {
      exif_stripped: true,
      pii_redaction_applied: true,
      reporter_identity_collected: false,
      unverified_null_not_zero_casualties: true,
      auto_merged: false,
    },
    report_count: sanitizedReports.length,
    reports: sanitizedReports,
    photo_attachments: photoAttachments,
  };
}
