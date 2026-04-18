# WhatsApp Outreach Skill

Generate personalized WhatsApp messages with clickable wa.me deep links for Swiss business lead outreach.

## When to Use

- **Day 0**: First contact — send 4 website draft links to a new lead
- **Post-call**: After a phone call — "wie besprochen" with links
- **Follow-up**: Day 7 reminder for leads who haven't responded

## How It Works

1. Takes lead data (phone, business name, owner name, 4 draft URLs)
2. Generates a personalized German WhatsApp message
3. Creates a `wa.me` deep link with pre-filled message
4. User clicks the link → WhatsApp opens → tap Send

No API keys or Meta verification needed. Works immediately.

## Usage

```bash
# Single lead
python3 send_whatsapp.py \
    --phone "+41 44 123 45 67" \
    --business-name "Coiffeur Züri" \
    --owner-name "Hans Müller" \
    --url-1 "https://coiffeur-zueri-earlydog.pages.dev" \
    --url-2 "https://coiffeur-zueri-bia.pages.dev" \
    --url-3 "https://coiffeur-zueri-liveblocks.pages.dev" \
    --url-4 "https://coiffeur-zueri-loveseen.pages.dev" \
    --sender-name "Louise" \
    --variant day0
```

## Message Variants

- `day0` — Cold first contact, introduces meine-kmu.ch, 4 links
- `post_call` — After phone conversation, "wie besprochen", 4 links
- `followup` — Gentle reminder after 7 days, 4 links

## Integration

The pipeline manager calls `generate_for_lead()` and `batch_generate()` directly.
The `format_swiss_phone()` function handles all Swiss phone formats (+41, 044, 0041).

## Future: Twilio API

When volume justifies it, add `--mode twilio` for fully automated sending via Twilio WhatsApp Business API. Requires Meta business verification and pre-approved templates.
