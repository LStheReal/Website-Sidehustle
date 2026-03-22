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

// Image slots per template: slot name → { file, description }
const TEMPLATE_IMAGE_SLOTS = {
  earlydog: [
    { slot: "hero", file: "hero.svg", desc: "Grosses Hero-Bild oben auf der Seite (Vollbild, Blickfang)" },
    { slot: "section1", file: "section1.svg", desc: "Service-Bereich 1 (zeigt erste Dienstleistung)" },
    { slot: "section2", file: "section2.svg", desc: "Service-Bereich 2 (zeigt zweite Dienstleistung)" },
    { slot: "section3", file: "section3.svg", desc: "Service-Bereich 3 (zeigt dritte Dienstleistung)" },
  ],
  bia: [
    { slot: "hero", file: "hero.svg", desc: "Grosses Hero-Bild oben auf der Seite (Vollbild, Blickfang)" },
    { slot: "showcase", file: "showcase.svg", desc: "Showcase/Portfolio-Bereich (zeigt Arbeit oder Produkte)" },
    { slot: "cta", file: "cta.svg", desc: "Call-to-Action-Bereich (motivierend, einladend)" },
    { slot: "contact", file: "contact.svg", desc: "Kontakt-Bereich (persönlich, einladend)" },
  ],
  liveblocks: [
    { slot: "feature", file: "feature.svg", desc: "Feature/Highlight-Bereich (zeigt Hauptmerkmal)" },
    { slot: "about", file: "about.svg", desc: "Über-uns-Bereich (Team, Geschäft, persönlich)" },
  ],
  loveseen: [
    { slot: "hero", file: "hero.jpg", desc: "Grosses Hero-Bild oben (Vollbild, stimmungsvoll, Haupteindruck)" },
    { slot: "about", file: "about.jpg", desc: "Über-uns-Bereich (Polaroid-Stil, persönlich, Team oder Inhaber)" },
    { slot: "gallery1", file: "gallery1.jpg", desc: "Galerie Hauptbild (gross, zeigt beste Arbeit/Produkt)" },
    { slot: "gallery2", file: "gallery2.jpg", desc: "Galerie klein 1 (ergänzend, Detail oder anderes Produkt)" },
    { slot: "gallery3", file: "gallery3.jpg", desc: "Galerie klein 2 (ergänzend, Atmosphäre oder weiteres Produkt)" },
  ],
};

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

  // Generate a 12-char hex lead_id from email + timestamp
  const encoder = new TextEncoder();
  const data = encoder.encode(email + Date.now().toString());
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const leadId = hashArray.map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 12);

  // Create a new row in the sheet with minimal data
  const now = new Date().toISOString();
  const row = new Array(COLUMN_NAMES.length).fill("");
  row[COLUMN_NAMES.indexOf("lead_id")] = leadId;
  row[COLUMN_NAMES.indexOf("scraped_at")] = now;
  row[COLUMN_NAMES.indexOf("owner_email")] = email;
  row[COLUMN_NAMES.indexOf("emails")] = email;
  row[COLUMN_NAMES.indexOf("status")] = "registered_no_code";
  row[COLUMN_NAMES.indexOf("acquisition_source")] = "organic";

  try { await appendRow(accessToken, env.LEADS_SHEET_ID, row); }
  catch (e) { console.error("Append error:", e); return jsonResp({ error: "Registrierung fehlgeschlagen." }, 500); }

  // Return minimal lead data (no previews, no domains — those come later)
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
    existingNotes.description = body.description || "";
    existingNotes.values = body.values || "";
    updates.notes = JSON.stringify(existingNotes);
  }
  if (body.category) updates.category = body.category;
  if (body.city) updates.city = body.city;

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

  // 2. Generate the final website HTML (same as preview)
  let finalHtml = null;
  let liveUrl = "";
  let projectName = "";
  try {
    finalHtml = await generateFinalHTML(env, request.url, chosenTemplate, leadId, description, values, logo, images);
  } catch (e) { console.error("HTML generation error:", e); }

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
  try { await updateCells(accessToken, env.LEADS_SHEET_ID, lead._row_idx, updates); }
  catch (e) { console.error("Sheet update error:", e); }

  return jsonResp({ success: true, message: "Bestellung erfolgreich!", drive_folder: driveFolderUrl, live_url: liveUrl || null, project_name: projectName || null });
}

async function handlePreview(leadId, templateKey, request, env) {
  if (!TEMPLATE_KEYS.includes(templateKey)) return new Response("Template not found", { status: 404 });
  const templateDir = `templates/${templateKey}`;
  // Fetch template HTML from static assets via ASSETS binding
  const assetUrl = new URL(`/${templateDir}/index.html`, request.url);
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
  if (lead) {
    const cust = { description: url.searchParams.get("description")||"", values: url.searchParams.get("values")||"" };
    let replacements = (cust.description || cust.values) ? await generateAIContent(env, lead, templateKey, cust) : null;
    if (!replacements) replacements = buildFallbackReplacements(lead, cust);
    for (const [key, value] of Object.entries(replacements)) html = html.replaceAll(`{{${key}}}`, value);
  }
  html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");
  const basePath = `/${templateDir}/`;
  html = html.replaceAll('src="assets/', `src="${basePath}assets/`).replaceAll("src='assets/", `src='${basePath}assets/`)
    .replaceAll('href="assets/', `href="${basePath}assets/`).replaceAll('href="style', `href="${basePath}style`).replaceAll('href="./style', `href="${basePath}style`);

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
async function generateFinalHTML(env, requestUrl, templateKey, leadId, description, values, logoFile, imageFiles) {
  if (!TEMPLATE_KEYS.includes(templateKey)) throw new Error("Template not found: " + templateKey);

  // 1. Get template HTML
  const templateDir = `templates/${templateKey}`;
  const assetUrl = new URL(`/${templateDir}/index.html`, requestUrl);
  const templateResp = await env.ASSETS.fetch(new Request(assetUrl));
  if (!templateResp.ok) throw new Error("Template HTML not found");
  let html = await templateResp.text();

  // 2. Get lead data and generate AI text content
  let lead = null;
  try {
    const accessToken = await getAccessToken(env);
    const sheetData = await getSheetValues(accessToken, env.LEADS_SHEET_ID);
    lead = findLead(sheetData, leadId);
  } catch (e) { console.error("Lead lookup error:", e); }

  if (lead) {
    const cust = { description, values };
    let replacements = (description || values) ? await generateAIContent(env, lead, templateKey, cust) : null;
    if (!replacements) replacements = buildFallbackReplacements(lead, cust);
    for (const [key, value] of Object.entries(replacements)) html = html.replaceAll(`{{${key}}}`, value);
  }
  html = html.replace(/\{\{[A-Z_0-9]+\}\}/g, "");

  // Fix asset paths for preview (relative → absolute)
  const basePath = `/${templateDir}/`;
  html = html.replaceAll('src="assets/', `src="${basePath}assets/`).replaceAll("src='assets/", `src='${basePath}assets/`)
    .replaceAll('href="assets/', `href="${basePath}assets/`).replaceAll('href="style', `href="${basePath}style`).replaceAll('href="./style', `href="${basePath}style`);

  // 3. Process uploaded images
  const images = (imageFiles || []).filter(f => f && f.size > 0);
  const imageDataUrls = [];
  const imageFilenames = [];
  for (const img of images) {
    const buf = await img.arrayBuffer();
    const b64 = arrayBufferToBase64(buf);
    imageDataUrls.push(`data:${img.type || "image/png"};base64,${b64}`);
    imageFilenames.push(img.name || `image_${imageDataUrls.length}`);
  }

  // 4. Inject logo
  if (logoFile && logoFile.size > 0) {
    const logoBuf = await logoFile.arrayBuffer();
    const logoB64 = arrayBufferToBase64(logoBuf);
    const logoDataUrl = `data:${logoFile.type || "image/png"};base64,${logoB64}`;
    const logoImgTag = `<img src="${logoDataUrl}" alt="Logo" style="height:40px;width:auto;object-fit:contain;">`;
    const footerLogoTag = `<img src="${logoDataUrl}" alt="Logo" style="height:32px;width:auto;object-fit:contain;">`;
    html = html.replace(/(<(?:a|div)[^>]*class="[^"]*nav-logo[^"]*"[^>]*>)([\s\S]*?)(<\/(?:a|div)>)/i, `$1${logoImgTag}$3`);
    html = html.replace(/(<(?:a|div|span)[^>]*class="[^"]*(?:contact-logo|footer-logo(?:-text)?)[^"]*"[^>]*>)([\s\S]*?)(<\/(?:a|div|span)>)/i, `$1${footerLogoTag}$3`);
  }

  // 5. AI image placement
  if (imageDataUrls.length > 0) {
    const slots = TEMPLATE_IMAGE_SLOTS[templateKey] || [];
    let placement = null;
    const businessName = (lead && lead.business_name) || "Business";
    placement = await generateAIImagePlacement(env, templateKey, imageFilenames, businessName);

    // Validate: no image used twice
    if (placement) {
      const usedIndices = new Set();
      const cleanPlacement = {};
      for (const [slot, idx] of Object.entries(placement)) {
        if (typeof idx === "number" && idx >= 0 && idx < imageDataUrls.length && !usedIndices.has(idx)) {
          cleanPlacement[slot] = idx;
          usedIndices.add(idx);
        }
      }
      placement = cleanPlacement;
    }

    // Fallback: sequential
    if (!placement || Object.keys(placement).length === 0) {
      placement = {};
      for (let i = 0; i < Math.min(imageDataUrls.length, slots.length); i++) {
        placement[slots[i].slot] = i;
      }
    }

    // Apply placement
    for (const slotDef of slots) {
      const imgIdx = placement[slotDef.slot];
      if (imgIdx === undefined || imgIdx === null || !imageDataUrls[imgIdx]) continue;
      const fileBase = slotDef.file.replace(/\.[^.]+$/, "");
      const fileExt = slotDef.file.split(".").pop();
      const srcPattern = new RegExp(`src="${basePath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}assets/images/${fileBase}\\.${fileExt}"`, "g");
      html = html.replace(srcPattern, `src="${imageDataUrls[imgIdx]}" style="object-fit:cover;width:100%;height:100%;"`);
    }
  }

  // 6. Inline the CSS so the deployed HTML is fully self-contained
  const cssUrl = new URL(`/${templateDir}/style.css`, requestUrl);
  try {
    const cssResp = await env.ASSETS.fetch(new Request(cssUrl));
    if (cssResp.ok) {
      const css = await cssResp.text();
      html = html.replace(/<link[^>]*href="[^"]*style[^"]*\.css"[^>]*>/gi, `<style>${css}</style>`);
    }
  } catch (e) { console.error("CSS inline failed:", e); }

  return html;
}

async function handlePreviewWithImages(request, env) {
  try {
    const fd = await request.formData();
    const html = await generateFinalHTML(
      env, request.url,
      fd.get("template") || "",
      fd.get("lead_id") || "",
      fd.get("description") || "",
      fd.get("values") || "",
      fd.get("logo"),
      fd.getAll("images")
    );
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
