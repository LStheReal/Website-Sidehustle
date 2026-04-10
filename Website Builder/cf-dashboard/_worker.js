/**
 * Cloudflare Pages Advanced Mode (_worker.js)
 * Intercepts /api/* routes, passes everything else to static assets.
 *
 * Env vars (set as Pages secrets):
 *   GOOGLE_TOKEN_JSON, GOOGLE_CREDENTIALS_JSON,
 *   LEADS_SHEET_ID, DRIVE_UPLOAD_FOLDER_ID, ANTHROPIC_API_KEY,
 *   CF_API_TOKEN, CF_ACCOUNT_ID, RESEND_API_KEY
 */

const COLUMN_NAMES = [
  "lead_id","scraped_at","search_query","business_name","category","address",
  "city","state","zip_code","phone","google_maps_url","rating","review_count",
  "owner_name","owner_email","owner_phone","emails","facebook","instagram",
  "linkedin","status","domain_option_1","domain_option_1_purchase","domain_option_1_price",
  "domain_option_2","domain_option_2_purchase","domain_option_2_price","domain_option_3",
  "domain_option_3_purchase","domain_option_3_price","website_url","email_sent_date",
  "response_date","notes","draft_url_1_earlydog","draft_url_2_bia","draft_url_3_liveblocks","draft_url_4_loveseen",
  "chosen_template","next_action","next_action_date","acquisition_source",
  "form_business_name","form_description","form_values","form_phone","form_address","form_services","form_strengths",
  "url_earlydog","url_bia","url_liveblocks","url_loveseen",
  "html_earlydog_drive_id","html_bia_drive_id","html_liveblocks_drive_id","html_loveseen_drive_id",
  "generation_status",
  "last_dashboard_visit","welcome_email_sent","last_reminder_sent",
  "reminder_count","subscription_status","stripe_payment_date",
  "live_email_sent","selected_domain",
];

const TEMPLATE_KEYS = ["earlydog", "bia", "liveblocks", "loveseen"];

// ── Preview HTML Cache (in-memory, keyed by leadId) ──
// Stores the generated HTML from preview so the order can reuse it without regenerating.
// Entries expire after 30 minutes.
const previewCache = new Map();
const PREVIEW_CACHE_TTL = 30 * 60 * 1000;

// ── Google OAuth (with caching to avoid rate limits) ─────
let _cachedToken = null;
let _cachedTokenExp = 0;

async function getAccessToken(env) {
  // Return cached token if still valid (4-minute TTL)
  if (_cachedToken && Date.now() < _cachedTokenExp) return _cachedToken;

  const creds = JSON.parse(env.GOOGLE_CREDENTIALS_JSON);
  const token = JSON.parse(env.GOOGLE_TOKEN_JSON);
  const installed = creds.installed || creds.web;
  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: installed.client_id,
      client_secret: installed.client_secret,
      refresh_token: token.refresh_token,
      grant_type: "refresh_token",
    }),
  });
  const data = await resp.json();
  if (!data.access_token) throw new Error("Google token refresh failed: " + JSON.stringify(data));

  _cachedToken = data.access_token;
  _cachedTokenExp = Date.now() + 240000; // 4 minutes
  return data.access_token;
}

// ── Google Sheets ─────────────────────────────────────────
async function getSheetValues(accessToken, sheetId) {
  const resp = await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Sheet1`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!resp.ok) throw new Error(`Sheets API error: ${resp.status}`);
  return resp.json();
}

function findLead(sheetData, leadId) {
  const rows = sheetData.values || [];
  for (let i = 1; i < rows.length; i++) {
    if ((rows[i][0] || "").trim() === leadId) {
      const lead = { _row_idx: i + 1 };
      COLUMN_NAMES.forEach((name, j) => { lead[name] = rows[i][j] || ""; });
      return lead;
    }
  }
  return null;
}

async function updateCells(accessToken, sheetId, rowIdx, updates) {
  const requests = [];
  for (const [colName, value] of Object.entries(updates)) {
    const colIdx = COLUMN_NAMES.indexOf(colName);
    if (colIdx < 0) continue;
    const colLetter = colIdx < 26
      ? String.fromCharCode(65 + colIdx)
      : String.fromCharCode(64 + Math.floor(colIdx / 26)) + String.fromCharCode(65 + (colIdx % 26));
    requests.push(
      fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${encodeURIComponent(`Sheet1!${colLetter}${rowIdx}`)}?valueInputOption=USER_ENTERED`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ values: [[String(value)]] }),
      })
    );
  }
  await Promise.all(requests);
}

// ── Google Drive ──────────────────────────────────────────
async function getOrCreateFolder(accessToken, parentId, folderName) {
  let query = `name='${folderName.replace(/'/g, "\\'")}' and mimeType='application/vnd.google-apps.folder' and trashed=false`;
  if (parentId) query += ` and '${parentId}' in parents`;
  const sr = await fetch(`https://www.googleapis.com/drive/v3/files?q=${encodeURIComponent(query)}&fields=files(id)`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  const sd = await sr.json();
  if (sd.files && sd.files.length > 0) return sd.files[0].id;
  const meta = { name: folderName, mimeType: "application/vnd.google-apps.folder" };
  if (parentId) meta.parents = [parentId];
  const cr = await fetch("https://www.googleapis.com/drive/v3/files?fields=id", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(meta),
  });
  return (await cr.json()).id;
}

async function uploadFileToDrive(accessToken, folderId, fileBytes, fileName, mimeType) {
  const metadata = { name: fileName, parents: [folderId] };
  const boundary = "----CFBoundary" + Date.now();
  const encoder = new TextEncoder();
  const parts = [
    encoder.encode(`--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(metadata)}\r\n`),
    encoder.encode(`--${boundary}\r\nContent-Type: ${mimeType}\r\n\r\n`),
    new Uint8Array(fileBytes),
    encoder.encode(`\r\n--${boundary}--`),
  ];
  const totalLen = parts.reduce((s, p) => s + p.byteLength, 0);
  const combined = new Uint8Array(totalLen);
  let offset = 0;
  for (const p of parts) { combined.set(p, offset); offset += p.byteLength; }
  const uploadResp = await fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": `multipart/related; boundary=${boundary}` },
    body: combined,
  });
  const uploadData = await uploadResp.json();
  return uploadData.id || null;
}

// ── AI Content ────────────────────────────────────────────
const TEMPLATE_PLACEHOLDERS = {
  earlydog: ["BUSINESS_NAME","TAGLINE","META_DESCRIPTION","HERO_TITLE_LINE1","HERO_TITLE_LINE2","HERO_DESCRIPTION","SERVICE_1_TITLE","SERVICE_1_DESCRIPTION","SERVICE_1_CTA","SERVICE_2_TITLE","SERVICE_2_DESCRIPTION","SERVICE_2_CTA","SERVICE_3_TITLE","SERVICE_3_DESCRIPTION","SERVICE_3_CTA","CTA_TITLE_LINE1","CTA_TITLE_LINE2","PHONE","EMAIL","ADDRESS"],
  bia: ["BUSINESS_NAME","BUSINESS_NAME_SHORT","TAGLINE","META_DESCRIPTION","SECTION_LABEL_HERO","HERO_TITLE_LINE1","HERO_TITLE_LINE2","HERO_TITLE_LINE3","INTRO_TEXT","INTRO_DESCRIPTION","SECTION_LABEL_SERVICES","SERVICES_HEADING","SERVICE_1_TITLE","SERVICE_1_DESCRIPTION","SERVICE_2_TITLE","SERVICE_2_DESCRIPTION","SERVICE_3_TITLE","SERVICE_3_DESCRIPTION","SERVICE_4_TITLE","SERVICE_4_DESCRIPTION","SECTION_LABEL_ABOUT","ABOUT_HEADING","ABOUT_DESCRIPTION","STAT_1_NUMBER","STAT_1_LABEL","STAT_2_NUMBER","STAT_2_LABEL","STAT_3_NUMBER","STAT_3_LABEL","CTA_TITLE_LINE1","CTA_TITLE_LINE2","CTA_TITLE_LINE3","PHONE","EMAIL","ADDRESS","OPENING_HOURS"],
  liveblocks: ["BUSINESS_NAME","BUSINESS_NAME_SHORT","TAGLINE","META_DESCRIPTION","SECTION_LABEL_HERO","HERO_TITLE_LINE1","HERO_TITLE_LINE2","HERO_WORD_1","HERO_WORD_2","HERO_WORD_3","HERO_WORD_4","HERO_DESCRIPTION","CTA_BUTTON_PRIMARY","CTA_BUTTON_SECONDARY","TRUST_LABEL","STAT_1_NUMBER","STAT_1_LABEL","STAT_2_NUMBER","STAT_2_LABEL","STAT_3_NUMBER","STAT_3_LABEL","STAT_4_NUMBER","STAT_4_LABEL","SECTION_LABEL_SERVICES","SERVICES_HEADING","SERVICES_DESCRIPTION","SERVICE_1_TITLE","SERVICE_1_DESCRIPTION","SERVICE_2_TITLE","SERVICE_2_DESCRIPTION","SERVICE_3_TITLE","SERVICE_3_DESCRIPTION","SERVICE_4_TITLE","SERVICE_4_DESCRIPTION","SERVICE_5_TITLE","SERVICE_5_DESCRIPTION","SERVICE_6_TITLE","SERVICE_6_DESCRIPTION","SECTION_LABEL_FEATURE","FEATURE_HEADING","FEATURE_DESCRIPTION","FEATURE_POINT_1","FEATURE_POINT_2","FEATURE_POINT_3","SECTION_LABEL_ABOUT","ABOUT_HEADING","ABOUT_LEAD","ABOUT_DESCRIPTION","VALUE_1_TITLE","VALUE_1_DESCRIPTION","VALUE_2_TITLE","VALUE_2_DESCRIPTION","VALUE_3_TITLE","VALUE_3_DESCRIPTION","CTA_HEADING_LINE1","CTA_HEADING_LINE2","CTA_DESCRIPTION","CONTACT_CARD_1_TITLE","CONTACT_CARD_1_DESCRIPTION","CONTACT_CARD_2_TITLE","CONTACT_CARD_2_DESCRIPTION","PHONE","PHONE_SHORT","EMAIL","ADDRESS","OPENING_HOURS","FOOTER_COL_1_TITLE","FOOTER_COL_1_LINK_1","FOOTER_COL_1_LINK_2","FOOTER_COL_1_LINK_3","FOOTER_COL_2_TITLE","FOOTER_COL_2_LINK_1","FOOTER_COL_2_LINK_2","FOOTER_COL_2_LINK_3"],
  loveseen: ["BUSINESS_NAME","TAGLINE","META_DESCRIPTION","NAV_CTA","NAV_LINK_1","NAV_LINK_2","NAV_LINK_3","NAV_LINK_4","HERO_TITLE_LINE1","HERO_TITLE_LINE2","HERO_CTA","SECTION_LABEL_ABOUT","ABOUT_HEADING_LINE1","ABOUT_HEADING_LINE2","ABOUT_LEAD","ABOUT_DESCRIPTION","ABOUT_CTA","STATEMENT_LABEL","STATEMENT_LINE1","STATEMENT_LINE2","STATEMENT_LINE3","SECTION_LABEL_SERVICES","SERVICES_HEADING","SERVICE_1_TITLE","SERVICE_1_DESCRIPTION","SERVICE_2_TITLE","SERVICE_2_DESCRIPTION","SERVICE_3_TITLE","SERVICE_3_DESCRIPTION","SERVICES_CTA","GALLERY_LABEL","INSTAGRAM_HANDLE","INSTAGRAM_URL","CONTACT_TAGLINE","EMAIL_PLACEHOLDER","CONTACT_LABEL_PHONE","CONTACT_LABEL_EMAIL","CONTACT_LABEL_ADDRESS","CONTACT_LABEL_HOURS","PHONE","EMAIL","ADDRESS","OPENING_HOURS","FOOTER_PRIVACY","FOOTER_TERMS","FOOTER_YEAR"],
};

// ── IMAGE_SLOT_MAP per template (placeholder key → slot name) ──
const IMAGE_SLOT_MAP = {
  earlydog: { IMAGE_HERO: "professional workspace", IMAGE_SERVICE_1: "service consultation", IMAGE_SERVICE_2: "teamwork quality", IMAGE_SERVICE_3: "finished project result" },
  bia: { IMAGE_HERO: "professional business hero", IMAGE_SHOWCASE: "showcase portfolio work", IMAGE_CTA: "modern workspace", IMAGE_CONTACT: "friendly team" },
  liveblocks: { IMAGE_FEATURE: "professional feature highlight", IMAGE_ABOUT: "team at work" },
  loveseen: { IMAGE_HERO: "elegant professional hero", IMAGE_ABOUT: "team portrait", IMAGE_GALLERY_1: "project result", IMAGE_GALLERY_2: "workspace detail", IMAGE_GALLERY_3: "finished work" },
};

// ── Template-specific PLACEHOLDER_DEFAULTS ──
// Mirrors the Python generate_website.py defaults for each template
const TEMPLATE_DEFAULTS = {
  earlydog: {
    BUSINESS_NAME: "Unser Unternehmen", TAGLINE: "Ihr Partner vor Ort", META_DESCRIPTION: "",
    HERO_TITLE_LINE1: "Willkommen bei", HERO_TITLE_LINE2: "unserem Service",
    HERO_DESCRIPTION: "Wir bieten professionelle Dienstleistungen für Ihr Unternehmen.",
    SERVICE_1_TITLE: "Service 1", SERVICE_1_DESCRIPTION: "Beschreibung unseres ersten Services.", SERVICE_1_CTA: "Mehr erfahren",
    SERVICE_2_TITLE: "Service 2", SERVICE_2_DESCRIPTION: "Beschreibung unseres zweiten Services.", SERVICE_2_CTA: "Mehr erfahren",
    SERVICE_3_TITLE: "Service 3", SERVICE_3_DESCRIPTION: "Beschreibung unseres dritten Services.", SERVICE_3_CTA: "Mehr erfahren",
    CTA_TITLE_LINE1: "Interesse geweckt?", CTA_TITLE_LINE2: "Kontaktieren Sie uns.",
    PHONE: "", EMAIL: "", ADDRESS: "",
    IMAGE_HERO: "assets/images/hero.svg", IMAGE_SERVICE_1: "assets/images/section1.svg",
    IMAGE_SERVICE_2: "assets/images/section2.svg", IMAGE_SERVICE_3: "assets/images/section3.svg",
  },
  bia: {
    BUSINESS_NAME: "Atelier Nord", BUSINESS_NAME_SHORT: "Atelier.", TAGLINE: "Qualität mit Handschlag", META_DESCRIPTION: "",
    SECTION_LABEL_HERO: "Willkommen", HERO_TITLE_LINE1: "Saubere Arbeit,", HERO_TITLE_LINE2: "starkes", HERO_TITLE_LINE3: "Finish",
    INTRO_TEXT: "Qualität und Verlässlichkeit", INTRO_DESCRIPTION: "Wir verbinden Präzision mit persönlicher Beratung für Ergebnisse mit Bestand.",
    SECTION_LABEL_SERVICES: "Leistungen", SERVICES_HEADING: "Was wir bieten",
    SERVICE_1_TITLE: "Beratung", SERVICE_1_DESCRIPTION: "Transparentes Erstgespräch zu Anforderungen und Ablauf.",
    SERVICE_2_TITLE: "Ausführung", SERVICE_2_DESCRIPTION: "Termintreue und präzise Umsetzung.",
    SERVICE_3_TITLE: "Feinschliff", SERVICE_3_DESCRIPTION: "Kontrolle aller Details für ein sauberes Resultat.",
    SERVICE_4_TITLE: "Nachbetreuung", SERVICE_4_DESCRIPTION: "Langfristige Unterstützung nach Projektabschluss.",
    SECTION_LABEL_ABOUT: "Über uns", ABOUT_HEADING: "Unser Anspruch", ABOUT_DESCRIPTION: "Strukturiert, termintreu und sauber bis ins Detail.",
    STAT_1_NUMBER: "10+", STAT_1_LABEL: "Jahre Erfahrung", STAT_2_NUMBER: "500+", STAT_2_LABEL: "Projekte",
    STAT_3_NUMBER: "100%", STAT_3_LABEL: "Engagement",
    CTA_TITLE_LINE1: "Bereit für", CTA_TITLE_LINE2: "den nächsten", CTA_TITLE_LINE3: "Schritt?",
    PHONE: "+41 44 123 45 67", EMAIL: "hallo@ateliernord.ch", ADDRESS: "Langstrasse 12, 8004 Zürich", OPENING_HOURS: "Di–Sa 9–18 Uhr",
    IMAGE_HERO: "assets/images/hero.svg", IMAGE_SHOWCASE: "assets/images/showcase.svg",
    IMAGE_CTA: "assets/images/cta.svg", IMAGE_CONTACT: "assets/images/contact.svg",
  },
  liveblocks: {
    BUSINESS_NAME: "TechFlow", BUSINESS_NAME_SHORT: "TechFlow.", TAGLINE: "Digitale Lösungen", META_DESCRIPTION: "",
    SECTION_LABEL_HERO: "Willkommen", HERO_TITLE_LINE1: "Moderne", HERO_TITLE_LINE2: "Lösungen für",
    HERO_WORD_1: "Qualität", HERO_WORD_2: "Vertrauen", HERO_WORD_3: "Erfahrung", HERO_WORD_4: "Service",
    HERO_DESCRIPTION: "Professionelle Dienstleistungen für Ihr Unternehmen.",
    CTA_BUTTON_PRIMARY: "Jetzt anrufen", CTA_BUTTON_SECONDARY: "E-Mail senden",
    TRUST_LABEL: "Vertrauen Sie uns", PHONE_SHORT: "Anrufen",
    STAT_1_NUMBER: "10+", STAT_1_LABEL: "Jahre", STAT_2_NUMBER: "500+", STAT_2_LABEL: "Kunden",
    STAT_3_NUMBER: "100%", STAT_3_LABEL: "Engagement", STAT_4_NUMBER: "24h", STAT_4_LABEL: "Erreichbar",
    SECTION_LABEL_SERVICES: "Leistungen", SERVICES_HEADING: "Unsere Leistungen", SERVICES_DESCRIPTION: "Entdecken Sie unser Angebot.",
    SERVICE_1_TITLE: "Beratung", SERVICE_1_DESCRIPTION: "Persönliche Beratung.",
    SERVICE_2_TITLE: "Umsetzung", SERVICE_2_DESCRIPTION: "Professionelle Ausführung.",
    SERVICE_3_TITLE: "Nachbetreuung", SERVICE_3_DESCRIPTION: "Langfristige Betreuung.",
    SERVICE_4_TITLE: "Planung", SERVICE_4_DESCRIPTION: "Optimale Ergebnisse.",
    SERVICE_5_TITLE: "Qualitätssicherung", SERVICE_5_DESCRIPTION: "Höchste Standards.",
    SERVICE_6_TITLE: "Kundendienst", SERVICE_6_DESCRIPTION: "Schnell und zuverlässig.",
    SECTION_LABEL_FEATURE: "Warum wir", FEATURE_HEADING: "Warum wir?",
    FEATURE_DESCRIPTION: "Qualität und Kundennähe.", FEATURE_POINT_1: "Erfahrung", FEATURE_POINT_2: "Betreuung", FEATURE_POINT_3: "Faire Preise",
    SECTION_LABEL_ABOUT: "Über uns", ABOUT_HEADING: "Über uns", ABOUT_LEAD: "Qualität und Vertrauen.",
    ABOUT_DESCRIPTION: "Ihr Partner für professionelle Lösungen.",
    VALUE_1_TITLE: "Qualität", VALUE_1_DESCRIPTION: "Höchste Ansprüche.", VALUE_2_TITLE: "Vertrauen", VALUE_2_DESCRIPTION: "Transparenz.",
    VALUE_3_TITLE: "Innovation", VALUE_3_DESCRIPTION: "Moderne Lösungen.",
    CTA_HEADING_LINE1: "Bereit für", CTA_HEADING_LINE2: "den nächsten Schritt?", CTA_DESCRIPTION: "Kontaktieren Sie uns.",
    CONTACT_CARD_1_TITLE: "Telefon", CONTACT_CARD_1_DESCRIPTION: "Anrufen",
    CONTACT_CARD_2_TITLE: "E-Mail", CONTACT_CARD_2_DESCRIPTION: "Schreiben",
    PHONE: "", EMAIL: "", ADDRESS: "", OPENING_HOURS: "Mo–Fr 08:00–18:00",
    FOOTER_COL_1_TITLE: "Navigation", FOOTER_COL_1_LINK_1: "Home", FOOTER_COL_1_LINK_2: "Leistungen", FOOTER_COL_1_LINK_3: "Kontakt",
    FOOTER_COL_2_TITLE: "Rechtliches", FOOTER_COL_2_LINK_1: "Datenschutz", FOOTER_COL_2_LINK_2: "AGB", FOOTER_COL_2_LINK_3: "Impressum",
    IMAGE_FEATURE: "assets/images/feature.svg", IMAGE_ABOUT: "assets/images/about.svg",
  },
  loveseen: {
    BUSINESS_NAME: "Atelier Nord", TAGLINE: "Qualität mit Handschlag", META_DESCRIPTION: "",
    NAV_CTA: "Kontakt", NAV_LINK_1: "Über uns", NAV_LINK_2: "Leistungen", NAV_LINK_3: "Galerie", NAV_LINK_4: "Kontakt",
    HERO_TITLE_LINE1: "Saubere Arbeit,", HERO_TITLE_LINE2: "starkes Finish", HERO_CTA: "Projekt anfragen",
    SECTION_LABEL_ABOUT: "Über uns", ABOUT_HEADING_LINE1: "Eine klare Haltung", ABOUT_HEADING_LINE2: "für starke Resultate",
    ABOUT_LEAD: "Wir verbinden Präzision, Verlässlichkeit und persönliche Beratung für Ergebnisse mit Bestand.",
    ABOUT_DESCRIPTION: "Unser Team arbeitet strukturiert, termintreu und sauber bis ins Detail.", ABOUT_CTA: "Unsere Leistungen",
    STATEMENT_LABEL: "Unser Versprechen", STATEMENT_LINE1: "Klare Planung,", STATEMENT_LINE2: "saubere Ausführung,", STATEMENT_LINE3: "spürbare Qualität.",
    SECTION_LABEL_SERVICES: "Was wir tun", SERVICES_HEADING: "Unsere Leistungen",
    SERVICE_1_TITLE: "Beratung", SERVICE_1_DESCRIPTION: "Transparentes Erstgespräch zu Anforderungen und Ablauf.",
    SERVICE_2_TITLE: "Ausführung", SERVICE_2_DESCRIPTION: "Termintreue und präzise Umsetzung.",
    SERVICE_3_TITLE: "Feinschliff", SERVICE_3_DESCRIPTION: "Kontrolle aller Details für ein sauberes Resultat.",
    SERVICES_CTA: "Unverbindlich anfragen",
    GALLERY_LABEL: "Einblicke", INSTAGRAM_HANDLE: "", INSTAGRAM_URL: "",
    CONTACT_TAGLINE: "Schreiben oder rufen Sie uns an.", EMAIL_PLACEHOLDER: "Deine E-Mail-Adresse",
    CONTACT_LABEL_PHONE: "Telefon", CONTACT_LABEL_EMAIL: "E-Mail", CONTACT_LABEL_ADDRESS: "Adresse", CONTACT_LABEL_HOURS: "Öffnungszeiten",
    PHONE: "+41 44 123 45 67", EMAIL: "hallo@ateliernord.ch", ADDRESS: "Langstrasse 12, 8004 Zürich", OPENING_HOURS: "Di–Sa 9–18 Uhr",
    FOOTER_PRIVACY: "Datenschutz", FOOTER_TERMS: "AGB", FOOTER_YEAR: "2026",
    IMAGE_HERO: "assets/images/hero.svg", IMAGE_ABOUT: "assets/images/about.svg",
    IMAGE_GALLERY_1: "assets/images/gallery1.svg", IMAGE_GALLERY_2: "assets/images/gallery2.svg", IMAGE_GALLERY_3: "assets/images/gallery3.svg",
  },
};

// ── Pexels API Integration ──
const THEME_QUERIES = {
  "beauty-salon": ["beauty salon interior", "hair styling", "spa treatment", "cosmetics", "beauty professional"],
  "wellness-fitness": ["yoga studio", "fitness gym", "wellness spa", "meditation", "personal training"],
  "medical": ["medical clinic", "doctor office", "dental practice", "healthcare professional", "pharmacy"],
  "construction-trade": ["construction work", "craftsman tools", "renovation", "painting wall", "building trade"],
  "food-hospitality": ["restaurant interior", "cafe ambiance", "food preparation", "bakery", "cuisine"],
  "tech-digital": ["modern office", "technology workspace", "digital business", "computer work", "startup"],
  "professional-office": ["business meeting", "professional office", "consulting", "corporate team", "workspace"],
  "local-service": ["local business", "service professional", "customer service", "store front", "workshop"],
};

function inferTheme(data) {
  const cat = ((data.category || "") + " " + (data.BUSINESS_NAME || "")).toLowerCase();
  if (/salon|coiffeur|friseur|beauty|kosmetik|nail|haar|hair|makeup|wimpern|lash/.test(cat)) return "beauty-salon";
  if (/yoga|fitness|gym|sport|wellness|massage|physio/.test(cat)) return "wellness-fitness";
  if (/arzt|praxis|dental|zahnarzt|doctor|klinik|clinic|apotheke|optik/.test(cat)) return "medical";
  if (/bau|maler|painter|schreiner|elektr|sanit|dachdeck|gipser|plattenleger|renovier|handwerk|craft/.test(cat)) return "construction-trade";
  if (/restaurant|café|cafe|bäckerei|bakery|gastro|catering|pizza|sushi|bar |bistro|küche/.test(cat)) return "food-hospitality";
  if (/tech|software|web|digital|it |computer|agentur|design|market/.test(cat)) return "tech-digital";
  if (/anwalt|lawyer|steuerber|treuhänd|notar|consult|beratung|versicher|immobilien/.test(cat)) return "professional-office";
  return "local-service";
}

async function searchPexels(env, query, orientation = "landscape") {
  const apiKey = env.PEXELS_API_KEY;
  if (!apiKey) return [];
  try {
    const url = `https://api.pexels.com/v1/search?query=${encodeURIComponent(query)}&orientation=${orientation}&per_page=5`;
    const resp = await fetch(url, { headers: { Authorization: apiKey } });
    if (!resp.ok) return [];
    const data = await resp.json();
    return (data.photos || []).map(p => p.src.large2x || p.src.large || p.src.original);
  } catch (e) { console.error("Pexels error:", e); return []; }
}

async function suggestBusinessImages(env, data, slotMap) {
  const theme = inferTheme(data);
  const queries = THEME_QUERIES[theme] || THEME_QUERIES["local-service"];
  const imageKeys = Object.keys(slotMap);
  const result = {};
  // Use the AI-determined category (English word) for more accurate Pexels results
  const categoryTerm = data.category || data.BUSINESS_NAME || "";

  // Search for images in parallel, one query per slot
  // Use different query index offset per slot to get variety
  const usedUrls = new Set();
  const promises = imageKeys.map(async (key, i) => {
    const slotDesc = slotMap[key] || queries[i % queries.length];
    const searchQuery = categoryTerm + " " + slotDesc;
    const urls = await searchPexels(env, searchQuery);
    // Pick the first URL not already used by another slot (avoid duplicates)
    for (const url of urls) {
      if (!usedUrls.has(url)) {
        result[key] = url;
        usedUrls.add(url);
        break;
      }
    }
    // Fallback to first result if all were duplicates
    if (!result[key] && urls.length > 0) {
      result[key] = urls[0];
    }
  });

  await Promise.all(promises);
  return result;
}

// ── AI Text Enrichment via Claude Haiku ──
async function enrichWithAI(env, data, templateKey) {
  if (!env.ANTHROPIC_API_KEY) return {};
  const name = data.BUSINESS_NAME || "";
  const category = data.category || "";
  const description = data._description || "";
  const services = data._services || "";
  const strengths = data._strengths || "";
  const city = data.city || "";
  // Skip AI if there's no meaningful input
  if (!description && !services && !strengths && !category && !name) return {};

  const context = [
    name ? `Firmenname: ${name}` : "",
    category ? `Branche: ${category}` : "",
    city ? `Standort: ${city}` : "",
    description ? `Beschreibung vom Kunden: ${description}` : "",
    services ? `Leistungen vom Kunden: ${services}` : "",
    strengths ? `Besonderheiten/Stärken vom Kunden: ${strengths}` : "",
  ].filter(Boolean).join("\n");

  const prompt = `Du bist ein Webseiten-Texter für Schweizer KMU. Erstelle professionelle, authentische deutsche Texte für eine Firmenwebsite.

Firma-Info:
${context}

WICHTIGE REGELN:
1. Die Texte vom Kunden (Beschreibung, Leistungen, Besonderheiten) sind die WICHTIGSTE Grundlage. Verwende sie als Basis für alle Texte. Du darfst umformulieren und professionell aufbereiten, aber der Inhalt MUSS dem entsprechen, was der Kunde geschrieben hat.
2. Verwende die Leistungen des Kunden DIREKT als SERVICE_1/2/3 Titel und Beschreibungen. Erfinde KEINE anderen Leistungen. Wenn der Kunde nur 1-2 Leistungen nennt, fülle die restlichen SERVICE-Felder mit "".
3. Verwende die Besonderheiten/Stärken des Kunden DIREKT für FEATURE_POINT, VALUE und STAT Felder. Erfinde KEINE konkreten Zahlen oder Statistiken (z.B. "500+ Kunden", "20 Jahre"). Verwende NUR Zahlen, die der Kunde explizit genannt hat. Wenn keine Zahlen: verwende beschreibende Wörter wie "Persönlich", "Regional", "Zuverlässig".
4. Erfinde KEINE Social-Media-Handles, Instagram-Namen, URLs oder E-Mail-Adressen.
5. Wenn der Kunde wenig Info gegeben hat: schreibe kürzere, allgemeinere Texte. Weniger Text ist besser als falscher Text. Setze Felder auf "" wenn du keinen passenden Inhalt hast.
6. Schreibe natürlich und professionell auf Deutsch (Schweizer Stil, kein ß). Verwende immer echte Umlaute (ä, ö, ü, Ä, Ö, Ü) — NIEMALS ae, oe, ue schreiben.

Generiere ein JSON-Objekt mit diesen Feldern:

{
  "TAGLINE": "kurzer Slogan basierend auf Kundenbeschreibung, max 8 Wörter",
  "HERO_TITLE_LINE1": "erste Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE2": "zweite Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE3": "dritte Zeile oder leer",
  "HERO_DESCRIPTION": "1-2 Sätze basierend auf Kundenbeschreibung, max 150 Zeichen",
  "ABOUT_HEADING": "Überschrift Über-uns-Bereich, 2-4 Wörter",
  "ABOUT_LEAD": "1 Satz Einleitung basierend auf Kundenbeschreibung, max 100 Zeichen",
  "ABOUT_DESCRIPTION": "2-3 Sätze über die Firma — NUR basierend auf Kundeninfo",
  "INTRO_TEXT": "kurze Einleitung, 3-5 Wörter",
  "INTRO_DESCRIPTION": "1 Satz Firmenbeschreibung basierend auf Kundentext, max 120 Zeichen",
  "FEATURE_HEADING": "Überschrift Vorteile-Bereich, 2-4 Wörter",
  "FEATURE_DESCRIPTION": "1 Satz warum diese Firma, max 100 Zeichen",
  "FEATURE_POINT_1": "Vorteil aus Kundenwerten, 2-3 Wörter, oder leer",
  "FEATURE_POINT_2": "Vorteil aus Kundenwerten, 2-3 Wörter, oder leer",
  "FEATURE_POINT_3": "Vorteil aus Kundenwerten, 2-3 Wörter, oder leer",
  "SERVICE_1_TITLE": "Leistung aus Kundenbeschreibung, oder leer",
  "SERVICE_1_DESCRIPTION": "1 Satz zu Leistung 1, oder leer",
  "SERVICE_2_TITLE": "Leistung aus Kundenbeschreibung, oder leer",
  "SERVICE_2_DESCRIPTION": "1 Satz zu Leistung 2, oder leer",
  "SERVICE_3_TITLE": "Leistung aus Kundenbeschreibung, oder leer",
  "SERVICE_3_DESCRIPTION": "1 Satz zu Leistung 3, oder leer",
  "CTA_DESCRIPTION": "Handlungsaufforderung, 1 Satz",
  "CTA_TITLE_LINE1": "CTA Titel Zeile 1, 2-3 Wörter",
  "CTA_TITLE_LINE2": "CTA Titel Zeile 2, 2-3 Wörter",
  "VALUE_1_TITLE": "Wert aus Kundeninfo, 1-2 Wörter, oder leer",
  "VALUE_1_DESCRIPTION": "kurze Beschreibung basierend auf Kundentext, oder leer",
  "VALUE_2_TITLE": "Wert aus Kundeninfo, 1-2 Wörter, oder leer",
  "VALUE_2_DESCRIPTION": "kurze Beschreibung basierend auf Kundentext, oder leer",
  "VALUE_3_TITLE": "Wert aus Kundeninfo, 1-2 Wörter, oder leer",
  "VALUE_3_DESCRIPTION": "kurze Beschreibung basierend auf Kundentext, oder leer",
  "STATEMENT_LINE1": "Statement Zeile 1, 2-4 Wörter",
  "STATEMENT_LINE2": "Statement Zeile 2, 2-4 Wörter",
  "STATEMENT_LINE3": "Statement Zeile 3, 2-4 Wörter",
  "META_DESCRIPTION": "SEO-Beschreibung basierend auf Kundentext, max 155 Zeichen",
  "INSTAGRAM_HANDLE": "NUR wenn vom Kunden angegeben, sonst leer",
  "CATEGORY": "Branche der Firma als ein Wort auf Englisch, z.B. painter, hairdresser, restaurant, fitness, dentist, lawyer, bakery, plumber, architect, photographer, florist — wähle das passendste"
}

Antworte NUR mit dem JSON-Objekt, kein anderer Text.`;

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 2000,
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!resp.ok) { console.error("AI enrichment failed:", resp.status); return {}; }
    const result = await resp.json();
    const text = (result.content || []).map(b => b.text || "").join("");
    // Extract JSON from response (handle markdown code blocks)
    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (!jsonMatch) return {};
    return JSON.parse(jsonMatch[0]);
  } catch (e) { console.error("AI enrichment error:", e); return {}; }
}

// ── Merge lead data with template defaults + Pexels images ──
async function mergeWithDefaults(env, templateKey, leadData, quickMode = false) {
  const defaults = TEMPLATE_DEFAULTS[templateKey] || {};
  const merged = { ...defaults };

  // Override defaults with lead data (non-empty values only)
  for (const [key, value] of Object.entries(leadData)) {
    if (key.startsWith("_")) continue;
    if (value !== null && value !== undefined && value !== "") {
      merged[key] = String(value);
    }
  }

  // Quick mode: skip AI + Pexels (used for step 3 thumbnail previews)
  if (quickMode) {
    if (!merged.META_DESCRIPTION) {
      const name = merged.BUSINESS_NAME || "";
      const tagline = merged.TAGLINE || "";
      merged.META_DESCRIPTION = tagline ? `${name} — ${tagline}` : name;
    }
    return merged;
  }

  // AI text enrichment — generates unique copy based on business info
  const aiText = await enrichWithAI(env, { ...merged, _description: leadData._description || "", _services: leadData._services || "", _strengths: leadData._strengths || "" }, templateKey);
  let aiCategory = "";
  for (const [key, value] of Object.entries(aiText)) {
    if (key === "CATEGORY") {
      aiCategory = String(value);
      continue;
    }
    if (!key.startsWith("IMAGE_")) {
      // Allow AI to return empty strings to intentionally clear defaults
      // (e.g. SERVICE_3 when business only has 2 services, or INSTAGRAM_HANDLE)
      if (value !== null && value !== undefined) {
        merged[key] = String(value);
      }
    }
  }
  merged._aiCategory = aiCategory;

  if (!merged.META_DESCRIPTION) {
    const name = merged.BUSINESS_NAME || "";
    const tagline = merged.TAGLINE || "";
    merged.META_DESCRIPTION = tagline ? `${name} — ${tagline}` : name;
  }

  // Fetch Pexels images for IMAGE_* slots not explicitly set by user uploads
  const hasBusinessContext = !!(leadData._description || leadData._services || leadData._strengths || leadData.category || (leadData.BUSINESS_NAME && leadData.BUSINESS_NAME !== ""));
  const slotMap = IMAGE_SLOT_MAP[templateKey] || {};
  if (hasBusinessContext) {
    if (aiCategory) merged.category = aiCategory;
    const userProvidedImages = {};
    for (const key of Object.keys(slotMap)) {
      if (leadData[key] && !leadData[key].startsWith("assets/")) {
        userProvidedImages[key] = true;
      }
    }
    const autoImages = await suggestBusinessImages(env, merged, slotMap);
    for (const [placeholder, imageUrl] of Object.entries(autoImages)) {
      if (!userProvidedImages[placeholder]) {
        merged[placeholder] = imageUrl;
      }
    }
  }

  return merged;
}

// ── Convert lead sheet data to placeholder data ──
function leadToPlaceholderData(lead, customizations) {
  const cust = customizations || {};
  const data = {};

  const name = lead.business_name || "";
  if (name) {
    data.BUSINESS_NAME = name;
    data.BUSINESS_NAME_SHORT = name.split(/\s+/).slice(0, 2).join(" ");
  }
  if (lead.phone) { data.PHONE = lead.phone; data.PHONE_SHORT = lead.phone; }
  const email = lead.owner_email || lead.emails || "";
  if (email) data.EMAIL = email;
  if (lead.address || lead.city) data.ADDRESS = lead.address || lead.city;
  if (lead.category) data.category = lead.category;
  if (lead.city) data.city = lead.city;

  // Contact info from customizations (no-code users can provide these)
  if (cust.phone) { data.PHONE = cust.phone; data.PHONE_SHORT = cust.phone; }
  if (cust.address) data.ADDRESS = cust.address;

  // Pass description, services, strengths as AI context — NOT as direct placeholder overrides.
  // These are used by enrichWithAI() to generate proper unique text for each section.
  if (cust.description) data._description = cust.description.trim();
  if (cust.services) data._services = cust.services.trim();
  if (cust.strengths) data._strengths = cust.strengths.trim();
  // Legacy fallback: old "values" field maps to strengths
  if (!cust.services && !cust.strengths && cust.values) {
    data._strengths = cust.values.trim();
  }

  return data;
}

async function generateAIImagePlacement(env, templateKey, imageFilenames, business) {
  if (!env.ANTHROPIC_API_KEY || !imageFilenames.length) return null;
  const slots = TEMPLATE_IMAGE_SLOTS[templateKey];
  if (!slots) return null;

  // If images >= slots: skip AI, use sequential assignment (all slots get an image, guaranteed)
  // This is faster and more reliable than asking the AI to pick from many images
  if (imageFilenames.length >= slots.length) {
    const placement = {};
    for (let i = 0; i < slots.length; i++) {
      placement[slots[i].slot] = i;
    }
    return placement;
  }

  // If images < slots: use AI to decide which slots get the few available images
  // ALL images must be used
  const slotDescs = slots.map(s => `"${s.slot}": ${s.desc}`).join("\n");
  const imgList = imageFilenames.map((f, i) => `${i}: "${f}"`).join("\n");

  const rule = `WICHTIG: Es gibt ${imageFilenames.length} Bilder und ${slots.length} Slots. ALLE ${imageFilenames.length} Bilder MÜSSEN verwendet werden, jedes genau einmal. Ordne jedem Bild den passendsten Slot zu. Slots ohne Bild werden NICHT zugeordnet (Platzhalter bleibt). NIEMALS ein Bild doppelt verwenden.`;

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001", max_tokens: 500,
        system: "Du ordnest Bilder den passenden Positionen auf einer Website zu. Basierend auf Dateinamen und Geschäftskontext. Jedes Bild darf NUR EINMAL verwendet werden. Slots ohne passendes Bild bleiben leer (nicht im JSON). NUR JSON ausgeben.",
        messages: [{ role: "user", content: `Geschäft: ${business}\n\nBild-Slots auf der Website:\n${slotDescs}\n\nVerfügbare Bilder:\n${imgList}\n\n${rule}\n\nAntwort als JSON-Objekt: { "slot_name": bild_index, ... }\nNur Slots mit zugeordnetem Bild auflisten. Beispiel bei 2 Bildern und 5 Slots: { "hero": 0, "about": 1 }` }],
      }),
    });
    const data = await resp.json();
    let text = data.content[0].text.trim();
    if (text.startsWith("```")) text = text.split("\n").slice(1).join("\n").replace(/```\s*$/, "").trim();
    return JSON.parse(text);
  } catch (e) {
    console.error("AI image placement failed:", e);
    return null;
  }
}

async function generateAIContent(env, lead, templateKey, customizations) {
  if (!env.ANTHROPIC_API_KEY) return null;
  const placeholderKeys = TEMPLATE_PLACEHOLDERS[templateKey];
  if (!placeholderKeys) return null;
  const phone = lead.phone || "", email = lead.owner_email || lead.emails || "";
  const fixedValues = {
    PHONE: phone || "Telefon", PHONE_SHORT: phone.slice(-13) || "Anrufen",
    EMAIL: email || "info@example.ch", ADDRESS: lead.address || lead.city || "Schweiz",
    OPENING_HOURS: "Mo\u2013Fr 08:00\u201318:00", FOOTER_YEAR: "2026",
    FOOTER_PRIVACY: "Datenschutz", FOOTER_TERMS: "AGB",
    EMAIL_PLACEHOLDER: "ihre@email.ch", CONTACT_LABEL_PHONE: "Telefon",
    CONTACT_LABEL_EMAIL: "E-Mail", CONTACT_LABEL_ADDRESS: "Adresse",
    CONTACT_LABEL_HOURS: "\u00d6ffnungszeiten", INSTAGRAM_URL: "#",
  };
  const aiKeys = placeholderKeys.filter(k => !(k in fixedValues));
  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001", max_tokens: 2500,
        system: "Du bist ein professioneller Website-Texter f\u00fcr Schweizer KMUs. Deutsch, modern, pr\u00e4gnant. Hero-Titel: max 3-4 W\u00f6rter. BUSINESS_NAME_SHORT: erstes Wort + Punkt. Stats: '15+', '500+'. Services: branchenspezifisch. Verwende immer echte Umlaute (\u00e4, \u00f6, \u00fc, \u00c4, \u00d6, \u00dc) \u2014 NIEMALS ae, oe, ue schreiben. NUR JSON.",
        messages: [{ role: "user", content: `Gesch\u00e4ft: ${lead.business_name}\nBranche: ${lead.category}\nStadt: ${lead.city}\nBeschreibung: ${customizations.description || ""}\nWerte: ${customizations.values || ""}\n\nJSON mit Schl\u00fcsseln:\n${JSON.stringify(aiKeys)}` }],
      }),
    });
    const data = await resp.json();
    let text = data.content[0].text.trim();
    if (text.startsWith("```")) text = text.split("\n").slice(1).join("\n").replace(/```\s*$/, "").trim();
    return { ...fixedValues, ...JSON.parse(text) };
  } catch (e) { console.error("AI failed:", e); return null; }
}

function buildFallbackReplacements(lead, cust) {
  const biz = lead.business_name || "Mein Business", city = lead.city || "", phone = lead.phone || "";
  const email = lead.owner_email || lead.emails || "", category = lead.category || "";
  const short = biz.split(",")[0].split(" ")[0] || "Business";
  const desc = (cust || {}).description || "";
  return {
    BUSINESS_NAME: biz, BUSINESS_NAME_SHORT: short,
    TAGLINE: city ? `Ihr Partner in ${city}` : "Ihr Partner f\u00fcr Qualit\u00e4t",
    META_DESCRIPTION: city ? `${biz} \u2014 ${category} in ${city}` : biz,
    HERO_TITLE_LINE1: biz.includes(",") ? biz.split(",")[0] : biz,
    HERO_TITLE_LINE2: city ? `in ${city}` : "Qualit\u00e4t & Vertrauen",
    HERO_TITLE_LINE3: category || "Ihr Experte",
    HERO_DESCRIPTION: desc || `Willkommen bei ${biz}. Ihr Partner f\u00fcr ${(category || "Dienstleistungen").toLowerCase()} in ${city || "Ihrer Region"}.`,
    HERO_CTA: "Kontakt aufnehmen", HERO_WORD_1: category || "Qualit\u00e4t", HERO_WORD_2: "Vertrauen", HERO_WORD_3: "Erfahrung", HERO_WORD_4: "Service",
    PHONE: phone || "Telefon", PHONE_SHORT: (phone || "").slice(-13) || "Anrufen",
    EMAIL: email || "info@example.ch", ADDRESS: lead.address || city || "Schweiz",
    OPENING_HOURS: "Mo\u2013Fr 08:00\u201318:00", NAV_CTA: "Kontakt",
    SECTION_LABEL_HERO: "Willkommen", SECTION_LABEL_SERVICES: "Unsere Leistungen",
    SECTION_LABEL_ABOUT: "\u00dcber uns", SECTION_LABEL_FEATURE: "Warum wir",
    TRUST_LABEL: `Vertrauen Sie ${short}`,
    STAT_1_NUMBER: "10+", STAT_1_LABEL: "Jahre Erfahrung", STAT_2_NUMBER: "500+", STAT_2_LABEL: "Zufriedene Kunden",
    STAT_3_NUMBER: "100%", STAT_3_LABEL: "Engagement", STAT_4_NUMBER: "24h", STAT_4_LABEL: "Erreichbar",
    SERVICES_HEADING: "Unsere Leistungen", SERVICES_DESCRIPTION: `Entdecken Sie unser Angebot bei ${biz}.`, SERVICES_CTA: "Mehr erfahren",
    SERVICE_1_TITLE: "Beratung", SERVICE_1_DESCRIPTION: "Pers\u00f6nliche Beratung.", SERVICE_1_CTA: "Mehr \u2192",
    SERVICE_2_TITLE: "Umsetzung", SERVICE_2_DESCRIPTION: "Professionelle Ausf\u00fchrung.", SERVICE_2_CTA: "Mehr \u2192",
    SERVICE_3_TITLE: "Nachbetreuung", SERVICE_3_DESCRIPTION: "Langfristige Betreuung.", SERVICE_3_CTA: "Mehr \u2192",
    SERVICE_4_TITLE: "Planung", SERVICE_4_DESCRIPTION: "Optimale Ergebnisse.",
    SERVICE_5_TITLE: "Qualit\u00e4tssicherung", SERVICE_5_DESCRIPTION: "H\u00f6chste Standards.",
    SERVICE_6_TITLE: "Kundendienst", SERVICE_6_DESCRIPTION: "Schnell und zuverl\u00e4ssig.",
    FEATURE_HEADING: `Warum ${short}?`, FEATURE_DESCRIPTION: `Qualit\u00e4t und Kundenn\u00e4he in ${city || "der Schweiz"}.`,
    FEATURE_POINT_1: "Langj\u00e4hrige Erfahrung", FEATURE_POINT_2: "Pers\u00f6nliche Betreuung", FEATURE_POINT_3: "Faire Preise",
    ABOUT_HEADING: `\u00dcber ${short}`, ABOUT_HEADING_LINE1: "\u00dcber", ABOUT_HEADING_LINE2: short,
    ABOUT_LEAD: `${biz} steht f\u00fcr Qualit\u00e4t.`, ABOUT_DESCRIPTION: desc || `Ihr Partner in ${city || "der Schweiz"}.`, ABOUT_CTA: "Mehr \u00fcber uns",
    VALUE_1_TITLE: "Qualit\u00e4t", VALUE_1_DESCRIPTION: "H\u00f6chste Anspr\u00fcche.", VALUE_2_TITLE: "Vertrauen", VALUE_2_DESCRIPTION: "Transparenz.",
    VALUE_3_TITLE: "Innovation", VALUE_3_DESCRIPTION: "Moderne L\u00f6sungen.",
    CTA_TITLE_LINE1: "Bereit f\u00fcr", CTA_TITLE_LINE2: "den n\u00e4chsten Schritt?", CTA_TITLE_LINE3: "",
    CTA_HEADING_LINE1: "Bereit f\u00fcr", CTA_HEADING_LINE2: "den n\u00e4chsten Schritt?",
    CTA_DESCRIPTION: `Kontaktieren Sie ${biz} noch heute.`, CTA_BUTTON_PRIMARY: "Jetzt anrufen", CTA_BUTTON_SECONDARY: "E-Mail senden",
    CONTACT_TAGLINE: "Wir freuen uns auf Sie", CONTACT_LABEL_PHONE: "Telefon", CONTACT_LABEL_EMAIL: "E-Mail",
    CONTACT_LABEL_ADDRESS: "Adresse", CONTACT_LABEL_HOURS: "\u00d6ffnungszeiten",
    CONTACT_CARD_1_TITLE: "Telefon", CONTACT_CARD_1_DESCRIPTION: phone || "Anrufen",
    CONTACT_CARD_2_TITLE: "E-Mail", CONTACT_CARD_2_DESCRIPTION: email || "Schreiben",
    INTRO_TEXT: `Willkommen bei ${biz}`, INTRO_DESCRIPTION: desc || `Ihr Partner f\u00fcr ${(category || "Qualit\u00e4t").toLowerCase()}.`,
    STATEMENT_LABEL: "Unser Versprechen", STATEMENT_LINE1: "Qualit\u00e4t.", STATEMENT_LINE2: "Vertrauen.", STATEMENT_LINE3: "Leidenschaft.",
    GALLERY_LABEL: "Einblicke", INSTAGRAM_HANDLE: "", INSTAGRAM_URL: "#", EMAIL_PLACEHOLDER: "ihre@email.ch",
    NAV_LINK_1: "Home", NAV_LINK_2: "\u00dcber uns", NAV_LINK_3: "Leistungen", NAV_LINK_4: "Kontakt",
    FOOTER_YEAR: "2026", FOOTER_PRIVACY: "Datenschutz", FOOTER_TERMS: "AGB",
    FOOTER_COL_1_TITLE: "Navigation", FOOTER_COL_1_LINK_1: "Home", FOOTER_COL_1_LINK_2: "Leistungen", FOOTER_COL_1_LINK_3: "Kontakt",
    FOOTER_COL_2_TITLE: "Rechtliches", FOOTER_COL_2_LINK_1: "Datenschutz", FOOTER_COL_2_LINK_2: "AGB", FOOTER_COL_2_LINK_3: "Impressum",
  };
}

// ── Helpers ───────────────────────────────────────────────
function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
  });
}

// ── Route Handlers ────────────────────────────────────────
async function handleGetLead(leadId, env, ctx) {
  if (!leadId || leadId.length > 50)
    return jsonResp({ error: "Ung\u00fcltiges Format. Pr\u00fcfe die E-Mail mit deinem Code." }, 400);
  let accessToken, sheetData;
  try { accessToken = await getAccessToken(env); sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID); }
  catch (e) { console.error("Sheet error:", e); return jsonResp({ error: "Verbindungsfehler. Versuche es erneut." }, 500); }

  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Code nicht gefunden. Pr\u00fcfe die E-Mail." }, 404);

  // Track dashboard visit (fire-and-forget)
  if (ctx) ctx.waitUntil(updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { last_dashboard_visit: new Date().toISOString() }).catch(() => {}));

  const draftSuffixes = ["1_earlydog", "2_bia", "3_liveblocks", "4_loveseen"];
  const previews = [];
  for (let i = 0; i < 4; i++) {
    let url = (lead[`draft_url_${draftSuffixes[i]}`] || "").trim();
    if (!url || !(url.startsWith("http") || url.startsWith("/"))) url = `/api/preview/${leadId}/${TEMPLATE_KEYS[i]}`;
    previews.push(url);
  }

  const domains = [];
  for (let i = 1; i <= 3; i++) {
    const d = (lead[`domain_option_${i}`] || "").trim();
    if (d) { const tld = d.includes(".") ? "."+d.split(".").pop() : ".ch"; domains.push({ domain: d, tld, available: true }); }
  }
  if (!domains.length) {
    let clean = (lead.business_name||"").toLowerCase().replace(/\u00e4/g,"ae").replace(/\u00f6/g,"oe").replace(/\u00fc/g,"ue").replace(/[^a-z0-9]/g,"").slice(0,30)||"meinbusiness";
    domains.push({ domain: `${clean}.ch`, tld: ".ch", available: true }, { domain: `${clean}.com`, tld: ".com", available: true }, { domain: `${clean}-online.ch`, tld: ".ch", available: true });
  }

  // Set acquisition_source to "outreach" if not already set (code-based leads were contacted)
  if (!lead.acquisition_source) {
    try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { acquisition_source: "outreach" }); }
    catch (e) { console.error("Source update error:", e); }
  }

  return jsonResp({ lead_id: leadId, business_name: lead.business_name, category: lead.category, city: lead.city, phone: lead.phone,
    owner_email: lead.owner_email, owner_name: lead.owner_name, address: lead.address, status: lead.status, previews, domains,
    chosen_template: lead.chosen_template, notes: lead.notes, acquisition_source: lead.acquisition_source,
    form_business_name: lead.form_business_name, form_description: lead.form_description,
    form_values: lead.form_values, form_phone: lead.form_phone, form_address: lead.form_address,
    form_services: lead.form_services, form_strengths: lead.form_strengths,
    url_earlydog: lead.url_earlydog, url_bia: lead.url_bia, url_liveblocks: lead.url_liveblocks, url_loveseen: lead.url_loveseen,
    generation_status: lead.generation_status,
    html_earlydog_drive_id: lead.html_earlydog_drive_id, html_bia_drive_id: lead.html_bia_drive_id,
    html_liveblocks_drive_id: lead.html_liveblocks_drive_id, html_loveseen_drive_id: lead.html_loveseen_drive_id });
}

// ── Append a new row to the sheet ────────────────────────
async function appendRow(accessToken, sheetId, values) {
  const resp = await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/Sheet1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ values: [values] }),
    }
  );
  if (!resp.ok) throw new Error("Append row failed: " + resp.status);
  return resp.json();
}

// ── Register new lead (no-code flow) ─────────────────────
async function handleRegister(request, env) {
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }
  const email = (body.email || "").trim().toLowerCase();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return jsonResp({ error: "Bitte gib eine gültige E-Mail-Adresse ein." }, 400);
  }

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch (e) { return jsonResp({ error: "Verbindungsfehler." }, 500); }

  // Always create a new lead — no dedup. No-code users start fresh every session.
  // To return to an existing site, users must use their access code (lead_id).

  // Generate a 12-char hex lead_id from email + timestamp
  const encoder = new TextEncoder();
  const data = encoder.encode(email + Date.now().toString());
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const leadId = hashArray.map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 12);

  // Build row explicitly — only set known fields, everything else stays empty
  const now = new Date().toISOString();
  const row = [];
  for (let i = 0; i < COLUMN_NAMES.length; i++) {
    switch (COLUMN_NAMES[i]) {
      case "lead_id":            row.push(leadId); break;
      case "scraped_at":         row.push(now); break;
      case "owner_email":        row.push(email); break;
      case "emails":             row.push(email); break;
      case "status":             row.push("registered_no_code"); break;
      case "acquisition_source": row.push("organic"); break;
      default:                   row.push(""); break;
    }
  }

  console.log("[register] New lead:", leadId, "email:", email, "row length:", row.length,
    "non-empty cells:", row.filter(v => v !== "").length);

  try { await appendRow(accessToken, env.LEADS_SHEET_ID, row); }
  catch (e) { console.error("Append error:", e); return jsonResp({ error: "Registrierung fehlgeschlagen." }, 500); }

  // Welcome email is sent AFTER all 4 websites are generated (in handleGenerateAll step 5)
  // so the user gets the email with preview screenshots included

  return jsonResp({
    lead_id: leadId,
    business_name: "",
    category: "",
    city: "",
    phone: "",
    owner_email: email,
    owner_name: "",
    address: "",
    status: "registered_no_code",
    previews: TEMPLATE_KEYS.map(t => `/api/preview/${leadId}/${t}`),
    domains: [],
    chosen_template: "",
    notes: "",
  });
}

// ── Update lead data (no-code flow: add business info) ───
async function handleUpdateLead(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  const updates = {};
  if (body.business_name) updates.business_name = body.business_name;
  if (body.description || body.values) {
    const existingNotes = lead.notes ? (function() { try { return JSON.parse(lead.notes); } catch { return {}; } })() : {};
    if (body.description) existingNotes.description = body.description;
    if (body.values) existingNotes.values = body.values;
    updates.notes = JSON.stringify(existingNotes);
  }
  if (body.category) updates.category = body.category;
  if (body.city) updates.city = body.city;
  if (body.phone) updates.phone = body.phone;
  if (body.address) updates.address = body.address;
  if (body.chosen_template) updates.chosen_template = body.chosen_template;
  if (body.domain_option_1) updates.domain_option_1 = body.domain_option_1;
  if (body.domain_option_2) updates.domain_option_2 = body.domain_option_2;
  if (body.domain_option_3) updates.domain_option_3 = body.domain_option_3;

  if (Object.keys(updates).length > 0) {
    try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
    catch (e) { console.error("Update error:", e); return jsonResp({ error: "Update fehlgeschlagen." }, 500); }
  }

  return jsonResp({ success: true });
}

async function handleOrder(leadId, request, env) {
  if (!leadId || leadId.length > 50) return jsonResp({ error: "Invalid lead ID" }, 400);
  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead not found" }, 404);
  const fd = await request.formData();
  const chosenTemplate = fd.get("chosen_template")||"", description = fd.get("description")||"";
  const services = fd.get("services")||"", strengths = fd.get("strengths")||"";
  const selectedDomain = fd.get("selected_domain")||"";
  const phone = fd.get("phone")||"", address = fd.get("address")||"";
  if (fd.get("agreed_to_terms") !== "true") return jsonResp({ error: "AGB müssen akzeptiert werden." }, 400);
  if (!chosenTemplate) return jsonResp({ error: "Kein Template gewählt." }, 400);

  const logo = fd.get("logo");
  const images = fd.getAll("images");

  // 1. Upload files to Google Drive (non-blocking for main flow)
  let driveFolderUrl = "";
  try {
    const folderId = await getOrCreateFolder(accessToken, env.DRIVE_UPLOAD_FOLDER_ID, `${lead.business_name||leadId} (${leadId})`);
    driveFolderUrl = `https://drive.google.com/drive/folders/${folderId}`;
    if (logo && logo.size > 0) await uploadFileToDrive(accessToken, folderId, await logo.arrayBuffer(), `logo_${logo.name}`, logo.type||"image/png");
    for (const img of images) {
      if (img && img.size > 0) await uploadFileToDrive(accessToken, folderId, await img.arrayBuffer(), `image_${img.name}`, img.type||"image/png");
    }
  } catch (e) { console.error("Drive error:", e); }

  // 2. Use cached preview HTML if available, otherwise regenerate
  let finalHtml = null;
  let liveUrl = "";
  let projectName = "";
  const cached = previewCache.get(leadId);
  if (cached && cached.template === chosenTemplate && (Date.now() - cached.timestamp) < PREVIEW_CACHE_TTL) {
    finalHtml = cached.html;
    previewCache.delete(leadId);
    console.log("Using cached preview HTML for", leadId);
  } else {
    try {
      const result = await generateFinalHTML(env, request.url, chosenTemplate, leadId, description, services, strengths, logo, images, phone, address);
      finalHtml = result.html;
    } catch (e) { console.error("HTML generation error:", e); }
  }

  // 3. Deploy to Cloudflare Pages
  if (finalHtml && env.CF_API_TOKEN && env.CF_ACCOUNT_ID) {
    try {
      projectName = generateProjectName(lead.business_name || "", leadId);
      liveUrl = await deployToCloudflarePages(env, projectName, finalHtml);
      console.log("Deployed to:", liveUrl);
    } catch (e) { console.error("Deploy error:", e); }
  } else if (!finalHtml) {
    console.error("Skipping deploy: HTML generation failed");
  } else {
    console.error("Skipping deploy: CF_API_TOKEN or CF_ACCOUNT_ID not set");
  }

  // 4. Update Google Sheet with order data (emails sent by Stripe webhook after payment)
  const now = new Date().toISOString();
  const updates = {
    chosen_template: chosenTemplate,
    notes: JSON.stringify({ order_date: now, description, services, strengths, selected_domain: selectedDomain, drive_folder: driveFolderUrl, project_name: projectName }),
    status: liveUrl ? "website_created" : "website_creating",
    next_action: "AWAITING PAYMENT",
    next_action_date: now.slice(0,10),
    selected_domain: selectedDomain,
  };
  if (selectedDomain) updates.domain_option_1 = selectedDomain;
  if (liveUrl) updates.website_url = liveUrl;
  if (phone) updates.phone = phone;
  if (address) updates.address = address;
  try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
  catch (e) { console.error("Sheet update error:", e); }

  // 5. Emails are sent by the Stripe webhook after payment confirmation.
  // The frontend shows the Stripe pricing table with client-reference-id=leadId.
  // When payment completes → webhook fires → order confirmation + internal notification sent.

  return jsonResp({ success: true, message: "Bestellung vorbereitet. Zahlung wird erwartet.", drive_folder: driveFolderUrl, live_url: liveUrl || null, project_name: projectName || null });
}

async function handlePreview(leadId, templateKey, request, env, ctx) {
  if (!TEMPLATE_KEYS.includes(templateKey)) return new Response("Template not found", { status: 404 });
  const templateDir = `templates/${templateKey}`;
  // Use raw templates (with {{PLACEHOLDER}} patterns) for runtime filling
  const rawDir = `templates-raw/${templateKey}`;
  const assetUrl = new URL(`/${rawDir}/index.html`, request.url);
  const templateResp = await env.ASSETS.fetch(new Request(assetUrl));
  if (!templateResp.ok) return new Response("Template HTML not found", { status: 404 });
  let html = await templateResp.text();

  let lead = null;
  try {
    const accessToken = await getAccessToken(env);
    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    lead = findLead(sheetData, leadId);
  } catch (e) { console.error("Preview error:", e); }

  const url = new URL(request.url);
  const cust = {
    description: url.searchParams.get("description") || (lead ? (lead.form_description || "") : ""),
    services: url.searchParams.get("services") || (lead ? (lead.form_services || "") : ""),
    strengths: url.searchParams.get("strengths") || (lead ? (lead.form_strengths || "") : ""),
    values: url.searchParams.get("values") || (lead ? (lead.form_values || "") : ""),
    phone: url.searchParams.get("phone") || (lead ? (lead.form_phone || lead.phone || "") : ""),
    address: url.searchParams.get("address") || (lead ? (lead.form_address || lead.address || "") : ""),
  };
  // Build placeholder data — works with or without a lead record
  const fakeLead = { business_name: url.searchParams.get("business_name") || "" };
  const placeholderData = leadToPlaceholderData(lead || fakeLead, cust);

  // Merge with template defaults (quick mode skips AI + Pexels for fast previews)
  const quickMode = url.searchParams.get("quick") === "true";
  const merged = await mergeWithDefaults(env, templateKey, placeholderData, quickMode);

  for (const [key, value] of Object.entries(merged)) html = html.replaceAll(`{{${key}}}`, value);
  html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");

  // Fix CSS path
  html = html.replaceAll('href="styles.css"', `href="/${templateDir}/styles.css"`);
  html = html.replaceAll('href="./styles.css"', `href="/${templateDir}/styles.css"`);

  // Fix relative image paths (for fallback SVG/JPG assets when Pexels didn't fill them)
  html = html.replace(/src="assets\//g, `src="/${templateDir}/assets/`);

  // Background deploy to CF Pages — only for full (non-quick) previews
  if (!quickMode && ctx && leadId !== "_fallback" && lead && !lead[`url_${templateKey}`] && env.CF_API_TOKEN && env.CF_ACCOUNT_ID) {
    const previewHtml = html; // capture for background
    const rowIdx = lead._row_idx;
    const businessName = lead.form_business_name || lead.business_name || "";
    ctx.waitUntil((async () => {
      try {
        let deployHtml = previewHtml;
        // Inline CSS so deployed page is self-contained
        try {
          const cssUrl = new URL(`/${templateDir}/styles.css`, request.url);
          const cssResp = await env.ASSETS.fetch(new Request(cssUrl));
          if (cssResp.ok) {
            const css = await cssResp.text();
            deployHtml = deployHtml.replace(/<link[^>]*href="[^"]*style[^"]*\.css"[^>]*>/gi, `<style>${css}</style>`);
          }
        } catch (e) { console.error("CSS inline for deploy failed:", e); }
        // Fix asset paths to absolute URLs so they work from the deployed domain
        deployHtml = deployHtml.replace(/src="\/(templates\/[^"]+)"/g, 'src="https://meinekmu.pages.dev/$1"');
        deployHtml = deployHtml.replace(/href="\/(templates\/[^"]+)"/g, 'href="https://meinekmu.pages.dev/$1"');

        const projectName = generateTemplateProjectName(businessName, leadId, templateKey);
        const deployUrl = await deployToCloudflarePages(env, projectName, deployHtml);
        const at = await getAccessToken(env);
        await updateCells(at, env.LEADS_SHEET_ID, rowIdx, { [`url_${templateKey}`]: deployUrl });
        console.log(`[preview] Background deploy ${templateKey} → ${deployUrl}`);
      } catch (e) { console.error(`[preview] Background deploy ${templateKey} failed:`, e); }
    })());
  }

  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Access-Control-Allow-Origin": "*" } });
}

// Convert ArrayBuffer to base64 (chunked, safe for large files)
function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunks = [];
  for (let i = 0; i < bytes.length; i += 8192) {
    const chunk = bytes.subarray(i, i + 8192);
    let bin = "";
    for (let j = 0; j < chunk.length; j++) bin += String.fromCharCode(chunk[j]);
    chunks.push(bin);
  }
  return btoa(chunks.join(""));
}

// ── Generate Final HTML (shared between preview + order) ──
// Uses new generation pipeline: template defaults + Pexels images + placeholder fill
async function generateFinalHTML(env, requestUrl, templateKey, leadId, description, services, strengths, logoFile, imageFiles, phone, address) {
  if (!TEMPLATE_KEYS.includes(templateKey)) throw new Error("Template not found: " + templateKey);

  // 1. Get template HTML (use raw templates with {{PLACEHOLDER}} patterns)
  const templateDir = `templates/${templateKey}`;
  const rawDir = `templates-raw/${templateKey}`;
  const assetUrl = new URL(`/${rawDir}/index.html`, requestUrl);
  const templateResp = await env.ASSETS.fetch(new Request(assetUrl));
  if (!templateResp.ok) throw new Error("Template HTML not found");
  let html = await templateResp.text();

  // 2. Get lead data
  let lead = null;
  try {
    const accessToken = await getAccessToken(env);
    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    lead = findLead(sheetData, leadId);
  } catch (e) { console.error("Lead lookup error:", e); }

  // 3. Build placeholder data from lead + anpassen customizations
  const cust = { description, services, strengths, phone: phone || "", address: address || "" };
  const placeholderData = leadToPlaceholderData(lead || { business_name: "" }, cust);

  // 4. Process uploaded images — convert to data URLs for override
  const images = (imageFiles || []).filter(f => f && f.size > 0);
  const imageDataUrls = [];
  for (const img of images) {
    const buf = await img.arrayBuffer();
    const b64 = arrayBufferToBase64(buf);
    imageDataUrls.push(`data:${img.type || "image/png"};base64,${b64}`);
  }

  // Override IMAGE_* placeholders with uploaded images
  if (imageDataUrls.length > 0) {
    const slotMap = IMAGE_SLOT_MAP[templateKey] || {};
    const imageKeys = Object.keys(slotMap);
    imageDataUrls.forEach((dataUrl, i) => {
      if (i < imageKeys.length) placeholderData[imageKeys[i]] = dataUrl;
    });
  }

  // 5. Merge with template defaults + fetch Pexels images for unfilled slots
  const merged = await mergeWithDefaults(env, templateKey, placeholderData);
  const aiCategory = merged._aiCategory || "";
  delete merged._aiCategory;

  // 6. Replace all {{PLACEHOLDER}} patterns in HTML
  for (const [key, value] of Object.entries(merged)) {
    html = html.replaceAll(`{{${key}}}`, value);
  }
  html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");

  // 7. Fix CSS + relative image paths
  html = html.replaceAll('href="styles.css"', `href="/${templateDir}/styles.css"`);
  html = html.replaceAll('href="./styles.css"', `href="/${templateDir}/styles.css"`);
  html = html.replace(/src="assets\//g, `src="/${templateDir}/assets/`);

  // 8. Inject logo
  if (logoFile && logoFile.size > 0) {
    const logoBuf = await logoFile.arrayBuffer();
    const logoB64 = arrayBufferToBase64(logoBuf);
    const logoDataUrl = `data:${logoFile.type || "image/png"};base64,${logoB64}`;
    const logoImgTag = `<img src="${logoDataUrl}" alt="Logo" style="height:40px;width:auto;object-fit:contain;">`;
    const footerLogoTag = `<img src="${logoDataUrl}" alt="Logo" style="height:32px;width:auto;object-fit:contain;">`;
    html = html.replace(/(<(?:a|div)[^>]*class="[^"]*nav-logo[^"]*"[^>]*>)([\s\S]*?)(<\/(?:a|div)>)/i, `$1${logoImgTag}$3`);
    html = html.replace(/(<(?:a|div|span)[^>]*class="[^"]*(?:contact-logo|footer-logo(?:-text)?)[^"]*"[^>]*>)([\s\S]*?)(<\/(?:a|div|span)>)/i, `$1${footerLogoTag}$3`);
  }

  // 9. Inline the CSS so the deployed HTML is fully self-contained
  const cssUrl = new URL(`/${templateDir}/styles.css`, requestUrl);
  try {
    const cssResp = await env.ASSETS.fetch(new Request(cssUrl));
    if (cssResp.ok) {
      const css = await cssResp.text();
      html = html.replace(/<link[^>]*href="[^"]*style[^"]*\.css"[^>]*>/gi, `<style>${css}</style>`);
    }
  } catch (e) { console.error("CSS inline failed:", e); }

  return { html, aiCategory };
}

async function handlePreviewWithImages(request, env) {
  try {
    const fd = await request.formData();
    const leadId = fd.get("lead_id") || "";
    const templateKey = fd.get("template") || "";
    const description = fd.get("description") || "";
    const services = fd.get("services") || "";
    const strengths = fd.get("strengths") || "";
    const phone = fd.get("phone") || "";
    const address = fd.get("address") || "";
    const result = await generateFinalHTML(
      env, request.url, templateKey, leadId, description, services, strengths,
      fd.get("logo"), fd.getAll("images"), phone, address
    );
    const html = result.html;
    const aiCategory = result.aiCategory;

    // Cache the generated HTML so the order endpoint can reuse it
    if (leadId) {
      previewCache.set(leadId, { html, template: templateKey, timestamp: Date.now() });
    }

    // Write AI-detected category back to the sheet (fire-and-forget, don't block preview)
    if (leadId && aiCategory) {
      (async () => {
        try {
          const accessToken = await getAccessToken(env);
          const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
          const lead = findLead(sheetData, leadId);
          if (lead && !lead.category) {
            await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { category: aiCategory });
            console.log("[preview] Set category for", leadId, ":", aiCategory);
          }
        } catch (e) { console.error("[preview] Sheet writeback error:", e); }
      })();
    }

    return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Access-Control-Allow-Origin": "*" } });
  } catch (e) {
    console.error("Preview with images error:", e);
    return new Response("Error: " + e.message, { status: 500, headers: { "Access-Control-Allow-Origin": "*" } });
  }
}

// ── Project Name Generator ───────────────────────────────
function generateProjectName(businessName, leadId) {
  let name = businessName || "kmu";
  const umlauts = [["ä","ae"],["ö","oe"],["ü","ue"],["ß","ss"],["Ä","Ae"],["Ö","Oe"],["Ü","Ue"]];
  for (const [o, n] of umlauts) name = name.split(o).join(n);
  name = name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  name = name.toLowerCase().trim().replace(/[^a-z0-9-]/g, "-").replace(/-{2,}/g, "-").replace(/^-|-$/g, "").slice(0, 40).replace(/-$/, "") || "kmu";
  const suffix = (leadId || "000000").slice(0, 6);
  return `kmu-${name}-${suffix}`;
}

// ── Cloudflare Pages Deploy (REST API) ───────────────────
async function deployToCloudflarePages(env, projectName, htmlContent) {
  const accountId = env.CF_ACCOUNT_ID;
  const apiToken = env.CF_API_TOKEN;
  if (!accountId || !apiToken) throw new Error("CF_ACCOUNT_ID or CF_API_TOKEN not configured");

  const headers = { Authorization: `Bearer ${apiToken}` };

  // 1. Create project (ignore error if exists)
  try {
    await fetch(`https://api.cloudflare.com/client/v4/accounts/${accountId}/pages/projects`, {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ name: projectName, production_branch: "main" }),
    });
  } catch (e) { console.log("Project create (may already exist):", e.message); }

  // 2. Direct Upload deployment
  // Step a: create upload session
  const createResp = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/pages/projects/${projectName}/deployments`,
    { method: "POST", headers, body: (() => {
      const fd = new FormData();
      fd.append("manifest", JSON.stringify({ "/index.html": "index.html" }));
      const blob = new Blob([htmlContent], { type: "text/html" });
      fd.append("index.html", blob, "index.html");
      return fd;
    })() }
  );

  const createData = await createResp.json();
  if (!createData.success) {
    console.error("Deploy response:", JSON.stringify(createData));
    throw new Error("Deployment failed: " + (createData.errors?.[0]?.message || JSON.stringify(createData.errors)));
  }

  const deployUrl = createData.result?.url || `https://${projectName}.pages.dev`;
  return deployUrl;
}

// ── Email Helpers (Resend API) ───────────────────────────
function emailHeader() {
  return `<div style="background:#1a1a1a;padding:18px 24px;">
    <a href="https://meine-kmu.ch" target="_blank" style="text-decoration:none;">
      <span style="color:#fff;font-size:22px;font-weight:800;letter-spacing:-0.5px;
        font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Helvetica,Arial,sans-serif;">
        meine-kmu<span style="color:#a6ff00;">.</span>
      </span>
    </a>
  </div>`;
}

function emailFooter() {
  return `<div style="background:#f5f5f5;padding:16px 24px;font-size:12px;color:#888;border-top:1px solid #e0e0e0;">
    <p style="margin:0;">meine-kmu.ch &nbsp;·&nbsp;
      <a href="mailto:info@meine-kmu.ch" style="color:#888;">info@meine-kmu.ch</a> &nbsp;·&nbsp;
      <a href="https://meine-kmu.ch" style="color:#888;">meine-kmu.ch</a>
    </p>
  </div>`;
}

// ── Domain availability check via RDAP / DNS ─────────────
async function checkDomainAvailability(domain) {
  const tld = domain.rsplit ? domain.split(".").pop() : domain.split(".").pop();
  if (tld === "ch") {
    // .ch domains: use RDAP (nic.ch)
    try {
      const resp = await fetch(`https://rdap.nic.ch/domain/${domain}`, { redirect: "follow" });
      if (resp.status === 404) return { domain, available: true, tld: "." + tld };
      if (resp.status === 200) return { domain, available: false, tld: "." + tld };
    } catch (e) { /* fall through to DNS */ }
  } else if (tld === "com") {
    // .com domains: use RDAP (verisign)
    try {
      const resp = await fetch(`https://rdap.verisign.com/com/v1/domain/${domain}`, { redirect: "follow" });
      if (resp.status === 404) return { domain, available: true, tld: "." + tld };
      if (resp.status === 200) return { domain, available: false, tld: "." + tld };
    } catch (e) { /* fall through to DNS */ }
  }
  // Fallback: DNS resolution check via Cloudflare DoH
  try {
    const resp = await fetch(`https://cloudflare-dns.com/dns-query?name=${domain}&type=A`, {
      headers: { "Accept": "application/dns-json" },
    });
    const data = await resp.json();
    const hasRecords = data.Answer && data.Answer.length > 0;
    return { domain, available: !hasRecords, tld: "." + tld };
  } catch (e) {
    return { domain, available: null, tld: "." + tld }; // unknown
  }
}

async function handleCheckDomains(request) {
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Invalid request" }, 400); }
  const domains = body.domains;
  if (!Array.isArray(domains) || domains.length === 0) return jsonResp({ error: "No domains provided" }, 400);

  // Check all domains in parallel (max 10)
  const toCheck = domains.slice(0, 10);
  const results = await Promise.all(toCheck.map(d => checkDomainAvailability(d)));
  return jsonResp({ results });
}

function domainPurchaseLink(domain, existingLink) {
  if (existingLink && existingLink.startsWith("http")) return existingLink;
  const encoded = (domain || "").replace(/\./g, "%2E");
  return `https://www.namecheap.com/domains/registration/results/?domain=${encoded}`;
}

function cloudflareDomainLink(projectName) {
  return `https://dash.cloudflare.com/?to=/:account/pages/view/${projectName}/domains/new`;
}

async function sendEmail(env, to, subject, html) {
  if (!env.RESEND_API_KEY) { console.error("RESEND_API_KEY not set, skipping email to", to); return; }
  try {
    const resp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: "meine-kmu.ch <info@meine-kmu.ch>",
        to: [to], subject, html,
      }),
    });
    const data = await resp.json();
    if (data.error) console.error("Resend error:", data.error);
    else console.log("Email sent to", to, "id:", data.id);
  } catch (e) { console.error("Email send failed:", e); }
}

// ── Shared: Build 2x2 Website Screenshot Grid ───────────
function buildWebsiteGrid(lead) {
  const templateLabels = { earlydog: "Klassisch", bia: "Modern", liveblocks: "Frisch", loveseen: "Elegant" };
  const orderedKeys = ["earlydog", "bia", "liveblocks", "loveseen"];
  let gridCells = "";
  let linkCount = 0;
  for (const key of orderedKeys) {
    const url = lead[`url_${key}`] || "";
    if (url) {
      linkCount++;
      const thumbUrl = `https://image.thum.io/get/width/560/crop/400/${url}`;
      gridCells += `<td width="50%" style="padding:5px;">
        <a href="${url}" target="_blank" style="display:block;text-decoration:none;color:#444;">
          <img src="${thumbUrl}" width="100%" style="border:1px solid #ddd;border-radius:5px;display:block;" alt="${templateLabels[key] || key}">
          <div style="text-align:center;font-size:12px;margin-top:6px;font-weight:600;">${templateLabels[key] || key} →</div>
        </a>
      </td>`;
    }
  }
  if (linkCount === 0) return { gridHtml: "", linkCount: 0 };
  const cells = gridCells.split("</td>").filter(c => c.trim()).map(c => c + "</td>");
  let gridHtml = '<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">';
  for (let i = 0; i < cells.length; i += 2) {
    gridHtml += `<tr>${cells[i]}${cells[i + 1] || '<td width="50%"></td>'}</tr>`;
  }
  gridHtml += '</table>';
  return { gridHtml, linkCount };
}

// ── Shared: Standard email shell (light theme, matches cold outreach) ──
function emailShell(subject, bodyHtml) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:580px;margin:0 auto;padding:0;color:#333;line-height:1.6;">
${emailHeader()}
  <div style="padding:28px 24px;">
    ${bodyHtml}
    <p style="margin-bottom:0;margin-top:24px;">Freundliche Grüsse<br>
    <strong>Louise & Mael</strong><br>
    <span style="color:#555;">info@meine-kmu.ch</span><br>
    <a href="https://meine-kmu.ch" style="color:#555;">meine-kmu.ch</a></p>
  </div>
${emailFooter()}
</body></html>`;
}

function codeBox(leadId) {
  return `<div style="background:#f5f5f5;border:1px solid #e0e0e0;border-radius:8px;padding:22px;margin:20px 0;text-align:center;">
      <div style="font-size:11px;color:#999;margin-bottom:8px;text-transform:uppercase;letter-spacing:1.5px;">Dein persönlicher Code</div>
      <div style="font-size:30px;font-weight:bold;letter-spacing:6px;color:#1a1a1a;margin-bottom:16px;">${leadId}</div>
      <a href="https://meinekmu.pages.dev/onboarding.html" style="background:#1a1a1a;color:#fff;padding:11px 26px;border-radius:4px;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;">Zugriff erhalten →</a>
    </div>`;
}

function ctaButton(text, url) {
  const href = url || "https://meinekmu.pages.dev/onboarding.html";
  return `<div style="text-align:center;margin:20px 0;">
      <a href="${href}" style="display:inline-block;background:#1a1a1a;color:#fff;padding:11px 26px;border-radius:4px;text-decoration:none;font-size:14px;font-weight:600;">${text}</a>
    </div>`;
}

// ── Reminder Emails (3 variants, with website grid) ──────
async function sendReminderEmail(env, lead, variant) {
  const email = lead.owner_email || lead.emails;
  if (!email) return;
  const businessName = lead.form_business_name || lead.business_name || "dein Business";
  const leadId = lead.lead_id;
  const { gridHtml, linkCount } = buildWebsiteGrid(lead);

  const variants = {
    1: {
      subject: `${businessName}, deine Website wartet auf dich`,
      text: `<p style="margin-top:0;">Wir haben gesehen, dass du dir Websites für <strong>${businessName}</strong> angeschaut hast. Sieht super aus!</p>
      <p>Falls du noch nicht bestellt hast, kein Stress. Deine Entwürfe sind gespeichert und warten auf dich.</p>`,
    },
    2: {
      subject: `Können wir dir helfen, ${businessName}?`,
      text: `<p style="margin-top:0;">Deine Website Entwürfe für <strong>${businessName}</strong> sind immer noch bei uns gespeichert. Falls irgendwas unklar ist oder du nicht weiterkommst, schreib uns einfach. Wir helfen dir gerne weiter!</p>
      <p>Du kannst uns auch direkt erreichen: <a href="mailto:info@meine-kmu.ch" style="color:#1a1a1a;">info@meine-kmu.ch</a></p>`,
    },
    3: {
      subject: `Immer noch Interesse an einer Website, ${businessName}?`,
      text: `<p style="margin-top:0;">Kurzer Check in: Dein Website Entwurf für <strong>${businessName}</strong> ist weiterhin bei uns gespeichert. Das Angebot steht, wenn du bereit bist, sind wir es auch. Schau einfach nochmal rein wenn du magst!</p>`,
    },
  };
  const v = variants[variant] || variants[1];

  let gridSection = "";
  if (gridHtml && linkCount > 0) {
    gridSection = `<p>Klick auf ein Design, um es anzuschauen:</p>${gridHtml}`;
  }

  const html = emailShell(v.subject, `
    ${v.text}
    ${codeBox(leadId)}
    ${gridSection}
  `);
  await sendEmail(env, email, v.subject, html);
}

// ── Cold Follow-up Emails (Day 7 / Day 14) ──────────────
async function sendColdFollowUp(env, lead, day) {
  const email = lead.owner_email || lead.emails;
  if (!email) return;
  const businessName = lead.form_business_name || lead.business_name || "Ihr Unternehmen";
  const leadId = lead.lead_id;
  const { gridHtml, linkCount } = buildWebsiteGrid(lead);

  let subject, bodyText;
  if (day === 7) {
    subject = `Kurze Nachfrage wegen ${businessName}`;
    bodyText = `<p style="margin-top:0;">Guten Tag,</p>
    <p>ich wollte kurz nachfragen ob meine E-Mail von letzter Woche angekommen ist. Ich hatte Website Entwürfe für <strong>${businessName}</strong> erstellt und würde mich freuen wenn Sie mal einen Blick drauf werfen.</p>`;
  } else {
    subject = `Letzte Nachricht wegen ${businessName}`;
    bodyText = `<p style="margin-top:0;">Guten Tag,</p>
    <p>dies ist meine letzte Nachricht, ich möchte Ihre Zeit nicht länger beanspruchen. Falls Sie die Website für <strong>${businessName}</strong> zu einem späteren Zeitpunkt möchten, können Sie sich jederzeit melden. Ihr Zugangscode bleibt noch 14 Tage aktiv.</p>`;
  }

  let gridSection = "";
  if (gridHtml && linkCount > 0) {
    gridSection = `<p>Klicken Sie auf ein Design, um es anzuschauen:</p>${gridHtml}`;
  }

  const html = emailShell(subject, `
    ${bodyText}
    ${codeBox(leadId)}
    ${gridSection}
  `);
  await sendEmail(env, email, subject, html);
}

// ── Order Confirmation (after Stripe payment) ────────────
async function sendOrderConfirmation(env, lead, selectedDomain) {
  const email = lead.owner_email || lead.emails;
  if (!email) return;
  const name = lead.owner_name || "";
  const businessName = lead.form_business_name || lead.business_name || "dein Business";
  const greeting = name ? `Hallo ${name}!` : "Hey!";
  const domainDisplay = selectedDomain || "deiner gewünschten Adresse";

  // Website preview: show chosen template or first available
  const chosenKey = lead.chosen_template || "";
  const previewUrl = lead[`url_${chosenKey}`] || lead.url_earlydog || lead.url_bia || lead.url_liveblocks || lead.url_loveseen || "";
  let previewSection = "";
  if (previewUrl) {
    const thumbUrl = `https://image.thum.io/get/width/560/crop/400/${previewUrl}`;
    previewSection = `<div style="margin:20px 0;">
      <a href="${previewUrl}" target="_blank" style="display:block;text-decoration:none;">
        <img src="${thumbUrl}" width="100%" style="border:1px solid #ddd;border-radius:5px;display:block;" alt="Deine Website">
      </a>
    </div>`;
  }

  const subject = `Danke für deine Bestellung, ${businessName}!`;
  const html = emailShell(subject, `
    <p style="margin-top:0;">${greeting}</p>

    <p>Deine Zahlung ist eingegangen, vielen Dank! Wir freuen uns mega und legen direkt los mit deiner Website für <strong>${businessName}</strong>.</p>

    ${previewSection}

    <div style="background:#f5f5f5;border:1px solid #e0e0e0;border-radius:8px;padding:22px;margin:20px 0;text-align:center;">
      <div style="font-size:11px;color:#999;margin-bottom:8px;text-transform:uppercase;letter-spacing:1.5px;">Deine zukünftige Webadresse</div>
      <div style="font-size:20px;font-weight:700;color:#1a1a1a;">${domainDisplay}</div>
    </div>

    <p>Innerhalb von 48 Stunden ist deine Website unter <strong>${domainDisplay}</strong> live erreichbar. Wir melden uns sobald alles bereit ist!</p>

    <p>Falls du Fragen hast, schreib uns einfach: <a href="mailto:info@meine-kmu.ch" style="color:#1a1a1a;">info@meine-kmu.ch</a></p>
  `);
  await sendEmail(env, email, subject, html);
}

// ── Website Is Live Email ────────────────────────────────
async function sendWebsiteLiveEmail(env, lead) {
  const email = lead.owner_email || lead.emails;
  if (!email) return;
  const name = lead.owner_name || "";
  const businessName = lead.form_business_name || lead.business_name || "dein Business";
  const domain = lead.selected_domain || lead.domain_option_1 || "";
  const greeting = name ? `Hallo ${name}!` : "Hey!";
  const subject = `${businessName} ist jetzt online!`;
  const html = emailShell(subject, `
    <p style="margin-top:0;">${greeting}</p>

    <p>Deine Website für <strong>${businessName}</strong> ist ab sofort live erreichbar. Schau sie dir an!</p>

    ${ctaButton(`${domain} besuchen →`, `https://${domain}`)}

    <p><strong>Was du jetzt machen kannst:</strong></p>
    <p style="margin:4px 0;">• Teile den Link auf Social Media und Google Business</p>
    <p style="margin:4px 0;">• Schick den Link an deine bestehenden Kunden</p>
    <p style="margin:4px 0;">• Falls du was ändern willst, meld dich einfach bei uns</p>

    <p>Herzlichen Glückwunsch zur neuen Website! Wir freuen uns für dich.</p>
  `);
  await sendEmail(env, email, subject, html);
}

// ── Cancellation Email ───────────────────────────────────
async function sendCancellationEmail(env, lead) {
  const email = lead.owner_email || lead.emails;
  if (!email) return;
  const name = lead.owner_name || "";
  const businessName = lead.form_business_name || lead.business_name || "dein Business";
  const greeting = name ? `Hallo ${name},` : "Hey,";
  const subject = `Schade, ${businessName}!`;
  const html = emailShell(subject, `
    <p style="margin-top:0;">${greeting}</p>

    <p>schade dass du gehst! Deine Website für <strong>${businessName}</strong> bleibt bis zum Ende der bezahlten Periode erreichbar.</p>

    <p>Falls du es dir anders überlegst, meld dich einfach bei uns. Dein Entwurf bleibt gespeichert und wir können jederzeit weitermachen.</p>

    <p>Wir wünschen dir alles Gute!</p>

    <p>Fragen? Schreib uns: <a href="mailto:info@meine-kmu.ch" style="color:#1a1a1a;">info@meine-kmu.ch</a></p>
  `);
  await sendEmail(env, email, subject, html);
}

// ── Check if domain resolves (for "website is live" auto-detection) ──
async function checkDomainLive(domain) {
  try {
    const resp = await fetch(`https://cloudflare-dns.com/dns-query?name=${domain}&type=A`, {
      headers: { Accept: "application/dns-json" },
    });
    const data = await resp.json();
    return data.Answer && data.Answer.length > 0;
  } catch { return false; }
}

// ── Reminder eligibility + variant logic ─────────────────
function shouldSendReminder(lead, now) {
  const email = lead.owner_email || lead.emails;
  if (!email) return false;
  if (!lead.last_dashboard_visit) return false;
  // Stop if they ordered or cancelled
  const stopStatuses = ["website_created", "website_creating", "sold"];
  if (stopStatuses.includes(lead.status)) return false;
  if (lead.subscription_status === "cancelled") return false;
  if (lead.stripe_payment_date) return false;

  const count = parseInt(lead.reminder_count) || 0;
  if (count >= 8) return false; // cap at ~6 months

  const msSinceVisit = now - new Date(lead.last_dashboard_visit).getTime();
  const msSinceReminder = lead.last_reminder_sent ? now - new Date(lead.last_reminder_sent).getTime() : Infinity;
  const DAY = 86400000;

  if (count === 0) return msSinceVisit >= 3 * DAY;
  if (count === 1) return msSinceReminder >= 7 * DAY;
  return msSinceReminder >= 30 * DAY; // monthly
}

function getReminderVariant(lead) {
  const count = parseInt(lead.reminder_count) || 0;
  return (count % 3) + 1; // cycles through 1, 2, 3
}

// ── Daily Cron: Process Scheduled Emails ─────────────────
async function processScheduledEmails(env) {
  let accessToken;
  try { accessToken = await getAccessToken(env); }
  catch (e) { console.error("Cron: auth failed:", e); return; }

  let sheetData;
  try { sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID); }
  catch (e) { console.error("Cron: sheet fetch failed:", e); return; }

  const rows = sheetData.values || [];
  const now = Date.now();
  let emailsSent = 0;
  const MAX_EMAILS = 30;

  for (let i = 1; i < rows.length && emailsSent < MAX_EMAILS; i++) {
    const lead = { _row_idx: i + 1 };
    COLUMN_NAMES.forEach((name, j) => { lead[name] = rows[i][j] || ""; });

    // ── Cold follow-ups (Day 7 / Day 14) ──
    if (lead.status === "email_sent" && lead.email_sent_date) {
      const daysSinceCold = (now - new Date(lead.email_sent_date).getTime()) / 86400000;
      let notes = {};
      try { notes = JSON.parse(lead.notes || "{}"); } catch {}

      if (daysSinceCold >= 14 && !notes.day14_sent) {
        try {
          await sendColdFollowUp(env, lead, 14);
          notes.day14_sent = new Date().toISOString();
          await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { notes: JSON.stringify(notes) });
          emailsSent++;
          console.log("Cron: sent Day 14 to", lead.lead_id);
        } catch (e) { console.error("Cron: Day 14 error for", lead.lead_id, e); }
      } else if (daysSinceCold >= 7 && !notes.day7_sent) {
        try {
          await sendColdFollowUp(env, lead, 7);
          notes.day7_sent = new Date().toISOString();
          await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { notes: JSON.stringify(notes) });
          emailsSent++;
          console.log("Cron: sent Day 7 to", lead.lead_id);
        } catch (e) { console.error("Cron: Day 7 error for", lead.lead_id, e); }
      }
    }

    // ── Website Is Live (DNS check) ──
    if (lead.stripe_payment_date && !lead.live_email_sent && lead.selected_domain) {
      try {
        const isLive = await checkDomainLive(lead.selected_domain);
        if (isLive) {
          await sendWebsiteLiveEmail(env, lead);
          await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, {
            live_email_sent: new Date().toISOString(),
            status: "sold",
          });
          emailsSent++;
          console.log("Cron: sent live email to", lead.lead_id, "domain:", lead.selected_domain);
        }
      } catch (e) { console.error("Cron: live check error for", lead.lead_id, e); }
    }

    // ── Reminders ──
    if (shouldSendReminder(lead, now)) {
      const variant = getReminderVariant(lead);
      try {
        await sendReminderEmail(env, lead, variant);
        const count = (parseInt(lead.reminder_count) || 0) + 1;
        await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, {
          last_reminder_sent: new Date().toISOString(),
          reminder_count: String(count),
        });
        emailsSent++;
        console.log("Cron: sent reminder variant", variant, "to", lead.lead_id, "(count:", count, ")");
      } catch (e) { console.error("Cron: reminder error for", lead.lead_id, e); }
    }
  }

  console.log(`Cron: finished. ${emailsSent} emails sent.`);
}

// ── Stripe Webhook Handler ───────────────────────────────
// ── Confirm Live: mark lead as sold + send "website is live" email ───
async function handleConfirmLive(leadId, env) {
  try {
    const accessToken = await getAccessToken(env);
    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    const lead = findLead(sheetData, leadId);
    if (!lead) return new Response("<h1>Lead nicht gefunden</h1>", { status: 404, headers: { "Content-Type": "text/html;charset=utf-8" } });

    if (lead.live_email_sent) {
      return new Response(`<html><body style="font-family:sans-serif;max-width:500px;margin:60px auto;text-align:center;">
        <h2>Bereits erledigt</h2><p>"Website ist live" Mail wurde bereits gesendet am ${lead.live_email_sent}.</p>
      </body></html>`, { headers: { "Content-Type": "text/html;charset=utf-8" } });
    }

    // Update sheet: status=sold, live_email_sent=now
    await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, {
      status: "sold",
      live_email_sent: new Date().toISOString(),
    });

    // Send "website is live" email to customer
    await sendWebsiteLiveEmail(env, lead);

    const businessName = lead.form_business_name || lead.business_name || leadId;
    return new Response(`<html><body style="font-family:sans-serif;max-width:500px;margin:60px auto;text-align:center;">
      <h2 style="color:#1a1a1a;">Erledigt!</h2>
      <p><strong>${businessName}</strong> wurde als "sold" markiert.</p>
      <p>"Website ist live" Mail wurde an <strong>${lead.owner_email || lead.emails || "?"}</strong> gesendet.</p>
    </body></html>`, { headers: { "Content-Type": "text/html;charset=utf-8" } });
  } catch (e) {
    return new Response(`<h1>Fehler</h1><p>${e.message}</p>`, { status: 500, headers: { "Content-Type": "text/html;charset=utf-8" } });
  }
}

async function handleStripeWebhook(request, env) {
  const body = await request.text();
  const sig = request.headers.get("stripe-signature");

  // Verify webhook signature
  if (env.STRIPE_WEBHOOK_SECRET && sig) {
    const verified = await verifyStripeSignature(body, sig, env.STRIPE_WEBHOOK_SECRET);
    if (!verified) return jsonResp({ error: "Invalid signature" }, 400);
  }

  const event = JSON.parse(body);
  console.log("Stripe webhook:", event.type);

  let accessToken;
  try { accessToken = await getAccessToken(env); }
  catch (e) { return jsonResp({ error: "Auth failed" }, 500); }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    const leadId = session.client_reference_id || session.metadata?.lead_id;
    if (!leadId) { console.error("Stripe: no lead_id in session"); return jsonResp({ received: true }); }

    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    const lead = findLead(sheetData, leadId);
    if (!lead) { console.error("Stripe: lead not found:", leadId); return jsonResp({ received: true }); }

    const now = new Date().toISOString();
    let notes = {};
    try { notes = JSON.parse(lead.notes || "{}"); } catch {}
    const selectedDomain = notes.selected_domain || lead.selected_domain || lead.domain_option_1 || "";

    // Send order confirmation + internal notification
    try { await sendOrderConfirmation(env, lead, selectedDomain); } catch (e) { console.error("Stripe: order email error:", e); }

    const purchaseLink = domainPurchaseLink(selectedDomain, lead.domain_option_1_purchase || "");
    const projectName = notes.project_name || "";
    const cfDomainLink = projectName ? cloudflareDomainLink(projectName) : "";
    const liveUrl = lead.website_url || "(noch kein Deploy)";
    try { await sendInternalNotification(env, leadId, lead.business_name || leadId, lead.owner_email || "", liveUrl, selectedDomain, purchaseLink, cfDomainLink); }
    catch (e) { console.error("Stripe: internal email error:", e); }

    // Update sheet
    await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, {
      stripe_payment_date: now,
      subscription_status: "active",
      selected_domain: selectedDomain,
      status: lead.website_url ? "sold" : "website_creating",
    });

    console.log("Stripe: processed checkout for", leadId);
  }

  if (event.type === "customer.subscription.deleted") {
    const subscription = event.data.object;
    const leadId = subscription.metadata?.lead_id;
    if (!leadId) { console.error("Stripe: no lead_id in subscription metadata"); return jsonResp({ received: true }); }

    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    const lead = findLead(sheetData, leadId);
    if (!lead) { console.error("Stripe: lead not found for cancellation:", leadId); return jsonResp({ received: true }); }

    try { await sendCancellationEmail(env, lead); } catch (e) { console.error("Stripe: cancellation email error:", e); }

    await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, {
      subscription_status: "cancelled",
    });

    console.log("Stripe: processed cancellation for", leadId);
  }

  return jsonResp({ received: true });
}

// ── Stripe Signature Verification ────────────────────────
async function verifyStripeSignature(payload, sigHeader, secret) {
  try {
    const parts = {};
    for (const item of sigHeader.split(",")) {
      const [key, value] = item.split("=");
      parts[key.trim()] = value;
    }
    const timestamp = parts.t;
    const signature = parts.v1;
    if (!timestamp || !signature) return false;

    // Check timestamp is within 5 minutes
    const age = Math.abs(Date.now() / 1000 - parseInt(timestamp));
    if (age > 300) return false;

    const signedPayload = `${timestamp}.${payload}`;
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
    );
    const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signedPayload));
    const expectedSig = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
    return expectedSig === signature;
  } catch { return false; }
}

async function sendInternalNotification(env, leadId, businessName, leadEmail, liveUrl, selectedDomain, purchaseLink, cfDomainLink) {
  const confirmUrl = `https://meinekmu.pages.dev/api/lead/${leadId}/confirm-live?secret=${env.CRON_SECRET || ""}`;
  const subject = `Neue Bestellung — ${businessName} (${leadId})`;
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:580px;margin:0 auto;padding:0;color:#333;line-height:1.6;">
${emailHeader()}
  <div style="padding:28px 24px;">
    <h2 style="margin-top:0;font-size:20px;">Neue Bestellung eingegangen</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
      <tr><td style="padding:8px 0;border-bottom:1px solid #eee;color:#888;width:40%;font-size:14px;">Lead ID</td>
          <td style="padding:8px 0;border-bottom:1px solid #eee;font-weight:600;font-size:14px;">${leadId}</td></tr>
      <tr><td style="padding:8px 0;border-bottom:1px solid #eee;color:#888;font-size:14px;">Betrieb</td>
          <td style="padding:8px 0;border-bottom:1px solid #eee;font-weight:600;font-size:14px;">${businessName}</td></tr>
      <tr><td style="padding:8px 0;border-bottom:1px solid #eee;color:#888;font-size:14px;">E-Mail Kunde</td>
          <td style="padding:8px 0;border-bottom:1px solid #eee;font-size:14px;">
            <a href="mailto:${leadEmail}" style="color:#1a1a1a;">${leadEmail || "—"}</a></td></tr>
      <tr><td style="padding:8px 0;border-bottom:1px solid #eee;color:#888;font-size:14px;">Gewünschte Domain</td>
          <td style="padding:8px 0;border-bottom:1px solid #eee;font-size:14px;">${selectedDomain || "—"}</td></tr>
    </table>

    <h3 style="font-size:16px;margin-bottom:12px;">Aktionen</h3>

    <div style="margin-bottom:12px;">
      <a href="${liveUrl}" style="display:block;background:#f5f5f5;border:1px solid #e0e0e0;border-radius:6px;padding:14px 16px;text-decoration:none;color:#333;">
        <div style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Website anschauen</div>
        <div style="font-weight:600;">${liveUrl} →</div>
      </a>
    </div>

    <div style="margin-bottom:12px;">
      <a href="${purchaseLink}" style="display:block;background:#f5f5f5;border:1px solid #e0e0e0;border-radius:6px;padding:14px 16px;text-decoration:none;color:#333;">
        <div style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Domain kaufen (Namecheap)</div>
        <div style="font-weight:600;">${selectedDomain || "Domain suchen"} →</div>
      </a>
    </div>

    <div style="margin-bottom:12px;">
      <a href="${cfDomainLink}" style="display:block;background:#f5f5f5;border:1px solid #e0e0e0;border-radius:6px;padding:14px 16px;text-decoration:none;color:#333;">
        <div style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Domain verbinden (Cloudflare)</div>
        <div style="font-weight:600;">Cloudflare Pages → Custom Domain →</div>
      </a>
    </div>

    <div style="background:#f5f5f5;border-radius:6px;padding:16px;margin-top:20px;font-size:13px;color:#555;">
      <strong>Nächste Schritte:</strong><br>
      1. Domain kaufen (oben)<br>
      2. Domain im Cloudflare Dashboard mit dem Pages-Projekt verbinden<br>
      3. Warten bis DNS propagiert (5–30 min)<br>
      4. Auf den Button unten klicken → Sheet wird aktualisiert + Kunde bekommt "Website ist live" Mail
    </div>

    <div style="text-align:center;margin:28px 0;">
      <a href="${confirmUrl}" style="display:inline-block;background:#1a1a1a;color:#fff;padding:14px 32px;border-radius:4px;text-decoration:none;font-size:15px;font-weight:600;">Domain ist verbunden, Kunde informieren →</a>
    </div>
  </div>
${emailFooter()}
</body></html>`;
  await sendEmail(env, "info@meine-kmu.ch", subject, html);
}

// ── Save Form Data ───────────────────────────────────────
async function handleSaveForm(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  const updates = {};
  if (body.business_name) { updates.form_business_name = body.business_name; updates.business_name = body.business_name; }
  if (body.description) updates.form_description = body.description;
  if (body.services) updates.form_services = body.services;
  if (body.strengths) updates.form_strengths = body.strengths;
  if (body.values) updates.form_values = body.values;
  if (body.phone !== undefined) { updates.form_phone = body.phone; if (body.phone) updates.phone = body.phone; }
  if (body.address !== undefined) { updates.form_address = body.address; if (body.address) updates.address = body.address; }

  // Also store in notes JSON for backward compatibility
  const existingNotes = lead.notes ? (() => { try { return JSON.parse(lead.notes); } catch { return {}; } })() : {};
  if (body.description) existingNotes.description = body.description;
  if (body.services) existingNotes.services = body.services;
  if (body.strengths) existingNotes.strengths = body.strengths;
  if (body.values) existingNotes.values = body.values;
  updates.notes = JSON.stringify(existingNotes);

  try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
  catch (e) { console.error("Save form error:", e); return jsonResp({ error: "Speichern fehlgeschlagen." }, 500); }

  return jsonResp({ success: true });
}

// ── Generate All 4 Templates (background) ────────────────
function generateTemplateProjectName(businessName, leadId, templateKey) {
  let name = businessName || "kmu";
  const umlauts = [["ä","ae"],["ö","oe"],["ü","ue"],["ß","ss"],["Ä","Ae"],["Ö","Oe"],["Ü","Ue"]];
  for (const [o, n] of umlauts) name = name.split(o).join(n);
  name = name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  name = name.toLowerCase().trim().replace(/[^a-z0-9-]/g, "-").replace(/-{2,}/g, "-").replace(/^-|-$/g, "").slice(0, 30).replace(/-$/, "") || "kmu";
  const suffix = (leadId || "000000").slice(0, 6);
  return `kmu-${name}-${suffix}-${templateKey}`;
}

async function handleGenerateAll(leadId, request, env, ctx) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);

  // Accept form data from request body (avoids race condition with save-form)
  let bodyData = {};
  try { bodyData = await request.json(); } catch { /* empty body is fine */ }

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  // Set initial generation status
  const initStatus = {};
  TEMPLATE_KEYS.forEach(k => { initStatus[k] = "pending"; });
  try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { generation_status: JSON.stringify(initStatus) }); }
  catch (e) { console.error("Status init error:", e); }

  // Background generation via waitUntil — optimized to share AI + Pexels across templates
  const requestUrl = request.url;
  const rowIdx = lead._row_idx;
  ctx.waitUntil((async () => {
    // Use form data from body (freshest) with sheet data as fallback
    const description = bodyData.description || lead.form_description || "";
    const services = bodyData.services || lead.form_services || "";
    const strengths = bodyData.strengths || lead.form_strengths || "";
    const phone = bodyData.phone || lead.form_phone || lead.phone || "";
    const address = bodyData.address || lead.form_address || lead.address || "";
    const businessName = bodyData.business_name || lead.form_business_name || lead.business_name || "";
    const isNoCode = lead.acquisition_source === "organic" || lead.acquisition_source === "self-signup";
    const email = lead.owner_email || lead.emails || "";

    // ── SHARED STEP 1: Build lead placeholder data ONCE ──
    const cust = { description, services, strengths, phone, address };
    const placeholderData = leadToPlaceholderData(lead, cust);

    // ── SHARED STEP 2: Call AI enrichment ONCE (same for all templates) ──
    let aiText = {};
    let aiCategory = "";
    try {
      aiText = await enrichWithAI(env, { ...TEMPLATE_DEFAULTS.bia, ...placeholderData, _description: placeholderData._description || "", _services: placeholderData._services || "", _strengths: placeholderData._strengths || "" }, "bia");
      if (aiText.CATEGORY) { aiCategory = aiText.CATEGORY; delete aiText.CATEGORY; }
    } catch (e) { console.error("Shared AI enrichment error:", e); }

    // ── SHARED STEP 3: Fetch Pexels images ONCE per slot type ──
    const allImageSlots = {};
    for (const tplKey of TEMPLATE_KEYS) {
      const slotMap = IMAGE_SLOT_MAP[tplKey] || {};
      for (const [key, desc] of Object.entries(slotMap)) {
        if (!allImageSlots[key]) allImageSlots[key] = desc;
      }
    }
    let sharedImages = {};
    const hasBusinessContext = !!(description || values || lead.category || businessName);
    if (hasBusinessContext) {
      const mergedForImages = { ...placeholderData, category: aiCategory || lead.category || "" };
      sharedImages = await suggestBusinessImages(env, mergedForImages, allImageSlots);
    }

    // ── Track status in memory (avoid re-reading sheet for each template) ──
    const genStatus = { ...initStatus };
    const genUrls = {};

    // Helper: update sheet with current status + url for a single template
    // Uses the already-obtained accessToken from outer scope (avoids 4 parallel OAuth calls)
    async function updateTemplateResult(tplKey, url, status) {
      genStatus[tplKey] = status;
      if (url) genUrls[tplKey] = url;
      try {
        const updates = { generation_status: JSON.stringify(genStatus) };
        if (url) updates[`url_${tplKey}`] = url;
        await updateCells(accessToken, env.LEADS_SHEET_ID, rowIdx, updates);
      } catch (e) { console.error(`Status update error for ${tplKey}:`, e); }
    }

    // ── PARALLEL STEP 4: Generate + deploy all 4 templates ──
    await Promise.allSettled(TEMPLATE_KEYS.map(async (tplKey) => {
      try {
        // Build template-specific merged data using shared AI + images
        const defaults = TEMPLATE_DEFAULTS[tplKey] || {};
        const merged = { ...defaults };
        for (const [key, value] of Object.entries(placeholderData)) {
          if (key.startsWith("_")) continue;
          if (value !== null && value !== undefined && value !== "") merged[key] = String(value);
        }
        // Apply shared AI text
        for (const [key, value] of Object.entries(aiText)) {
          if (value && !key.startsWith("IMAGE_")) merged[key] = String(value);
        }
        // Apply shared Pexels images for this template's slots
        const tplSlotMap = IMAGE_SLOT_MAP[tplKey] || {};
        for (const key of Object.keys(tplSlotMap)) {
          if (sharedImages[key]) merged[key] = sharedImages[key];
        }
        // Auto-generate META_DESCRIPTION
        if (!merged.META_DESCRIPTION) {
          const n = merged.BUSINESS_NAME || "";
          const t = merged.TAGLINE || "";
          merged.META_DESCRIPTION = t ? `${n} — ${t}` : n;
        }

        // Fetch template HTML and apply placeholders
        const templateDir = `templates/${tplKey}`;
        const rawDir = `templates-raw/${tplKey}`;
        const assetUrl = new URL(`/${rawDir}/index.html`, requestUrl);
        const templateResp = await env.ASSETS.fetch(new Request(assetUrl));
        if (!templateResp.ok) throw new Error("Template HTML not found for " + tplKey);
        let html = await templateResp.text();

        for (const [key, value] of Object.entries(merged)) {
          if (key.startsWith("_")) continue;
          html = html.replaceAll(`{{${key}}}`, value);
        }
        html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");

        // Fix paths
        html = html.replaceAll('href="styles.css"', `href="/${templateDir}/styles.css"`);
        html = html.replaceAll('href="./styles.css"', `href="/${templateDir}/styles.css"`);
        html = html.replace(/src="assets\//g, `src="/${templateDir}/assets/`);

        // Inline CSS
        try {
          const cssUrl = new URL(`/${templateDir}/styles.css`, requestUrl);
          const cssResp = await env.ASSETS.fetch(new Request(cssUrl));
          if (cssResp.ok) {
            const css = await cssResp.text();
            html = html.replace(/<link[^>]*href="[^"]*style[^"]*\.css"[^>]*>/gi, `<style>${css}</style>`);
          }
        } catch (e) { console.error("CSS inline failed:", e); }

        // Fix asset paths to absolute URLs so they work from deployed domain
        html = html.replace(/src="\/(templates\/[^"]+)"/g, 'src="https://meinekmu.pages.dev/$1"');
        html = html.replace(/href="\/(templates\/[^"]+)"/g, 'href="https://meinekmu.pages.dev/$1"');

        // Deploy
        const projectName = generateTemplateProjectName(businessName, leadId, tplKey);
        const deployUrl = await deployToCloudflarePages(env, projectName, html);
        await updateTemplateResult(tplKey, deployUrl, "done");
        return { tplKey, url: deployUrl };
      } catch (e) {
        console.error(`Generation failed for ${tplKey}:`, e);
        await updateTemplateResult(tplKey, null, "error");
        throw e;
      }
    }));

    // ── STEP 5: Send welcome email with website previews ──
    if (email && !lead.welcome_email_sent) {
      try {
        await sendCodeEmail(env, leadId, email, businessName, genUrls);
        // Mark welcome email as sent
        try { await updateCells(accessToken, env.LEADS_SHEET_ID, rowIdx, { welcome_email_sent: new Date().toISOString() }); }
        catch (e) { console.error("Welcome tracking error:", e); }
      } catch (e) { console.error("Welcome email error:", e); }
    }
  })());

  return jsonResp({ status: "generating" }, 202);
}

// ── Generation Status ────────────────────────────────────
async function handleGenerationStatus(leadId, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  const status = lead.generation_status ? (() => { try { return JSON.parse(lead.generation_status); } catch { return {}; } })() : {};
  const urls = {};
  TEMPLATE_KEYS.forEach(k => {
    if (lead[`url_${k}`]) urls[k] = lead[`url_${k}`];
  });

  return jsonResp({ status, urls });
}

// ── AI Chat Edit ─────────────────────────────────────────
async function handleChatEdit(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);
  if (!env.ANTHROPIC_API_KEY) return jsonResp({ error: "AI nicht konfiguriert." }, 500);

  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }
  const { html, message, template_key, history, business_context } = body;
  if (!html || !message) return jsonResp({ error: "HTML und Nachricht sind erforderlich." }, 400);

  // Build business context for the system prompt
  const biz = business_context || {};
  const bizName = biz.business_name || "unbekannt";
  const bizCategory = biz.category || "";
  const bizDescription = biz.description || "";
  const bizValues = biz.values || "";
  const bizPhone = biz.phone || "";
  const bizAddress = biz.address || "";

  const systemPrompt = `Du bist ein freundlicher Website-Editor-Assistent für Schweizer KMU. Du hilfst Kunden, ihre Website anzupassen.

Geschäftskontext:
- Firma: ${bizName}
- Branche: ${bizCategory}
- Beschreibung: ${bizDescription}
- Werte & Besonderheiten: ${bizValues}
- Telefon: ${bizPhone}
- Adresse: ${bizAddress}

Du erhältst den aktuellen HTML-Code der Website und eine Nachricht vom Kunden.

WICHTIG — Antworte IMMER als gültiges JSON-Objekt mit genau einem dieser Formate:
{"type": "edit", "html": "<vollständiges geändertes HTML>", "message": "Kurze, natürliche Beschreibung der Änderung"}
oder
{"type": "chat", "message": "Deine Antwort an den Kunden"}

BILDER — SEHR WICHTIG:
- Im HTML gibt es Bildplatzhalter im Format src="[BILD_0]", src="[BILD_1]" usw. Diese sind echte eingebettete Bilder des Kunden. Du MUSST sie exakt beibehalten — lösche oder ersetze sie NIEMALS durch etwas anderes.
- Wenn der Kunde sagt "tausche das Bild aus" oder "ändere das Bild": Antworte mit "type": "chat" und erkläre, dass er das Kamera-Symbol unten links verwenden soll um ein neues Bild hochzuladen — dann tauschst du es ein.
- Wenn der Kunde dir eine Bild-URL (https://...) oder data:image/... gibt: verwende diese direkt im src-Attribut des betreffenden img-Tags.

Regeln:
- Verwende "type": "edit" NUR wenn du tatsächlich das HTML änderst. Gib dann das VOLLSTÄNDIGE geänderte HTML im "html"-Feld zurück.
- Verwende "type": "chat" wenn der Kunde eine Frage stellt, etwas Unmögliches verlangt, oder du Klarstellung brauchst.
- Halte dich STRIKT an den Geschäftskontext. Ändere NIEMALS Texte so, dass sie nichts mehr mit der Firma zu tun haben.
- Ändere NUR das, was der Kunde explizit verlangt. Behalte alle anderen Texte, Bilder, Styles und Struktur exakt bei.
- Schreibe auf Deutsch (Schweizer Stil, kein ß).
- Verwende immer echte Umlaute (ä, ö, ü, Ä, Ö, Ü) — NIEMALS ae, oe, ue schreiben.
- Variiere deine Antworten im "message"-Feld — sei natürlich und freundlich, nicht roboterhaft.

Was du KANNST:
- Texte ändern (Überschriften, Absätze, Button-Texte)
- Farben und einfache Styles anpassen
- Bilder austauschen (NUR wenn der Kunde eine konkrete URL oder data:image liefert)
- Abschnitte umordnen oder entfernen
- Neue Textabschnitte hinzufügen
- Schriftarten anpassen

Was du NICHT kannst (antworte mit "type": "chat" und verweise auf info@meine-kmu.ch):
- Kontaktformulare mit Backend-Funktionalität
- Interaktive JavaScript-Features (Slider, Animationen, Kalender)
- E-Commerce / Shop-Funktionalität
- SEO-Optimierung, Google Analytics, Domain-Konfiguration
- Alles was über HTML/CSS hinausgeht

Bei Anfragen die du nicht umsetzen kannst, antworte freundlich und verweise auf info@meine-kmu.ch für persönliche Unterstützung.`;

  try {
    // Build messages array with conversation history
    const messages = [];
    if (history && Array.isArray(history)) {
      const recent = history.slice(-6); // limit history to last 3 exchanges
      for (const turn of recent) {
        if (turn.role && turn.content) {
          messages.push({ role: turn.role, content: turn.content });
        }
      }
    }
    // Current request with HTML context (data URLs already stripped client-side)
    messages.push({
      role: "user",
      content: `Aktuelle Website:\n${html}\n\nKundenanfrage: ${message}`,
    });

    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 16000,
        system: systemPrompt,
        messages,
      }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error?.message || `API error ${resp.status}`);
    }

    const data = await resp.json();
    let editedText = data.content?.[0]?.text || "";

    // Strip any accidental markdown code fences
    editedText = editedText.replace(/^```(?:json|html)?\s*\n?/i, "").replace(/\n?```\s*$/i, "").trim();

    // Parse structured response with fallbacks
    let result;
    try {
      result = JSON.parse(editedText);
    } catch {
      // Fallback: if AI returned raw HTML (starts with < or <!DOCTYPE)
      if (editedText.trimStart().startsWith("<")) {
        result = { type: "edit", html: editedText, message: "Änderung umgesetzt!" };
      } else {
        // AI returned plain text — treat as chat response
        result = { type: "chat", message: editedText };
      }
    }

    // Validate: if type is "edit", the html field must look like actual HTML
    if (result.type === "edit") {
      const htmlContent = (result.html || "").trim();
      if (!htmlContent.startsWith("<") || htmlContent.length < 50) {
        result = { type: "chat", message: result.message || result.html || "Etwas ist schiefgegangen." };
      }
    }

    return jsonResp(result);
  } catch (e) {
    console.error("Chat edit error:", e);
    return jsonResp({ error: "Änderung fehlgeschlagen: " + e.message }, 500);
  }
}

// ── Upload image for chat editing ─────────────────────────
async function handleChatImageUpload(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);

  let formData;
  try { formData = await request.formData(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }
  const file = formData.get("image");
  if (!file || !file.size) return jsonResp({ error: "Kein Bild hochgeladen." }, 400);

  // Limit to 5MB
  if (file.size > 5 * 1024 * 1024) return jsonResp({ error: "Bild zu gross (max. 5MB)." }, 400);

  try {
    const buf = await file.arrayBuffer();
    const b64 = arrayBufferToBase64(buf);
    const dataUrl = `data:${file.type || "image/png"};base64,${b64}`;
    return jsonResp({ url: dataUrl, filename: file.name });
  } catch (e) {
    console.error("Image upload error:", e);
    return jsonResp({ error: "Upload fehlgeschlagen: " + e.message }, 500);
  }
}

// ── Save HTML to Drive + Redeploy ────────────────────────
async function handleSaveHtml(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);

  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }
  const { html, template_key } = body;
  if (!html || !template_key) return jsonResp({ error: "HTML und Template sind erforderlich." }, 400);
  if (!TEMPLATE_KEYS.includes(template_key)) return jsonResp({ error: "Ungültiges Template." }, 400);

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  const updates = {};

  // 1. Save HTML to Google Drive
  try {
    const folderId = await getOrCreateFolder(accessToken, env.DRIVE_UPLOAD_FOLDER_ID, `${lead.business_name || leadId} (${leadId})`);
    const encoder = new TextEncoder();
    const htmlBytes = encoder.encode(html);
    const fileId = await uploadFileToDrive(accessToken, folderId, htmlBytes, `${template_key}-edited.html`, "text/html");
    if (fileId) updates[`html_${template_key}_drive_id`] = fileId;
  } catch (e) { console.error("Drive save error:", e); }

  // 2. Redeploy to Cloudflare Pages
  let liveUrl = "";
  try {
    const businessName = lead.form_business_name || lead.business_name || "";
    const projectName = generateTemplateProjectName(businessName, leadId, template_key);
    liveUrl = await deployToCloudflarePages(env, projectName, html);
    updates[`url_${template_key}`] = liveUrl;
  } catch (e) { console.error("Redeploy error:", e); }

  // 3. Update sheet
  if (Object.keys(updates).length > 0) {
    try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
    catch (e) { console.error("Sheet update error:", e); }
  }

  return jsonResp({ success: true, live_url: liveUrl });
}

// ── Save HTML draft to Drive only (no redeploy) ──────────
async function handleSaveHtmlDraft(leadId, request, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Ungültige Anfrage." }, 400); }
  const { html, template_key } = body;
  if (!html || !template_key) return jsonResp({ error: "HTML und Template sind erforderlich." }, 400);
  if (!TEMPLATE_KEYS.includes(template_key)) return jsonResp({ error: "Ungültiges Template." }, 400);

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  try {
    const folderId = await getOrCreateFolder(accessToken, env.DRIVE_UPLOAD_FOLDER_ID, `${lead.business_name || leadId} (${leadId})`);
    const encoder = new TextEncoder();
    const htmlBytes = encoder.encode(html);
    const fileId = await uploadFileToDrive(accessToken, folderId, htmlBytes, `${template_key}-draft.html`, "text/html");
    if (fileId) {
      const updates = {};
      updates[`html_${template_key}_drive_id`] = fileId;
      await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates);
      return jsonResp({ success: true, drive_id: fileId });
    }
  } catch (e) { console.error("Draft save error:", e); }
  return jsonResp({ success: false });
}

// ── Fetch saved HTML from Drive by template ──────────────
async function handleGetSavedHtml(leadId, templateKey, env) {
  if (!leadId || !templateKey) return jsonResp({ error: "Invalid params" }, 400);
  if (!TEMPLATE_KEYS.includes(templateKey)) return jsonResp({ error: "Ungültiges Template." }, 400);

  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  const driveId = lead[`html_${templateKey}_drive_id`];
  if (!driveId) return jsonResp({ html: null });

  try {
    const resp = await fetch(`https://www.googleapis.com/drive/v3/files/${driveId}?alt=media`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!resp.ok) return jsonResp({ html: null });
    const html = await resp.text();
    return jsonResp({ html: html || null });
  } catch (e) {
    console.error("Drive fetch error:", e);
    return jsonResp({ html: null });
  }
}

// ── Send Code Email (no-code users) ──────────────────────
async function sendCodeEmail(env, leadId, email, businessName, urls) {
  const templateLabels = { earlydog: "Klassisch", bia: "Modern", liveblocks: "Frisch", loveseen: "Elegant" };

  // Build 2x2 screenshot grid (light theme, matches cold outreach)
  let gridCells = "";
  let linkCount = 0;
  const orderedKeys = ["earlydog", "bia", "liveblocks", "loveseen"];
  for (const key of orderedKeys) {
    const url = urls[key];
    if (url) {
      linkCount++;
      const thumbUrl = `https://image.thum.io/get/width/560/crop/400/${url}`;
      gridCells += `<td width="50%" style="padding:5px;">
        <a href="${url}" target="_blank" style="display:block;text-decoration:none;color:#444;">
          <img src="${thumbUrl}" width="100%" style="border:1px solid #ddd;border-radius:5px;display:block;" alt="${templateLabels[key] || key}">
          <div style="text-align:center;font-size:12px;margin-top:6px;font-weight:600;">${templateLabels[key] || key} →</div>
        </a>
      </td>`;
    }
  }

  if (linkCount === 0) return; // No URLs to send

  // Arrange into 2x2 grid rows
  const cells = gridCells.split("</td>").filter(c => c.trim()).map(c => c + "</td>");
  let gridHtml = '<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">';
  for (let i = 0; i < cells.length; i += 2) {
    gridHtml += `<tr>${cells[i]}${cells[i + 1] || '<td width="50%"></td>'}</tr>`;
  }
  gridHtml += '</table>';

  const biz = businessName || "dein Business";
  const subject = `${biz}, deine ${linkCount} Website Vorschläge sind da!`;
  const html = emailShell(subject, `
    <p style="margin-top:0;">Hey, schön dass du da bist!</p>

    <p>Wir haben <strong>${linkCount} professionelle Website Designs</strong> für <strong>${biz}</strong> erstellt, komplett mit deinen Texten und Bildern.</p>

    <p>Hier ist dein persönlicher Code, damit du jederzeit zurückkommen kannst:</p>

    ${codeBox(leadId)}

    <p>Klick auf ein Design, um es anzuschauen:</p>

    ${gridHtml}

    <p>Logge dich mit deinem Code ein, wähle dein Lieblingsdesign und passe es direkt an. Kostenlos und unverbindlich.</p>
  `);
  await sendEmail(env, email, subject, html);
}

// ── End Session (deploy check + send code email) ─────────
async function handleEndSession(leadId, env) {
  if (!leadId) return jsonResp({ error: "Invalid lead ID" }, 400);
  let accessToken;
  try { accessToken = await getAccessToken(env); } catch { return jsonResp({ error: "Verbindungsfehler." }, 500); }
  const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Lead nicht gefunden." }, 404);

  // Collect deployed URLs
  const urls = {};
  TEMPLATE_KEYS.forEach(k => { if (lead[`url_${k}`]) urls[k] = lead[`url_${k}`]; });

  // Send code email if not already sent and has at least one deployed URL
  const email = lead.owner_email || lead.emails || "";
  const businessName = lead.form_business_name || lead.business_name || "";
  if (email && !lead.email_sent_date && Object.keys(urls).length > 0) {
    try {
      await sendCodeEmail(env, leadId, email, businessName, urls);
      await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, { email_sent_date: new Date().toISOString() });
    } catch (e) { console.error("End-session email error:", e); }
  }

  return jsonResp({ success: true });
}

// ── Fetch URL Proxy (for cross-origin HTML in editor) ────
async function handleFetchUrl(request) {
  let body;
  try { body = await request.json(); } catch { return jsonResp({ error: "Invalid request" }, 400); }
  const targetUrl = body.url;
  if (!targetUrl || !targetUrl.includes(".pages.dev")) return jsonResp({ error: "Invalid URL" }, 400);
  try {
    const resp = await fetch(targetUrl);
    const html = await resp.text();
    return jsonResp({ html });
  } catch (e) { return jsonResp({ error: "Fetch failed: " + e.message }, 500); }
}

// ── Main Worker ───────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS preflight
    if (request.method === "OPTIONS" && path.startsWith("/api/")) {
      return new Response(null, { headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      }});
    }

    // API routes
    if (path.startsWith("/api/")) {
      try {
        // GET /api/lead/:id
        const leadMatch = path.match(/^\/api\/lead\/([^\/]+)$/);
        if (leadMatch && request.method === "GET") return handleGetLead(leadMatch[1], env, ctx);

        // POST /api/lead/register (no-code flow)
        if (path === "/api/lead/register" && request.method === "POST") return handleRegister(request, env);

        // POST /api/lead/:id/update (update lead data)
        const updateMatch = path.match(/^\/api\/lead\/([^\/]+)\/update$/);
        if (updateMatch && request.method === "POST") return handleUpdateLead(updateMatch[1], request, env);

        // POST /api/lead/:id/save-form (save info form data)
        const saveFormMatch = path.match(/^\/api\/lead\/([^\/]+)\/save-form$/);
        if (saveFormMatch && request.method === "POST") return handleSaveForm(saveFormMatch[1], request, env);

        // POST /api/lead/:id/generate-all (background generation of all 4 templates)
        const generateAllMatch = path.match(/^\/api\/lead\/([^\/]+)\/generate-all$/);
        if (generateAllMatch && request.method === "POST") return handleGenerateAll(generateAllMatch[1], request, env, ctx);

        // GET /api/lead/:id/generation-status (poll generation progress)
        const genStatusMatch = path.match(/^\/api\/lead\/([^\/]+)\/generation-status$/);
        if (genStatusMatch && request.method === "GET") return handleGenerationStatus(genStatusMatch[1], env);

        // POST /api/lead/:id/chat-edit (AI chat editing)
        const chatEditMatch = path.match(/^\/api\/lead\/([^\/]+)\/chat-edit$/);
        if (chatEditMatch && request.method === "POST") return handleChatEdit(chatEditMatch[1], request, env);

        // POST /api/lead/:id/upload-chat-image (image upload for chat editor)
        const chatImageMatch = path.match(/^\/api\/lead\/([^\/]+)\/upload-chat-image$/);
        if (chatImageMatch && request.method === "POST") return handleChatImageUpload(chatImageMatch[1], request, env);

        // POST /api/lead/:id/save-html (save edited HTML to Drive + redeploy)
        const saveHtmlMatch = path.match(/^\/api\/lead\/([^\/]+)\/save-html$/);
        if (saveHtmlMatch && request.method === "POST") return handleSaveHtml(saveHtmlMatch[1], request, env);

        // POST /api/lead/:id/save-html-draft (Drive-only save, no redeploy)
        const saveDraftMatch = path.match(/^\/api\/lead\/([^\/]+)\/save-html-draft$/);
        if (saveDraftMatch && request.method === "POST") return handleSaveHtmlDraft(saveDraftMatch[1], request, env);

        // GET /api/lead/:id/saved-html/:template (fetch saved HTML from Drive)
        const getSavedHtmlMatch = path.match(/^\/api\/lead\/([^\/]+)\/saved-html\/([^\/]+)$/);
        if (getSavedHtmlMatch && request.method === "GET") return handleGetSavedHtml(getSavedHtmlMatch[1], getSavedHtmlMatch[2], env);

        // POST /api/lead/:id/end-session (deploy check + send code email)
        const endSessionMatch = path.match(/^\/api\/lead\/([^\/]+)\/end-session$/);
        if (endSessionMatch && request.method === "POST") return handleEndSession(endSessionMatch[1], env);

        // POST /api/fetch-url (proxy for cross-origin HTML fetch)
        if (path === "/api/fetch-url" && request.method === "POST") return handleFetchUrl(request);

        // POST /api/lead/:id/order
        const orderMatch = path.match(/^\/api\/lead\/([^\/]+)\/order$/);
        if (orderMatch && request.method === "POST") return handleOrder(orderMatch[1], request, env);

        // GET /api/preview/:id/:template
        const previewMatch = path.match(/^\/api\/preview\/([^\/]+)\/(earlydog|bia|liveblocks|loveseen)$/);
        if (previewMatch && request.method === "GET") return handlePreview(previewMatch[1], previewMatch[2], request, env, ctx);

        // Fallback preview for _fallback
        const fallbackMatch = path.match(/^\/api\/preview\/_fallback\/(earlydog|bia|liveblocks|loveseen)$/);
        if (fallbackMatch && request.method === "GET") return handlePreview("_fallback", fallbackMatch[1], request, env);

        // POST /api/preview-with-images — full preview with AI image placement
        if (path === "/api/preview-with-images" && request.method === "POST")
          return handlePreviewWithImages(request, env);

        // POST /api/check-domains — check domain availability via RDAP/DNS
        if (path === "/api/check-domains" && request.method === "POST")
          return handleCheckDomains(request);

        // GET /api/lead/:id/confirm-live — mark lead as live + send customer email (triggered from internal notification)
        const confirmLiveMatch = path.match(/^\/api\/lead\/([^\/]+)\/confirm-live$/);
        if (confirmLiveMatch && request.method === "GET") {
          const secret = url.searchParams.get("secret");
          if (!env.CRON_SECRET || secret !== env.CRON_SECRET)
            return new Response("<h1>Nicht autorisiert</h1>", { status: 401, headers: { "Content-Type": "text/html" } });
          return handleConfirmLive(confirmLiveMatch[1], env);
        }

        // POST /api/webhooks/stripe — Stripe payment/cancellation webhooks
        if (path === "/api/webhooks/stripe" && request.method === "POST")
          return handleStripeWebhook(request, env);

        // POST /api/cron/process-reminders — manual/fallback cron trigger
        if (path === "/api/cron/process-reminders" && request.method === "POST") {
          const auth = request.headers.get("Authorization");
          if (!env.CRON_SECRET || auth !== `Bearer ${env.CRON_SECRET}`)
            return jsonResp({ error: "Unauthorized" }, 401);
          ctx.waitUntil(processScheduledEmails(env));
          return jsonResp({ status: "processing" });
        }

        return jsonResp({ error: "Not found" }, 404);
      } catch (e) {
        console.error("API error:", e);
        return jsonResp({ error: "Internal server error: " + e.message }, 500);
      }
    }

    // Everything else → serve static assets
    return env.ASSETS.fetch(request);
  },

  // Daily cron: process reminders, cold follow-ups, DNS checks
  async scheduled(event, env, ctx) {
    ctx.waitUntil(processScheduledEmails(env));
  },
};
