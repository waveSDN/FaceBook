import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from app import (
    Agent,
    AppServer,
    Config,
    Store,
    explicit_affirmative,
    lead_score,
    match_catalog,
    reply_for,
    valid_signature,
)


class AgentScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        self.store = Store(Path(self.temp_dir.name) / "test.sqlite3", root / "schema.sql")
        self.config = Config()
        self.agent = Agent(self.store, self.config)

    def send_demo(self, message):
        return self.agent.process_inbound("demo", "test-customer", message, demo=True)

    def test_customer_asks_what_wis_offers_without_configured_catalog(self):
        result = self.send_demo("What does WIS offer?")
        self.assertIn("don’t have confirmed WIS service information", result["reply"])
        self.assertNotIn("$", result["reply"])
        self.assertEqual(self.store.catalog(), [])
        self.assertEqual(result["deliveryStatus"], "draft")

    def test_customer_requests_customer_service_automation_uses_only_approved_catalog(self):
        answer = "WIS provides customer-service automation for business teams."
        self.store.save_catalog([{
            "id": "customer-service-automation",
            "topic": "Customer-service automation",
            "language": "en",
            "keywords": ["customer service automation", "automate customer service"],
            "answer": answer,
        }])
        result = self.send_demo("Our company wants customer service automation.")
        self.assertIn(answer, result["reply"])
        self.assertEqual(result["reply"].count("?"), 1)
        self.assertFalse(self.store.dashboard()["conversations"][0]["lead"]["qualified"])

    def test_interested_customer_is_not_qualified_without_explicit_need_and_timing(self):
        result = self.send_demo("I am interested but I do not know which solution fits.")
        dashboard = self.store.dashboard()
        lead = dashboard["conversations"][0]["lead"]
        self.assertEqual(lead["status"], "interested")
        self.assertFalse(lead["qualified"])
        self.assertEqual(lead["score"], 40)
        self.assertIn("What task or challenge", result["reply"])

    def test_explicit_human_request_escalates_without_qualifying_the_lead(self):
        result = self.send_demo("Please connect me with a human.")
        conversation = self.store.dashboard()["conversations"][0]
        self.assertEqual(conversation["status"], "needs_human")
        self.assertFalse(conversation["lead"]["qualified"])
        self.assertEqual(conversation["handoffReason"], "human_requested_or_complex")
        self.assertIn("refer your conversation", result["reply"])

    def test_whatsapp_handoff_requires_qualification_prompt_then_explicit_customer_consent(self):
        config = Config(
            host="127.0.0.1",
            messenger_verify_token="verify",
            meta_app_secret="secret",
            meta_page_access_token="page-token",
            meta_page_id="page-id",
            graph_api_version="v99.0",
            whatsapp_number="12345678901",
        )
        agent = Agent(self.store, config)
        qualified_messages = [
            "Our company is interested in a quote for customer service automation.",
            "We want to start next month.",
        ]
        for index, message in enumerate(qualified_messages, start=1):
            agent.process_inbound(
                "messenger", "qualified-customer", message, f"qualified-mid-{index}",
                timestamp=1_800_000_000_000 + index,
            )
        conversation = next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "qualified-customer"
        )
        self.assertTrue(conversation["lead"]["qualified"])

        with patch.object(agent, "send_messenger") as send:
            result = agent.request_whatsapp_consent(conversation["id"])
            self.assertEqual(result, {"consent": "pending"})
            response = agent.process_inbound(
                "messenger", "qualified-customer", "Yes", "qualified-mid-3",
                timestamp=1_800_000_000_100,
            )
        self.assertTrue(response["consentGranted"])
        self.assertEqual(response["processingStatus"], "whatsapp_handoff_sent")
        self.assertEqual(send.call_count, 2)
        updated = next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "qualified-customer"
        )
        self.assertEqual(updated["status"], "transferred")
        self.assertEqual(updated["whatsappConsent"], "granted")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT whatsapp_consent_message_id FROM conversations WHERE id=?",
                (conversation["id"],),
            ).fetchone()
        self.assertTrue(row["whatsapp_consent_message_id"])
        self.assertTrue(explicit_affirmative("نعم،"))
        self.assertTrue(explicit_affirmative("Yes, please."))
        self.assertFalse(explicit_affirmative("Please."))
        self.assertFalse(explicit_affirmative("Yes, but not now"))

    def test_whatsapp_consent_is_not_inferred_without_prompt_and_explicit_yes(self):
        config = Config(
            host="127.0.0.1",
            messenger_verify_token="verify",
            meta_app_secret="secret",
            meta_page_access_token="page-token",
            meta_page_id="page-id",
            graph_api_version="v99.0",
            whatsapp_number="12345678901",
        )
        agent = Agent(self.store, config)
        agent.process_inbound(
            "messenger", "maybe-customer",
            "Our company is interested in a quote for customer service automation.", "maybe-1",
        )
        agent.process_inbound("messenger", "maybe-customer", "We want to start next month.", "maybe-2")
        conversation = next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "maybe-customer"
        )
        with patch.object(agent, "send_messenger"):
            agent.request_whatsapp_consent(conversation["id"])
        response = agent.process_inbound("messenger", "maybe-customer", "Yes, but not now.", "maybe-3")
        self.assertNotIn("consentGranted", response)
        self.assertEqual(next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "maybe-customer"
        )["whatsappConsent"], "pending")
        denied = agent.process_inbound("messenger", "maybe-customer", "No, thanks.", "maybe-4")
        self.assertTrue(denied["consentDeclined"])
        self.assertEqual(next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "maybe-customer"
        )["whatsappConsent"], "declined")

    def test_whatsapp_consent_prompt_is_blocked_after_messenger_service_window(self):
        config = Config(
            host="127.0.0.1",
            messenger_verify_token="verify",
            meta_app_secret="secret",
            meta_page_access_token="page-token",
            meta_page_id="page-id",
            graph_api_version="v99.0",
            whatsapp_number="12345678901",
        )
        agent = Agent(self.store, config)
        old_timestamp = (time.time() - 25 * 60 * 60) * 1000
        agent.process_inbound(
            "messenger", "old-customer",
            "Our company is interested in a quote for customer service automation.",
            "old-1", old_timestamp,
        )
        agent.process_inbound(
            "messenger", "old-customer", "We want to start next month.",
            "old-2", old_timestamp + 1,
        )
        conversation = next(
            item for item in self.store.dashboard()["conversations"]
            if item["customerId"] == "old-customer"
        )
        self.assertTrue(conversation["lead"]["qualified"])
        with patch.object(agent, "send_messenger") as send:
            with self.assertRaisesRegex(RuntimeError, "MESSENGER_WINDOW_CLOSED"):
                agent.request_whatsapp_consent(conversation["id"])
        send.assert_not_called()

    def test_duplicate_webhook_message_id_is_not_processed_twice(self):
        first = self.agent.process_inbound("messenger", "user-1", "Hello", "meta-mid")
        duplicate = self.agent.process_inbound("messenger", "user-1", "Hello", "meta-mid")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(self.store.dashboard()["conversations"][0]["messages"]), 1)

    def test_strict_model_output_rejects_unverified_catalog_claims(self):
        malicious_classifier = lambda *_: {
            "intent": "offer_question",
            "reply_type": "answer_catalog",
            "knowledge_entry_id": "invented",
        }
        agent = Agent(self.store, self.config, classifier=malicious_classifier)
        result = agent.process_inbound("messenger", "user-2", "What services do you offer?", "user-2-mid")
        self.assertEqual(result["processingStatus"], "GEMINI_INVALID_OUTPUT")
        self.assertNotIn("reply", result)


class PolicyHelperTests(unittest.TestCase):
    def test_qualification_requires_all_three_explicit_user_evidence_types(self):
        result = lead_score([
            "Our company is interested in a quote for customer service automation.",
            "We want to start next month.",
        ])
        self.assertTrue(result["qualified"])
        self.assertEqual(result["score"], 100)
        incomplete = lead_score([
            "Our company is interested in a quote.",
            "We want to start next month.",
        ])
        self.assertFalse(incomplete["qualified"])
        self.assertIsNone(incomplete["evidence"]["business_need"])

    def test_catalog_match_and_safe_fallback(self):
        entries = [{
            "id": "known",
            "topic": "Known service",
            "language": "en",
            "keywords": ["known service"],
            "answer": "WIS approved answer.",
        }]
        self.assertEqual(match_catalog("Tell me about known service", "en", entries)["id"], "known")
        self.assertIsNone(match_catalog("Tell me about another service", "en", entries))
        fallback = reply_for("en", "offer_question", None)
        self.assertIn("don’t have confirmed WIS service information", fallback)
        self.assertNotIn("Another service", fallback)

    def test_messenger_webhook_signature_is_verified_before_processing(self):
        raw = b'{"object":"page"}'
        signature = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
        self.assertTrue(valid_signature(raw, signature, "app-secret"))
        self.assertFalse(valid_signature(raw + b" ", signature, "app-secret"))
        self.assertFalse(valid_signature(raw, signature, ""))
        self.assertFalse(valid_signature(raw, "sha256=bad", "app-secret"))

    def test_remote_binding_requires_a_long_dashboard_token(self):
        with self.assertRaisesRegex(ValueError, "at least 32 characters"):
            Config.from_env({"HOST": "0.0.0.0"})
        with self.assertRaisesRegex(ValueError, "at least 32 characters"):
            Config.from_env({"HOST": "0.0.0.0", "WIS_ADMIN_TOKEN": "short"})
        config = Config.from_env({"HOST": "0.0.0.0", "WIS_ADMIN_TOKEN": "a" * 32})
        self.assertEqual(config.host, "0.0.0.0")


class MessengerWebhookTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        self.store = Store(Path(self.temp_dir.name) / "webhook.sqlite3", root / "schema.sql")
        self.config = Config(host="127.0.0.1", meta_app_secret="test-app-secret", messenger_verify_token="verify-token")
        self.server = AppServer(
            ("127.0.0.1", 0), self.config, self.store,
            Agent(self.store, self.config, lambda *_: {
                "intent": "other", "reply_type": "ask_need", "knowledge_entry_id": None,
            }),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def post_webhook(self, raw, signature):
        request = Request(
            f"{self.base_url}/webhooks/messenger",
            data=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def signature(self, raw):
        return "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()

    def test_dashboard_and_health_endpoints_work_without_external_credentials(self):
        with urlopen(self.base_url, timeout=3) as response:
            page = response.read().decode()
        self.assertIn("WIS | وكيل المبيعات الذكي", page)
        with urlopen(f"{self.base_url}/api/health", timeout=3) as response:
            health = json.loads(response.read())
        self.assertEqual(health["integrations"]["messenger"], "not_configured")
        with urlopen(f"{self.base_url}/api/dashboard", timeout=3) as response:
            dashboard = json.loads(response.read())
        self.assertEqual(dashboard["metrics"]["conversations"], 0)
        self.assertEqual(dashboard["catalog"], [])

    def test_messenger_webhook_challenge_verification(self):
        with urlopen(
            f"{self.base_url}/webhooks/messenger?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=challenge-123",
            timeout=3,
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read().decode(), "challenge-123")
        try:
            urlopen(
                f"{self.base_url}/webhooks/messenger?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=x",
                timeout=3,
            )
        except HTTPError as exc:
            with exc:
                self.assertEqual(exc.code, 403)
        else:
            self.fail("Invalid webhook verification token was accepted.")

    def test_webhook_rejects_bad_signature_before_processing_and_deduplicates_valid_event(self):
        raw = json.dumps({
            "object": "page",
            "entry": [{"messaging": [{
                "sender": {"id": "test-sender"}, "timestamp": 1_800_000_000_000,
                "message": {"mid": "test-mid-1", "text": "Hello"},
            }]}],
        }).encode()
        status, _ = self.post_webhook(raw, "sha256=" + "0" * 64)
        self.assertEqual(status, 401)
        self.assertEqual(self.store.dashboard()["metrics"]["inboundMessages"], 0)

        status, result = self.post_webhook(raw, self.signature(raw))
        self.assertEqual(status, 200)
        self.assertEqual(result["accepted"], 1)
        status, result = self.post_webhook(raw, self.signature(raw))
        self.assertEqual(status, 200)
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(self.store.dashboard()["metrics"]["inboundMessages"], 1)

    def test_malformed_webhook_is_rejected_without_processing_any_event(self):
        raw = json.dumps({
            "object": "page",
            "entry": [
                {"messaging": [{"sender": {"id": "valid"}, "message": {"text": "hello"}}]},
                {"messaging": [{"sender": {"id": "bad"}, "message": {"text": "x" * 4001}}]},
            ],
        }).encode()
        status, _ = self.post_webhook(raw, self.signature(raw))
        self.assertEqual(status, 400)
        self.assertEqual(self.store.dashboard()["metrics"]["inboundMessages"], 0)


if __name__ == "__main__":
    unittest.main()
