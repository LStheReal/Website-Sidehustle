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
  "response_date","notes","draft_url_1","draft_url_2","draft_url_3","draft_url_4",
  "chosen_template","next_action","next_action_date","acquisition_source",
];

const TEMPLATE_KEYS = ["earlydog", "bia", "liveblocks", "loveseen"];

// ── Preview HTML Cache (in-memory, keyed by leadId) ──
// Stores the generated HTML from preview so the order can reuse it without regenerating.
// Entries expire after 30 minutes.
const previewCache = new Map();
const PREVIEW_CACHE_TTL = 30 * 60 * 1000;

// ── Google OAuth ──────────────────────────────────────────
async function getAccessToken(env) {
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
  await fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": `multipart/related; boundary=${boundary}` },
    body: combined,
  });
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
    GALLERY_LABEL: "Einblicke", INSTAGRAM_HANDLE: "ateliernord", INSTAGRAM_URL: "#",
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
  const values = data._values || "";
  const city = data.city || "";
  // Skip AI if there's no meaningful input
  if (!description && !values && !category && !name) return {};

  const context = [
    name ? `Firmenname: ${name}` : "",
    category ? `Branche: ${category}` : "",
    city ? `Standort: ${city}` : "",
    description ? `Beschreibung vom Kunden: ${description}` : "",
    values ? `Werte/Besonderheiten vom Kunden: ${values}` : "",
  ].filter(Boolean).join("\n");

  const prompt = `Du bist ein Webseiten-Texter für Schweizer KMU. Erstelle professionelle, authentische deutsche Texte für eine Firmenwebsite.

Firma-Info:
${context}

Generiere ein JSON-Objekt mit diesen Feldern. Jeder Text soll einzigartig sein, zur Firma passen und NICHT einfach die Beschreibung wiederholen. Schreibe natürlich und professionell auf Deutsch (Schweizer Stil, kein ß).

{
  "TAGLINE": "kurzer Slogan, max 8 Wörter",
  "HERO_TITLE_LINE1": "erste Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE2": "zweite Zeile Haupttitel, 2-4 Wörter",
  "HERO_TITLE_LINE3": "dritte Zeile oder leer",
  "HERO_DESCRIPTION": "1-2 Sätze, was die Firma bietet, max 150 Zeichen",
  "ABOUT_HEADING": "Überschrift Über-uns-Bereich, 2-4 Wörter",
  "ABOUT_LEAD": "1 Satz Einleitung zum Über-uns-Text, max 100 Zeichen",
  "ABOUT_DESCRIPTION": "2-3 Sätze über die Firma, Werte und Arbeitsweise",
  "INTRO_TEXT": "kurze Einleitung, 3-5 Wörter",
  "INTRO_DESCRIPTION": "1 Satz Firmenbeschreibung, max 120 Zeichen",
  "FEATURE_HEADING": "Überschrift Vorteile-Bereich, 2-4 Wörter",
  "FEATURE_DESCRIPTION": "1 Satz warum diese Firma, max 100 Zeichen",
  "FEATURE_POINT_1": "Vorteil 1, 2-3 Wörter",
  "FEATURE_POINT_2": "Vorteil 2, 2-3 Wörter",
  "FEATURE_POINT_3": "Vorteil 3, 2-3 Wörter",
  "SERVICE_1_TITLE": "Leistung 1 Name",
  "SERVICE_1_DESCRIPTION": "1 Satz zu Leistung 1",
  "SERVICE_2_TITLE": "Leistung 2 Name",
  "SERVICE_2_DESCRIPTION": "1 Satz zu Leistung 2",
  "SERVICE_3_TITLE": "Leistung 3 Name",
  "SERVICE_3_DESCRIPTION": "1 Satz zu Leistung 3",
  "CTA_DESCRIPTION": "Handlungsaufforderung, 1 Satz",
  "CTA_TITLE_LINE1": "CTA Titel Zeile 1, 2-3 Wörter",
  "CTA_TITLE_LINE2": "CTA Titel Zeile 2, 2-3 Wörter",
  "VALUE_1_TITLE": "Wert 1, 1-2 Wörter",
  "VALUE_1_DESCRIPTION": "kurze Beschreibung Wert 1",
  "VALUE_2_TITLE": "Wert 2, 1-2 Wörter",
  "VALUE_2_DESCRIPTION": "kurze Beschreibung Wert 2",
  "VALUE_3_TITLE": "Wert 3, 1-2 Wörter",
  "VALUE_3_DESCRIPTION": "kurze Beschreibung Wert 3",
  "STATEMENT_LINE1": "Statement Zeile 1, 2-4 Wörter",
  "STATEMENT_LINE2": "Statement Zeile 2, 2-4 Wörter",
  "STATEMENT_LINE3": "Statement Zeile 3, 2-4 Wörter",
  "META_DESCRIPTION": "SEO-Beschreibung, max 155 Zeichen",
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
async function mergeWithDefaults(env, templateKey, leadData) {
  const defaults = TEMPLATE_DEFAULTS[templateKey] || {};
  const merged = { ...defaults };

  // Override defaults with lead data (non-empty values only)
  // Skip _description and _values context fields — they're for AI only
  for (const [key, value] of Object.entries(leadData)) {
    if (key.startsWith("_")) continue;
    if (value !== null && value !== undefined && value !== "") {
      merged[key] = String(value);
    }
  }

  // AI text enrichment — generates unique copy based on business info
  // AI values override template defaults for ALL text fields
  // Also returns CATEGORY which is used for Pexels image search
  const aiText = await enrichWithAI(env, { ...merged, _description: leadData._description || "", _values: leadData._values || "" }, templateKey);
  let aiCategory = "";
  for (const [key, value] of Object.entries(aiText)) {
    if (key === "CATEGORY") {
      aiCategory = String(value);
      continue; // Don't put CATEGORY into the HTML placeholders
    }
    if (value && !key.startsWith("IMAGE_")) {
      merged[key] = String(value);
    }
  }
  // Store AI category on merged so callers can write it back to the sheet
  merged._aiCategory = aiCategory;

  // Auto-generate META_DESCRIPTION if AI didn't provide one
  if (!merged.META_DESCRIPTION) {
    const name = merged.BUSINESS_NAME || "";
    const tagline = merged.TAGLINE || "";
    merged.META_DESCRIPTION = tagline ? `${name} — ${tagline}` : name;
  }

  // Fetch Pexels images for IMAGE_* slots not explicitly set by user uploads
  // Skip Pexels when there's no real business context (e.g. step-2 fallback preview)
  const hasBusinessContext = !!(leadData._description || leadData._values || leadData.category || (leadData.BUSINESS_NAME && leadData.BUSINESS_NAME !== ""));
  const slotMap = IMAGE_SLOT_MAP[templateKey] || {};
  if (hasBusinessContext) {
    // Use AI-determined category for better Pexels results, fall back to lead data
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

  // Pass description + values as AI context — NOT as direct placeholder overrides.
  // These are used by enrichWithAI() to generate proper unique text for each section.
  if (cust.description) data._description = cust.description.trim();
  if (cust.values) data._values = cust.values.trim();

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
        system: "Du bist ein professioneller Website-Texter f\u00fcr Schweizer KMUs. Deutsch, modern, pr\u00e4gnant. Hero-Titel: max 3-4 W\u00f6rter. BUSINESS_NAME_SHORT: erstes Wort + Punkt. Stats: '15+', '500+'. Services: branchenspezifisch. NUR JSON.",
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
async function handleGetLead(leadId, env) {
  if (!leadId || leadId.length > 50)
    return jsonResp({ error: "Ung\u00fcltiges Format. Pr\u00fcfe die E-Mail mit deinem Code." }, 400);
  let accessToken, sheetData;
  try { accessToken = await getAccessToken(env); sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID); }
  catch (e) { console.error("Sheet error:", e); return jsonResp({ error: "Verbindungsfehler. Versuche es erneut." }, 500); }

  const lead = findLead(sheetData, leadId);
  if (!lead) return jsonResp({ error: "Code nicht gefunden. Pr\u00fcfe die E-Mail." }, 404);

  const previews = [];
  for (let i = 1; i <= 4; i++) {
    let url = (lead[`draft_url_${i}`] || "").trim();
    if (!url || !(url.startsWith("http") || url.startsWith("/"))) url = `/api/preview/${leadId}/${TEMPLATE_KEYS[i-1]}`;
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
    chosen_template: lead.chosen_template, notes: lead.notes });
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

  // Check if this email already has a lead (dedup)
  try {
    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    const rows = sheetData.values || [];
    const emailIdx = COLUMN_NAMES.indexOf("owner_email");
    for (let i = 1; i < rows.length; i++) {
      if ((rows[i][emailIdx] || "").trim().toLowerCase() === email) {
        // Return existing lead instead of creating a duplicate
        const existingLead = { _row_idx: i + 1 };
        COLUMN_NAMES.forEach((name, j) => { existingLead[name] = rows[i][j] || ""; });
        console.log("[register] Existing lead found for", email, "→", existingLead.lead_id);
        return jsonResp({
          lead_id: existingLead.lead_id,
          business_name: existingLead.business_name,
          category: existingLead.category,
          city: existingLead.city,
          phone: existingLead.phone,
          owner_email: existingLead.owner_email,
          owner_name: existingLead.owner_name,
          address: existingLead.address,
          status: existingLead.status,
          previews: TEMPLATE_KEYS.map(t => `/api/preview/${existingLead.lead_id}/${t}`),
          domains: [],
          chosen_template: existingLead.chosen_template,
          notes: existingLead.notes,
        });
      }
    }
  } catch (e) { console.error("Dedup check error:", e); }

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
  const values = fd.get("values")||"", selectedDomain = fd.get("selected_domain")||"";
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
      const result = await generateFinalHTML(env, request.url, chosenTemplate, leadId, description, values, logo, images, phone, address);
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

  // 4. Send emails (don't block on failure)
  const leadEmail = lead.owner_email || lead.emails || "";
  const purchaseLink = domainPurchaseLink(selectedDomain, lead.domain_option_1_purchase || "");
  const cfDomainLink = projectName ? cloudflareDomainLink(projectName) : "";
  try {
    await sendInternalNotification(env, leadId, lead.business_name || leadId, leadEmail, liveUrl || "(deploy fehlgeschlagen)", selectedDomain, purchaseLink, cfDomainLink);
  } catch (e) { console.error("Internal email error:", e); }
  try {
    await sendCustomerConfirmation(env, lead.owner_name || "", lead.business_name || leadId, leadEmail, selectedDomain);
  } catch (e) { console.error("Customer email error:", e); }

  // 5. Update Google Sheet
  const now = new Date().toISOString();
  const updates = {
    chosen_template: chosenTemplate,
    notes: JSON.stringify({ order_date: now, description, values, selected_domain: selectedDomain, drive_folder: driveFolderUrl, project_name: projectName }),
    status: liveUrl ? "website_created" : "website_creating",
    next_action: liveUrl ? "CONNECT DOMAIN" : "DEPLOY MANUALLY",
    next_action_date: now.slice(0,10),
  };
  if (selectedDomain) updates.domain_option_1 = selectedDomain;
  if (liveUrl) updates.website_url = liveUrl;
  if (phone) updates.phone = phone;
  if (address) updates.address = address;
  try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
  catch (e) { console.error("Sheet update error:", e); }

  return jsonResp({ success: true, message: "Bestellung erfolgreich!", drive_folder: driveFolderUrl, live_url: liveUrl || null, project_name: projectName || null });
}

async function handlePreview(leadId, templateKey, request, env) {
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
    description: url.searchParams.get("description") || "",
    values: url.searchParams.get("values") || "",
    phone: url.searchParams.get("phone") || "",
    address: url.searchParams.get("address") || "",
  };
  // Build placeholder data — works with or without a lead record
  const fakeLead = { business_name: url.searchParams.get("business_name") || "" };
  const placeholderData = leadToPlaceholderData(lead || fakeLead, cust);

  // Merge with template defaults + Pexels images
  const merged = await mergeWithDefaults(env, templateKey, placeholderData);

  for (const [key, value] of Object.entries(merged)) html = html.replaceAll(`{{${key}}}`, value);
  html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");

  // Fix CSS path
  html = html.replaceAll('href="styles.css"', `href="/${templateDir}/styles.css"`);
  html = html.replaceAll('href="./styles.css"', `href="/${templateDir}/styles.css"`);

  // Fix relative image paths (for fallback SVG/JPG assets when Pexels didn't fill them)
  html = html.replace(/src="assets\//g, `src="/${templateDir}/assets/`);

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
async function generateFinalHTML(env, requestUrl, templateKey, leadId, description, values, logoFile, imageFiles, phone, address) {
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
  const cust = { description, values, phone: phone || "", address: address || "" };
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
    const values = fd.get("values") || "";
    const phone = fd.get("phone") || "";
    const address = fd.get("address") || "";
    const result = await generateFinalHTML(
      env, request.url, templateKey, leadId, description, values,
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

async function sendInternalNotification(env, leadId, businessName, leadEmail, liveUrl, selectedDomain, purchaseLink, cfDomainLink) {
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
    <table style="width:100%;border-collapse:collapse;">
      <tr><td style="padding:10px 0;border-bottom:1px solid #eee;">
        <div style="font-size:13px;color:#888;margin-bottom:4px;">Website (live)</div>
        <a href="${liveUrl}" style="color:#1a1a1a;font-weight:600;">${liveUrl}</a></td></tr>
      <tr><td style="padding:10px 0;border-bottom:1px solid #eee;">
        <div style="font-size:13px;color:#888;margin-bottom:4px;">Domain kaufen</div>
        <a href="${purchaseLink}" style="color:#1a1a1a;font-weight:600;">${selectedDomain || "Domain suchen"} →</a></td></tr>
      <tr><td style="padding:10px 0;">
        <div style="font-size:13px;color:#888;margin-bottom:4px;">Domain mit Website verbinden</div>
        <a href="${cfDomainLink}" style="color:#1a1a1a;font-weight:600;">Cloudflare Pages → Custom Domain →</a></td></tr>
    </table>
    <div style="background:#f5f5f5;border-radius:6px;padding:16px;margin-top:24px;font-size:13px;color:#555;">
      <strong>Nächste Schritte:</strong><br>
      1. Domain kaufen (oben)<br>
      2. Domain im Cloudflare Dashboard mit dem Pages-Projekt verbinden<br>
      3. Warten bis DNS propagiert (5–30 min)<br>
      4. Kunden informieren
    </div>
  </div>
${emailFooter()}
</body></html>`;
  await sendEmail(env, "info@meine-kmu.ch", subject, html);
}

async function sendCustomerConfirmation(env, ownerName, businessName, leadEmail, selectedDomain) {
  if (!leadEmail) { console.log("No lead email — skipping customer confirmation"); return; }
  const greeting = `Grüezi${ownerName && ownerName.trim() ? " " + ownerName.trim() : ""}`;
  const domainDisplay = selectedDomain || "Ihrer gewünschten Adresse";
  const subject = `Ihre Website ist in Bearbeitung — ${businessName}`;
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',Helvetica,Arial,sans-serif;max-width:580px;margin:0 auto;padding:0;color:#333;line-height:1.6;">
${emailHeader()}
  <div style="padding:28px 24px;">
    <p style="margin-top:0;">${greeting}</p>
    <p>Vielen Dank für Ihre Bestellung! Wir haben Ihre Angaben erhalten und beginnen jetzt mit der Umsetzung Ihrer Website.</p>
    <div style="background:#f5f5f5;border:1px solid #e0e0e0;border-radius:8px;padding:22px;margin:24px 0;text-align:center;">
      <div style="font-size:11px;color:#999;margin-bottom:8px;text-transform:uppercase;letter-spacing:1.5px;">Ihre zukünftige Adresse</div>
      <div style="font-size:24px;font-weight:bold;letter-spacing:1px;color:#1a1a1a;margin-bottom:12px;">${domainDisplay}</div>
      <div style="font-size:14px;color:#555;">
        Ihre Website wird innerhalb von <strong>48 Stunden</strong> auf<br>
        <strong>${domainDisplay}</strong> live geschaltet.
      </div>
    </div>
    <p style="font-size:14px;color:#555;">
      Sobald Ihre Website fertig ist, erhalten Sie von uns eine weitere E-Mail mit dem direkten Link.
      Falls Sie in der Zwischenzeit Fragen haben, antworten Sie einfach auf diese E-Mail.
    </p>
    <p style="margin-bottom:0;">Freundliche Grüsse<br>
    <strong>Das meine-kmu.ch Team</strong><br>
    <a href="mailto:info@meine-kmu.ch" style="color:#555;">info@meine-kmu.ch</a><br>
    <a href="https://meine-kmu.ch" style="color:#555;">meine-kmu.ch</a></p>
  </div>
${emailFooter()}
</body></html>`;
  await sendEmail(env, leadEmail, subject, html);
}

// ── Main Worker ───────────────────────────────────────────
export default {
  async fetch(request, env) {
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
        if (leadMatch && request.method === "GET") return handleGetLead(leadMatch[1], env);

        // POST /api/lead/register (no-code flow)
        if (path === "/api/lead/register" && request.method === "POST") return handleRegister(request, env);

        // POST /api/lead/:id/update (update lead data)
        const updateMatch = path.match(/^\/api\/lead\/([^\/]+)\/update$/);
        if (updateMatch && request.method === "POST") return handleUpdateLead(updateMatch[1], request, env);

        // POST /api/lead/:id/order
        const orderMatch = path.match(/^\/api\/lead\/([^\/]+)\/order$/);
        if (orderMatch && request.method === "POST") return handleOrder(orderMatch[1], request, env);

        // GET /api/preview/:id/:template
        const previewMatch = path.match(/^\/api\/preview\/([^\/]+)\/(earlydog|bia|liveblocks|loveseen)$/);
        if (previewMatch && request.method === "GET") return handlePreview(previewMatch[1], previewMatch[2], request, env);

        // Fallback preview for _fallback
        const fallbackMatch = path.match(/^\/api\/preview\/_fallback\/(earlydog|bia|liveblocks|loveseen)$/);
        if (fallbackMatch && request.method === "GET") return handlePreview("_fallback", fallbackMatch[1], request, env);

        // POST /api/preview-with-images — full preview with AI image placement
        if (path === "/api/preview-with-images" && request.method === "POST")
          return handlePreviewWithImages(request, env);

        // POST /api/check-domains — check domain availability via RDAP/DNS
        if (path === "/api/check-domains" && request.method === "POST")
          return handleCheckDomains(request);

        return jsonResp({ error: "Not found" }, 404);
      } catch (e) {
        console.error("API error:", e);
        return jsonResp({ error: "Internal server error: " + e.message }, 500);
      }
    }

    // Everything else → serve static assets
    return env.ASSETS.fetch(request);
  },
};
