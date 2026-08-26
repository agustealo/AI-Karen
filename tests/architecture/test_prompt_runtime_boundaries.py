"""
Architecture invariants for PromptRuntime.

Tests that PromptRuntime respects its architectural boundaries:
- Does not select providers
- Does not invoke models  
- Does not execute tools
- Does not persist memory
- Does not enforce RBAC itself
"""

import pytest
import ast
from pathlib import Path


class TestPromptRuntimeArchitectureInvariants:
    """Test that PromptRuntime respects architectural boundaries."""
    
    @pytest.fixture
    def prompt_runtime_dir(self) -> Path:
        """Path to the PromptRuntime directory."""
        return Path(__file__).parent.parent.parent.parent / "src" / "ai_karen_engine" / "core" / "runtime" / "prompt"
    
    @pytest.fixture
    def prompt_runtime_files(self, prompt_runtime_dir) -> list[Path]:
        """All Python files in PromptRuntime directory."""
        files = []
        if prompt_runtime_dir.exists():
            files = list(prompt_runtime_dir.glob("**/*.py"))
        return files
    
    def test_no_provider_selection(self, prompt_runtime_files):
        """PromptRuntime should not select providers."""
        forbidden_imports = [
            "provider",
            "Provider",
            "LLMProvider", 
            "ProviderRuntime",
            "ProviderRegistry",
            "select_provider",
            "choose_provider",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_imports:
                            if forbidden in alias.name:
                                pytest.fail(
                                    f"{file_path.name} contains forbidden import: {alias.name}. "
                                    "PromptRuntime should not import provider selection logic."
                                )
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        for forbidden in forbidden_imports:
                            if forbidden in alias.name:
                                pytest.fail(
                                    f"{file_path.name} contains forbidden import: {alias.name}. "
                                    "PromptRuntime should not import provider selection logic."
                                )
    
    def test_no_model_invocation(self, prompt_runtime_files):
        """PromptRuntime should not invoke models."""
        forbidden_patterns = [
            "generate(",
            "complete(",
            "chat(",
            "inference(",
            "invoke(",
            "model.generate",
            "model.complete",
            "model.chat",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_patterns:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains model invocation pattern: {pattern}. "
                        "PromptRuntime should not invoke models."
                    )
    
    def test_no_tool_execution(self, prompt_runtime_files):
        """PromptRuntime should not execute tools."""
        forbidden_patterns = [
            "execute_tool(",
            "tool.execute(",
            "run_tool(",
            "call_tool(",
            "tool.call(",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_patterns:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains tool execution pattern: {pattern}. "
                        "PromptRuntime should not execute tools."
                    )
    
    def test_no_memory_persistence(self, prompt_runtime_files):
        """PromptRuntime should not persist memory."""
        forbidden_patterns = [
            "memory.save(",
            "memory.persist(",
            "memory.write(",
            "memory.store(",
            "save_memory(",
            "persist_memory(",
            "write_memory(",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_patterns:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains memory persistence pattern: {pattern}. "
                        "PromptRuntime should not persist memory."
                    )
    
    def test_no_rbac_enforcement(self, prompt_runtime_files):
        """PromptRuntime should not enforce RBAC directly."""
        forbidden_patterns = [
            "check_permission(",
            "verify_access(",
            "enforce_role(",
            "has_permission(",
            "can_access(",
            "user.can(",
            "role.has(",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_patterns:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains RBAC enforcement pattern: {pattern}. "
                        "PromptRuntime should not enforce RBAC directly."
                    )
    
    def test_consumes_approved_inputs_only(self, prompt_runtime_files):
        """PromptRuntime should only consume approved inputs via its public interface."""
        prompt_assembler_path = next(
            (f for f in prompt_runtime_files if f.name == "prompt_assembler.py"),
            None
        )
        
        if not prompt_assembler_path:
            pytest.skip("prompt_assembler.py not found")
            return
        
        content = prompt_assembler_path.read_text()
        
        # Check that PromptAssembler.assemble() accepts PromptAssemblyRequest
        if "def assemble(self, request: PromptAssemblyRequest)" not in content:
            pytest.fail(
                "PromptAssembler.assemble() should accept PromptAssemblyRequest. "
                "This ensures only approved inputs are consumed."
            )
        
        # Check that it returns PromptAssemblyResult
        if "PromptAssemblyResult" not in content:
            pytest.fail(
                "PromptAssembler should return PromptAssemblyResult. "
                "This ensures output is properly typed."
            )
    
    def test_no_expression_gateway_wiring(self, prompt_runtime_files):
        """PromptRuntime should not wire ExpressionGateway."""
        forbidden_imports = [
            "ExpressionGateway",
            "expression_gateway",
            "from.*expression_gateway",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_imports:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains ExpressionGateway reference: {pattern}. "
                        "PromptRuntime should not wire ExpressionGateway directly."
                    )
    
    def test_no_chat_runtime_wiring(self, prompt_runtime_files):
        """PromptRuntime should not wire ChatRuntime."""
        forbidden_imports = [
            "ChatRuntime",
            "chat_runtime",
            "from.*chat_runtime",
        ]
        
        for file_path in prompt_runtime_files:
            content = file_path.read_text()
            for pattern in forbidden_imports:
                if pattern in content:
                    pytest.fail(
                        f"{file_path.name} contains ChatRuntime reference: {pattern}. "
                        "PromptRuntime should not wire ChatRuntime directly."
                    )
    
    def test_prompt_assembler_isolate_boundaries(self, prompt_runtime_files):
        """Test that PromptAssembler maintains clear isolation boundaries."""
        prompt_assembler_path = next(
            (f for f in prompt_runtime_files if f.name == "prompt_assembler.py"),
            None
        )
        
        if not prompt_assembler_path:
            pytest.skip("prompt_assembler.py not found")
            return
        
        content = prompt_assembler_path.read_text()
        
        # Check that class has clear docstring about boundaries
        if "does NOT:" not in content:
            pytest.fail(
                "PromptAssembler should have clear documentation about what it does NOT do. "
                "This helps maintain architectural boundaries."
            )
        
        # Check for boundary violations in the class
        boundary_violations = [
            "select.*provider",
            "invoke.*model",
            "execute.*tool", 
            "persist.*memory",
            "enforce.*rbac",
        ]
        
        for violation in boundary_violations:
            import re
            if re.search(violation, content, re.IGNORECASE):
                pytest.fail(
                    f"PromptAssembler contains potential boundary violation: {violation}"
                )