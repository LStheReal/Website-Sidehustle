# Email Drafts — meine-kmu.ch

Alle Emails signed off by **Louise & Mael**. Gleicher branded Header, gleicher Footer, gleicher Style.

---

## Overview

| # | Email | Trigger | Automation |
|---|-------|---------|------------|
| A1 | Cold Day 0 | User sagt "send N cold emails" | Manueller Trigger, dann auto |
| A2 | Cold Day 7 | 7 Tage nach Day 0, keine Antwort | Auto (daily cron) |
| A3 | Cold Day 14 | 14 Tage nach Day 0, keine Antwort | Auto (daily cron) |
| B | Welcome + Code | No code User registriert sich | Auto (on register) |
| C1 | Reminder v1 | 3 Tage nach Dashboard Besuch | Auto (daily cron) |
| C2 | Reminder v2 | 7 Tage nach C1 | Auto (daily cron) |
| C3 | Reminder v3 | Monatlich nach C2 | Auto (daily cron, rotiert Varianten) |
| D | Bestellbestätigung | Stripe Zahlung erfolgreich | Auto (Stripe webhook) |
| E | Website ist live | Domain resolved | Auto (daily cron DNS check) |
| F | Interne Benachrichtigung | Stripe Zahlung erfolgreich | Auto (Stripe webhook) |
| G | Kündigung | Stripe subscription cancelled | Auto (Stripe webhook) |

**Stopp:** Reminders (C1 C3) stoppen wenn status = `sold`/`website_created`/`website_creating` oder `subscription_status = cancelled`.

---

## A1 — Cold Day 0

**Wird nicht verändert.** Nutzt die bestehende Cold Email aus dem `cold-email` Skill (Python/SMTP mit inline Screenshots). Schon implementiert und läuft.

---

## A2 — Cold Day 7 (Follow up)

**Subject:** Kurze Nachfrage wegen {business}
**Format:** Branded HTML mit 2x2 Grid + Code Box

> Guten Tag,
>
> ich wollte kurz nachfragen ob meine E-Mail von letzter Woche angekommen ist. Ich hatte Website Entwürfe für **{business}** erstellt und würde mich freuen wenn Sie mal einen Blick drauf werfen.
>
> [CODE BOX: {lead_id}]
>
> [2x2 WEBSITE GRID]
>
> [Button: Website ansehen →]

---

## A3 — Cold Day 14 (Letzte Nachricht)

**Subject:** Letzte Nachricht wegen {business}
**Format:** Branded HTML mit 2x2 Grid + Code Box

> Guten Tag,
>
> dies ist meine letzte Nachricht, ich möchte Ihre Zeit nicht länger beanspruchen. Falls Sie die Website für **{business}** zu einem späteren Zeitpunkt möchten, können Sie sich jederzeit melden. Ihr Zugangscode bleibt noch 14 Tage aktiv.
>
> [CODE BOX: {lead_id}]
>
> [2x2 WEBSITE GRID]
>
> [Button: Website ansehen →]

---

## B — Welcome + Code (Registration)

**Subject:** Schön, dass du da bist!
**Format:** Branded HTML mit Code Box

> Hey, willkommen bei meine-kmu!
>
> Mega cool, dass du dich angemeldet hast. Wir haben deinen Account erstellt und legen direkt los.
>
> Hier ist dein persönlicher Code, damit du jederzeit zurückkommen kannst:
>
> [CODE BOX: {lead_id}]
>
> Wir bereiten gerade Website Vorschläge für dich vor. Sobald die fertig sind, schicken wir dir nochmal eine Mail mit Vorschau Bildern und Links.
>
> [Button: Zum Dashboard →]
>
> Logge dich einfach mit deinem Code ein und schau dich um. Alles kostenlos und unverbindlich.

---

## C1 — Reminder Variant 1 (3 Tage Nudge)

**Subject:** {business}, deine Website wartet auf dich
**Format:** Branded HTML mit 2x2 Grid + Code Box

> **{business}, deine Website wartet!**
>
> Hey! Wir haben gesehen, dass du dir Websites für **{business}** angeschaut hast. Sieht echt gut aus! Falls du noch nicht bestellt hast, kein Stress, deine Entwürfe sind gespeichert und warten auf dich.
>
> [CODE BOX: {lead_id}]
>
> [2x2 WEBSITE GRID]
>
> [Button: Weiter zur Website →]

---

## C2 — Reminder Variant 2 (10 Tage, Hilfe anbieten)

**Subject:** Können wir dir helfen, {business}?
**Format:** Branded HTML mit 2x2 Grid + Code Box

> **Brauchst du Hilfe mit deiner Website?**
>
> Hey! Deine Website Entwürfe für **{business}** sind immer noch gespeichert bei uns. Falls irgendwas unklar ist oder du nicht weiterkommst, schreib uns einfach. Wir helfen dir gerne weiter!
>
> Du kannst uns auch direkt erreichen: info@meine-kmu.ch
>
> [CODE BOX: {lead_id}]
>
> [2x2 WEBSITE GRID]
>
> [Button: Weiter zur Website →]

---

## C3 — Reminder Variant 3 (Monatlicher Check in)

**Subject:** Immer noch Interesse an einer Website, {business}?
**Format:** Branded HTML mit 2x2 Grid + Code Box

> **Dein Entwurf für {business} ist noch da!**
>
> Kurzer Check in: Dein Website Entwurf für **{business}** ist weiterhin bei uns gespeichert. Das Angebot steht, wenn du bereit bist, sind wir es auch. Schau einfach nochmal rein wenn du magst!
>
> [CODE BOX: {lead_id}]
>
> [2x2 WEBSITE GRID]
>
> [Button: Weiter zur Website →]

---

## D — Bestellbestätigung (nach Stripe Zahlung)

**Subject:** Danke für deine Bestellung, {business}!
**Format:** Branded HTML mit Domain Box

> **Bestellung bestätigt für {business}!**
>
> Hallo {name}!
>
> Deine Zahlung ist eingegangen, vielen Dank! Wir freuen uns mega und legen direkt los mit deiner Website für **{business}**.
>
> [DOMAIN BOX: {domain}]
>
> Innerhalb von 48 Stunden ist deine Website unter **{domain}** live erreichbar. Wir melden uns sobald alles bereit ist!
>
> Falls du Fragen hast, schreib uns einfach: info@meine-kmu.ch

---

## E — Website ist live

**Subject:** {business} ist jetzt online!
**Format:** Branded HTML mit Live Link Button

> **{business} ist live!**
>
> Hallo {name}!
>
> Deine Website für **{business}** ist ab sofort live erreichbar. Schau sie dir an!
>
> [Button: {domain} besuchen →]
>
> Was du jetzt machen kannst:
> • Teile den Link auf Social Media und Google Business
> • Schick den Link an deine bestehenden Kunden
> • Falls du was ändern willst, meld dich einfach bei uns
>
> Herzlichen Glückwunsch zur neuen Website! Wir freuen uns für dich.

---

## F — Interne Benachrichtigung

Unverändert. HTML Tabelle mit Lead ID, Betrieb, E-Mail, Domain, Aktions Links (Namecheap, Cloudflare), Checkliste.

---

## G — Kündigung

**Subject:** Schade, {business}!
**Format:** Branded HTML

> **Wir haben deine Kündigung erhalten**
>
> Hallo {name},
>
> schade dass du gehst! Deine Website für **{business}** bleibt bis zum Ende der bezahlten Periode erreichbar.
>
> Falls du es dir anders überlegst, meld dich einfach bei uns. Dein Entwurf bleibt gespeichert und wir können jederzeit weitermachen.
>
> Wir wünschen dir alles Gute!
>
> Fragen? Schreib uns: info@meine-kmu.ch

---

## Gemeinsame Elemente (alle Emails)

**Branded Header:** Dunkler Balken mit "meine-kmu." Logo (grüner Punkt)
**Code Box:** Dunkle Box mit grünem Code in Monospace
**CTA Button:** Grüner (#a6ff00) runder Button
**Footer:** Grauer Balken mit meine-kmu.ch · info@meine-kmu.ch
**Sign off:** "Freundliche Grüsse, Louise & Mael, meine-kmu.ch"
**2x2 Grid:** Screenshot Thumbnails via thum.io, klickbar, mit Template Labels

## Sheet Tracking

| Col | Name | Updated By |
|-----|------|------------|
| 32 | `email_sent_date` | Cold Day 0 send |
| 34 | `notes` (JSON: `day7_sent`, `day14_sent`) | Cron cold follow ups |
| 57 | `last_dashboard_visit` | Jeder `GET /api/lead/:id` |
| 58 | `welcome_email_sent` | Registration handler |
| 59 | `last_reminder_sent` | Cron reminders |
| 60 | `reminder_count` | Cron reminders (0, 1, 2, ...) |
| 61 | `subscription_status` | Stripe webhook (`active`/`cancelled`) |
| 62 | `stripe_payment_date` | Stripe `checkout.session.completed` |
| 63 | `live_email_sent` | Cron DNS check |
| 64 | `selected_domain` | Order handler / Stripe webhook |
