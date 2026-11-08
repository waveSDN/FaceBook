# WIS Intelligent Sales Agent — MVP

A small, local-first MVP for one WIS page and Facebook Messenger. The repository had no application code, dependency manifest, existing data model, configuration, or integration credentials. This implementation uses Python 3.11+ and the Python standard library, including SQLite; it adds no Redis, queue, external service, or third-party dependency.

## Run locally

1. Install Python 3.11 or newer.
2. Use `.env.example` as a list of supported settings. Python does not load `.env` files; set selected environment variables through your local secret manager or shell.
3. Run `python app.py` and open `http://127.0.0.1:3000`.
4. Run checks with `python -m unittest discover -s tests -v`.

The server binds to loopback by default. Do not expose it directly to the internet. A non-loopback `HOST` requires a `WIS_ADMIN_TOKEN` of at least 32 characters, but production use also requires managed secrets, HTTPS, durable access controls, retention/privacy policy, monitoring, and deployment review; those are outside this MVP.

## MVP behavior

- **Page and dashboard:** local demo composer, Messenger conversation/customer history, opportunity evidence, human escalation, and a reviewed WIS service catalog.
- **Gemini:** when both `GEMINI_API_KEY` and `GEMINI_MODEL` are configured, Gemini classifies intent and selects a constrained reply strategy. The backend validates exact Structured Output fields and catalog references. Qualification, consent, escalation, service-window checks, and message sending remain backend decisions. There is no model-generated free-text claim about WIS offers.
- **WIS catalog:** starts empty. Operators may enter only reviewed facts in the dashboard. The customer-facing answer reproduces the approved answer text verbatim and adds at most one fixed clarification question. If a matching approved entry does not exist, the agent says it lacks confirmed information.
- **Qualification:** deterministic, evidence-bearing MVP rule: explicit interest (40 points), stated timing (30), and a named business process/goal (30). Merely identifying as a company does not count as a need. Only all three qualify; qualification does not itself trigger handoff or WhatsApp.
- **Human handoff:** complaints and direct requests for a person are escalated separately. Operators can always record a manual handoff and reason.
- **WhatsApp:** the operator may request consent for a qualified lead. The agent sends a clear Messenger consent question only while Messenger is configured and inside the 24-hour service window. The backend records consent only when a later customer message is an unambiguous affirmative. A link is not sent until that consent is recorded. WhatsApp Business API messaging is not implemented.
- **Messenger:** webhook verification and inbound POSTs require `X-Hub-Signature-256` HMAC-SHA256 validation before JSON parsing or processing. Meta message IDs are required and deduplicated. Ordinary outbound replies require all Messenger credentials, successful Gemini classification, and an open 24-hour service window. Human escalations use a fixed, non-offer reply and are placed in the dashboard's human-review list. No proactive messaging or templates are implemented.
- **Local demo:** uses safe deterministic message previews without Gemini or external delivery. Never use real customer data for demo testing.
- **Persistence:** SQLite stores customers, conversations, messages, opportunities/evidence, and approved catalog entries. The database is local and unencrypted; protect and delete it according to WIS policy.

## Messenger configuration

Set `MESSENGER_VERIFY_TOKEN`, `META_APP_SECRET`, `META_PAGE_ACCESS_TOKEN`, `META_PAGE_ID`, and `META_GRAPH_API_VERSION`. Configure the app's webhook callback to `/webhooks/messenger` and subscribe to page messaging events. Add `GEMINI_API_KEY` and `GEMINI_MODEL` to enable intent classification. Set `WIS_WHATSAPP_NUMBER` only if WIS wants the explicit-consent handoff link. Status labels indicate presence of configuration, not successful external connectivity. Test with a WIS test page/account after approval; none is configured in this repository.

## Scope and known gaps

No deployment, customer data, messaging account, real credentials, automatic CRM sync, WhatsApp Business API, notifications, follow-up scheduler, multi-tenant controls, encryption-at-rest, retention automation, or audited administrator identity is included. This is a local MVP for controlled testing, not a production-ready public service.
