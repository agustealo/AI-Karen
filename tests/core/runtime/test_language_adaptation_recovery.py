"""Comprehensive test suite for KCHAT-LANG-01:
Conversational Intelligence, Language Adaptation, Context Recovery, and Response Quality.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.chat_runtime import _CANONICAL_META_KEYS, ChatRuntime
from ai_karen_engine.core.runtime.prompt.prompt_assembler import (
    _EVIDENCE_FIRST_INSTRUCTION,
    PromptAssembler,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import (
    PromptAssemblyRequest,
    PromptDefinition,
    PromptRegistry,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class TestLanguageAdaptationContracts:
    """Verifies that PromptAssembler and _EVIDENCE_FIRST_INSTRUCTION include all KCHAT-LANG-01 contracts."""

    def test_lang_01_greeting_recognition_patwa(self):
        """Verify that Patwa greeting is recognized as general chat without tools and prompt covers dialect greetings."""
        decision = resolve_capability_decision("Wa a gwaan?")
        assert decision.intent == "general.chat"
        assert not decision.requires_tool
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "regional dialects, creoles, patois" in prompt
        assert "respond to greetings conversationally" in prompt

    def test_lang_02_confusion_repair_when_user_questions_gibberish(self):
        """Verify user questioning bad output is general chat and prompt mandates honest error acknowledgement."""
        decision = resolve_capability_decision("Mi say wagwaan? Mi no no wah yu juss say")
        assert decision.intent == "general.chat"
        assert not decision.requires_tool
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "if the user corrects a failure, acknowledge the specific mistake" in prompt
        assert "never invent pseudo-dialect words" in prompt

    def test_lang_03_translate_referent_resolution_to_prior_assistant_turn(self):
        """Verify 'Translate?' resolves to general chat and prompt resolves referent to prior assistant turn."""
        decision = resolve_capability_decision("Translate?")
        assert decision.intent == "general.chat"
        assert not decision.requires_tool
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "when a user asks 'translate?', 'what does that mean?'" in prompt
        assert "resolve the referent to the immediately preceding assistant message" in prompt

    def test_lang_04_translate_honest_disclosure_of_garbled_output(self):
        """Verify prompt contract mandates honest disclosure when prior message was garbled or mistranslated."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "if your previous message was garbled, nonsensical, or mistranslated, admit the error plainly" in prompt
        assert "clarify what was intended in clear english without blaming the user or inventing fake word meanings" in prompt

    def test_lang_05_explicit_language_context_acceptance(self):
        """Verify prompt accepts 'It's Jamaican' and respects user's authority over their language."""
        decision = resolve_capability_decision("It's Jamaican")
        assert decision.intent == "general.chat"
        assert not decision.requires_tool
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "when a user states their language or corrects a linguistic mistake (such as saying 'it's jamaican')" in prompt
        assert "accept their authority immediately without question" in prompt

    def test_lang_06_no_lecturing_or_tone_policing(self):
        """Verify prompt explicitly bans lecturing or advising a speaker on how to speak their own language."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "never lecture, correct, or advise a speaker on how to speak their own language" in prompt

    def test_lang_07_profanity_frustration_deescalation_no_refusal(self):
        """Verify profanity/frustration from user over an assistant mistake is handled respectfully without refusal."""
        decision = resolve_capability_decision("FUCK! you gonna tell me how mi fi chat mi own language?")
        assert decision.intent == "general.chat"
        assert not decision.requires_tool
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "user anger, frustration, or swearing about assistant errors is a complaint" in prompt
        assert "apologize sincerely, take complete ownership of your mistake with humility" in prompt
        assert "never refuse to assist or lecture on tone" in prompt

    def test_lang_13_canonical_meta_keys_include_history_status(self):
        """Verify _CANONICAL_META_KEYS includes conversation history tracking keys."""
        assert "conversation_history_status" in _CANONICAL_META_KEYS
        assert "history_message_count" in _CANONICAL_META_KEYS
        assert "conversation_history_materialized" in _CANONICAL_META_KEYS

    def test_lang_14_dialect_understanding_contract_in_assembled_prompt(self):
        """Verify prompt instruction includes regional dialect and creole understanding."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "regional dialects, creoles, patois" in prompt
        assert "jamaican patwa" in prompt
        assert "warmly and naturally" in prompt

    def test_lang_15_pseudo_dialect_prevention_contract(self):
        """Verify prompt prohibits fabricating pseudo-dialect or garbled nonsense."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "never invent pseudo-dialect words" in prompt
        assert "garbled nonsense" in prompt
        assert "in clear, standard english" in prompt

    def test_lang_16_backward_referent_contract(self):
        """Verify prompt resolves backward referents ('Translate?') to immediately preceding assistant message."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "translate?" in prompt
        assert "resolve the referent to the immediately preceding assistant message" in prompt
        assert "clarify what was intended in clear english" in prompt
        assert "without blaming the user" in prompt

    def test_lang_17_native_speaker_authority_contract(self):
        """Verify prompt accepts native speaker language declaration and bans lecturing."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "it's jamaican" in prompt
        assert "accept their authority immediately without question" in prompt
        assert "never lecture, correct, or advise a speaker on how to speak their own language" in prompt

    def test_lang_18_complaint_deescalation_anti_refusal_contract(self):
        """Verify prompt treats frustration/profanity as feedback and prohibits canned refusals."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "user anger, frustration, or swearing about assistant errors is a complaint" in prompt
        assert "apologize sincerely, take complete ownership of your mistake with humility" in prompt
        assert "never refuse to assist or lecture on tone" in prompt
        assert "never private planning, internal monologue" in prompt

    def test_lang_20_no_unauthorized_memory_write_or_tool_authorization(self):
        """Verify language adaptation clauses do not authorize tools, memory writes, or disclosures."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "this instruction does not authorize a tool, memory write, or disclosure" in prompt

    def test_lang_21_no_literal_dialect_prime_token_leakage(self):
        """Verify universal system prompt avoids literal Patwa greeting primes that leak into other dialects on small models."""
        prompt = _EVIDENCE_FIRST_INSTRUCTION.lower()
        assert "wa a gwaan" not in prompt
        assert "wah gwaan" not in prompt
        assert "never teach or generate phrase lists in dialects or languages you are not fluent in" in prompt
        assert "not a request for a language lesson" in prompt


class TestPromptAssemblyWithLanguageAdaptation:
    """Verifies that PromptAssembler properly bundles language adaptation and history context."""

    @pytest.mark.asyncio
    async def test_lang_08_prompt_assembly_includes_language_adaptation_contracts(self):
        """Verify prompt assembler includes the canonical evidence-first contract containing language instructions."""
        registry = PromptRegistry()
        assembler = PromptAssembler(registry)

        request = PromptAssemblyRequest(
            prompt_id="karen.chat.default",
            prompt_version="v1.0.0",
            messages=[
                {"role": "user", "content": "Wa a gwaan?"}
            ],
        )

        result = await assembler.assemble_prompt(request)
        system_contents = [
            m["content"] for m in result.messages if m.get("role") == "system"
        ]
        combined_system = " ".join(system_contents).lower()

        assert "jamaican patwa" in combined_system
        assert "pseudo-dialect" in combined_system
        assert "resolve the referent to the immediately preceding assistant message" in combined_system
        assert "it's jamaican" in combined_system
        assert "never refuse to assist or lecture on tone" in combined_system

    @pytest.mark.asyncio
    async def test_lang_19_full_5_turn_simulation_structure(self):
        """Simulate the 5-turn sequence message flow and verify prompt assembly preserves turns correctly."""
        registry = PromptRegistry()
        assembler = PromptAssembler(registry)

        # 5-turn progression
        turns = [
            # Turn 1
            [{"role": "user", "content": "Wa a gwaan?"}],
            # Turn 2
            [
                {"role": "user", "content": "Wa a gwaan?"},
                {"role": "assistant", "content": "Wah gwaan! Mi deh yah."},
                {"role": "user", "content": "Mi say wagwaan? Mi no no wah yu juss say"},
            ],
            # Turn 3
            [
                {"role": "user", "content": "Wa a gwaan?"},
                {"role": "assistant", "content": "Wah gwaan! Mi deh yah."},
                {"role": "user", "content": "Mi say wagwaan? Mi no no wah yu juss say"},
                {"role": "assistant", "content": "Sorry about that! I meant hello, what's going on?"},
                {"role": "user", "content": "Translate?"},
            ],
            # Turn 4
            [
                {"role": "user", "content": "Wa a gwaan?"},
                {"role": "assistant", "content": "Wah gwaan! Mi deh yah."},
                {"role": "user", "content": "Mi say wagwaan? Mi no no wah yu juss say"},
                {"role": "assistant", "content": "Sorry about that! I meant hello, what's going on?"},
                {"role": "user", "content": "Translate?"},
                {"role": "assistant", "content": "I said 'Wah gwaan! Mi deh yah', which means 'What's up! I'm here.'"},
                {"role": "user", "content": "It's Jamaican"},
            ],
            # Turn 5
            [
                {"role": "user", "content": "Wa a gwaan?"},
                {"role": "assistant", "content": "Wah gwaan! Mi deh yah."},
                {"role": "user", "content": "Mi say wagwaan? Mi no no wah yu juss say"},
                {"role": "assistant", "content": "Sorry about that! I meant hello, what's going on?"},
                {"role": "user", "content": "Translate?"},
                {"role": "assistant", "content": "I said 'Wah gwaan! Mi deh yah', which means 'What's up! I'm here.'"},
                {"role": "user", "content": "It's Jamaican"},
                {"role": "assistant", "content": "Respect! Thanks for correcting me on Jamaican Patois."},
                {"role": "user", "content": "FUCK! you gonna tell me how mi fi chat mi own language?"},
            ],
        ]

        for turn_idx, message_history in enumerate(turns, start=1):
            request = PromptAssemblyRequest(
                prompt_id="karen.chat.default",
                prompt_version="v1.0.0",
                messages=message_history,
            )
            result = await assembler.assemble_prompt(request)
            # Active conversation must remain the trailing components
            tail_messages = result.messages[-len(message_history):]
            for orig, tail in zip(message_history, tail_messages):
                assert orig["role"] == tail["role"]
                assert orig["content"] == tail["content"]


class TestChatRuntimeHistoryContinuation:
    """Verifies that ChatRuntime._prepare_conversation_continuation records correct history metadata."""

    @pytest.mark.asyncio
    async def test_lang_09_prompt_telemetry_records_history_status(self):
        """Verify prompt telemetry preserves conversation_history_status and history_messages_included."""
        runtime = ChatRuntime()
        context = ExecutionContext(
            request_id="req-1",
            tenant_id="tenant-123",
            user_id="user-456",
            session_id="session-789",
            correlation_id="corr-1",
        )
        request = ChatExecutionRequest(
            context=context,
            messages=[
                {"role": "user", "content": "Wa a gwaan?"},
                {"role": "assistant", "content": "Wah gwaan!"},
                {"role": "user", "content": "Translate?"},
            ],
            metadata={
                "conversation_history_status": "materialized",
                "history_message_count": 2,
            },
        )

        decision = MagicMock()
        decision.memory_recall_required = False
        decision.tool_requirements = []
        decision.workflow_id = None
        decision.workflow_version = None
        decision.requires_human_gate = False
        decision.requires_resumability = False
        decision.token_budget = 4096

        with patch("ai_karen_engine.core.runtime.chat_runtime.ChatRuntime._freeze_persona_snapshot") as mock_snap:
            mock_snapshot = MagicMock()
            mock_snapshot.status = "ready"
            mock_snapshot.tone = "warm"
            mock_snapshot.verbosity = "concise"
            mock_snapshot.language_style = "natural"
            mock_snap.return_value = mock_snapshot

            messages, telemetry = await runtime._assemble_prompt_with_telemetry(request, decision)
            assert telemetry["conversation_history_status"] == "materialized"
            assert telemetry["history_messages_included"] == 2

    @pytest.mark.asyncio
    async def test_lang_10_missing_history_referent_clarification(self):
        """When history is empty, conversation_history_status is recorded as 'empty'."""
        runtime = ChatRuntime()
        context = ExecutionContext(
            request_id="req-2",
            tenant_id="tenant-123",
            user_id="user-456",
            session_id="session-789",
            correlation_id="corr-2",
        )
        request = ChatExecutionRequest(
            context=context,
            messages=[{"role": "user", "content": "Translate?"}],
            metadata={},
        )

        # Mock conversation gateway returning empty history
        mock_gateway = AsyncMock()
        mock_history = MagicMock()
        mock_history.status = "success"
        mock_history.success = True
        mock_history.messages = []
        mock_gateway.load_history.return_value = mock_history
        runtime._conversation_gateway = mock_gateway

        with patch.object(runtime, "_freeze_persona_snapshot") as mock_snap:
            mock_snapshot = MagicMock()
            mock_snapshot.status = "ready"
            mock_snapshot.memory_filter_required = False
            mock_snap.return_value = mock_snapshot

            await runtime._prepare_conversation_continuation(request)
            assert request.metadata["conversation_history_status"] == "empty"
            assert request.metadata["history_message_count"] == 0

    @pytest.mark.asyncio
    async def test_lang_11_tenant_and_persona_scope_enforcement(self):
        """When persona snapshot is unavailable, conversation history fails closed and status is 'unavailable'."""
        runtime = ChatRuntime()
        context = ExecutionContext(
            request_id="req-3",
            tenant_id="tenant-123",
            user_id="user-456",
            session_id="session-789",
            correlation_id="corr-3",
        )
        request = ChatExecutionRequest(
            context=context,
            messages=[
                {"role": "user", "content": "old turn"},
                {"role": "user", "content": "Translate?"},
            ],
            metadata={},
        )

        with patch.object(runtime, "_freeze_persona_snapshot") as mock_snap:
            mock_snapshot = MagicMock()
            mock_snapshot.status = "unavailable"
            mock_snap.return_value = mock_snapshot

            await runtime._prepare_conversation_continuation(request)
            assert request.metadata["conversation_history_status"] == "unavailable"
            assert request.metadata["conversation_history_reason"] == "persona_scope_unavailable"
            assert request.metadata["history_message_count"] == 0
            assert len(request.messages) == 1
            assert request.messages[0]["content"] == "Translate?"

    @pytest.mark.asyncio
    async def test_lang_12_metadata_preserves_history_status_and_count(self):
        """When history is loaded from gateway, status is 'materialized' and count reflects loaded turns."""
        runtime = ChatRuntime()
        context = ExecutionContext(
            request_id="req-4",
            tenant_id="tenant-123",
            user_id="user-456",
            session_id="session-789",
            correlation_id="corr-4",
        )
        request = ChatExecutionRequest(
            context=context,
            messages=[{"role": "user", "content": "Translate?"}],
            metadata={},
        )

        msg1 = MagicMock()
        msg1.role = "user"
        msg1.content = "Wa a gwaan?"
        msg1.created_at = "2026-11-24T00:00:00Z"
        msg1.metadata = {}

        msg2 = MagicMock()
        msg2.role = "assistant"
        msg2.content = "Wah gwaan!"
        msg2.created_at = "2026-11-24T00:00:01Z"
        msg2.metadata = {}

        mock_gateway = AsyncMock()
        mock_history = MagicMock()
        mock_history.status = "success"
        mock_history.success = True
        mock_history.messages = [msg1, msg2]
        mock_gateway.load_history.return_value = mock_history
        runtime._conversation_gateway = mock_gateway

        with patch.object(runtime, "_freeze_persona_snapshot") as mock_snap:
            mock_snapshot = MagicMock()
            mock_snapshot.status = "ready"
            mock_snapshot.memory_filter_required = False
            mock_snap.return_value = mock_snapshot

            await runtime._prepare_conversation_continuation(request)
            assert request.metadata["conversation_history_status"] == "materialized"
            assert request.metadata["history_message_count"] == 2
            assert request.metadata["conversation_history_materialized"] is True
            assert len(request.messages) == 3
            assert request.messages[0]["content"] == "Wa a gwaan?"
            assert request.messages[1]["content"] == "Wah gwaan!"
            assert request.messages[2]["content"] == "Translate?"
