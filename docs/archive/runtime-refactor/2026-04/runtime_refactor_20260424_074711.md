# Runtime Authority Refactor Report

Mode: audit
Root: /mnt/Development/KIRO/AI-Karen
Timestamp: 20260424_074711

## Legacy llama.cpp References

/mnt/Development/KIRO/AI-Karen/.kilo/2025-12-21_intelligent-fallback-system/implementation-plan.md:288:    "llamacpp": 2,
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/extension_manifest.json:2:  "id": "kari.llamacpp_integration",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/extension_manifest.json:6:  "description": "Integrates KAREN with the local llama.cpp server for high-performance local inference.",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/extension_manifest.json:20:        "description": "URL of the llama.cpp server"
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:9:  "id": "kari.llamacpp_integration",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:13:  "description": "Integrates KAREN with the local llama.cpp server for high-performance local inference.",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:27:        "description": "URL of the llama.cpp server"
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:122:- **server_url**: URL of the llama.cpp server
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:185:1. **Local Server Unavailable**: When the llama.cpp server is not reachable
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:205:   src/extensions/llamacpp/
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/EXTENSION_MANIFEST.md:247:3. Test the extension with the llama.cpp server
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/handler.py:2:KAREN extension handler for llama.cpp integration
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/handler.py:13:    """KAREN extension for llama.cpp integration"""
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/handler.py:35:        """Check if the llama.cpp server is healthy"""
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/handler.py:46:            logger.error(f"Failed to check llama.cpp server health: {e}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/prompt.txt:3:When using local models through the llama.cpp integration, please:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/PROMPT_TEMPLATE.md:10:When using local models through the llama.cpp integration, please:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/extensions_backup_20251126-052112/llamacpp/PROMPT_TEMPLATE.md:248:The prompt template is designed to work seamlessly with the llama.cpp server:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:16:    from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:43:log = logging.getLogger("llamacpp_inprocess")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:46:REQ_COUNT = Counter("llamacpp_requests_total", "Total LlamaCpp LLM Calls", ["model", "method"]) if METRICS_ENABLED else Counter()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:47:REQ_LATENCY = Histogram("llamacpp_latency_seconds", "LlamaCpp LLM Latency", ["model", "method"]) if METRICS_ENABLED else Histogram()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:48:ERR_COUNT = Counter("llamacpp_errors_total", "LlamaCpp LLM Errors", ["error_type", "method"]) if METRICS_ENABLED else Counter()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:49:IN_FLIGHT = Gauge("llamacpp_inflight_requests", "In-Process LLM Calls In Flight", ["method"]) if METRICS_ENABLED else Gauge()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:82:            log.error(f"[llamacpp_inprocess] Model not found: {path}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:93:            log.info(f"[llamacpp_inprocess] Model loaded: {self.model_name}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:103:        log.info(f"[llamacpp_inprocess] Switched to model: {model_name}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:180:            log.error(f"[llamacpp_inprocess] Model discovery failed: {str(e)}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:216:        log.info(f"[llamacpp_inprocess] Downloading TinyLlama GGUF model from {TINY_LLAMA_URL} ...")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:220:            log.info(f"[llamacpp_inprocess] Downloaded: {target}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:222:            log.error(f"[llamacpp_inprocess] Failed to download TinyLlama: {e}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:230:llamacpp_inprocess_client = LlamaCppEngine()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_client.py:234:    return llamacpp_inprocess_client.health_check()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:13:from ai_karen_engine.plugins.llm_services.llama.llama_client import llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:17:    prefix="/llm/llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:21:log = logging.getLogger("llamacpp_plugin")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:32:        models = llamacpp_inprocess_client.list_models()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:49:        llamacpp_inprocess_client.switch_model(model_name, ctx_size, n_threads)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:50:        return {"status": "ok", "active_model": llamacpp_inprocess_client.model_name}
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:62:        status = llamacpp_inprocess_client.health_check()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:77:        result = llamacpp_inprocess_client.embedding(text)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:97:                for chunk in llamacpp_inprocess_client.chat(messages, stream=True, max_tokens=max_tokens):
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:101:            response = llamacpp_inprocess_client.chat(messages, stream=False, max_tokens=max_tokens)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:126:                async for chunk in llamacpp_inprocess_client.achat(messages, stream=True, max_tokens=max_tokens):
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/llama_plugin.py:133:            response = await llamacpp_inprocess_client.achat(messages, stream=False, max_tokens=max_tokens)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm-services/llama/plugin_manifest.json:10:  "provider_id": "llama_cpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:17:    from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:44:log = logging.getLogger("llamacpp_inprocess")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:47:REQ_COUNT = Counter("llamacpp_requests_total", "Total LlamaCpp LLM Calls", ["model", "method"]) if METRICS_ENABLED else Counter()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:48:REQ_LATENCY = Histogram("llamacpp_latency_seconds", "LlamaCpp LLM Latency", ["model", "method"]) if METRICS_ENABLED else Histogram()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:49:ERR_COUNT = Counter("llamacpp_errors_total", "LlamaCpp LLM Errors", ["error_type", "method"]) if METRICS_ENABLED else Counter()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:50:IN_FLIGHT = Gauge("llamacpp_inflight_requests", "In-Process LLM Calls In Flight", ["method"]) if METRICS_ENABLED else Gauge()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:83:            log.error(f"[llamacpp_inprocess] Model not found: {path}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:94:            log.info(f"[llamacpp_inprocess] Model loaded: {self.model_name}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:104:        log.info(f"[llamacpp_inprocess] Switched to model: {model_name}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:181:            log.error(f"[llamacpp_inprocess] Model discovery failed: {str(e)}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:216:        log.info(f"[llamacpp_inprocess] Downloading TinyLlama GGUF model from {TINY_LLAMA_URL} ...")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:220:            log.info(f"[llamacpp_inprocess] Downloaded: {target}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:222:            log.error(f"[llamacpp_inprocess] Failed to download TinyLlama: {e}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:230:llamacpp_inprocess_client = LlamaCppEngine()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_client.py:234:    return llamacpp_inprocess_client.health_check()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:14:from ai_karen_engine.plugins.llm_services.llama.llama_client import llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:17:    prefix="/llm/llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:21:log = logging.getLogger("llamacpp_plugin")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:29:        models = llamacpp_inprocess_client.list_models()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:46:        llamacpp_inprocess_client.switch_model(model_name, ctx_size, n_threads)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:47:        return {"status": "ok", "active_model": llamacpp_inprocess_client.model_name}
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:59:        status = llamacpp_inprocess_client.health_check()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:74:        result = llamacpp_inprocess_client.embedding(text)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:93:                for chunk in llamacpp_inprocess_client.chat(messages, stream=True, max_tokens=max_tokens):
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:97:            response = llamacpp_inprocess_client.chat(messages, stream=False, max_tokens=max_tokens)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:118:                async for chunk in llamacpp_inprocess_client.achat(messages, stream=True, max_tokens=max_tokens):
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/llama_plugin.py:124:            response = await llamacpp_inprocess_client.achat(messages, stream=False, max_tokens=max_tokens)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/plugins_backup_20251126-052112/ai/llm_services/llama/plugin_manifest.json:10:  "provider_id": "llama_cpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_connection_manager.py:334:            if connection.provider in ["local", "llamacpp"]:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_discovery_engine.py:395:            models.extend(await self._scan_llama_cpp_models(directory))
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_discovery_engine.py:433:    async def _scan_llama_cpp_models(self, directory: Path) -> List[ModelInfo]:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_discovery_engine.py:1238:                return await self._validate_llama_cpp_model(path)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_discovery_engine.py:1251:    async def _validate_llama_cpp_model(self, path: Path) -> ModelStatus:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/provider_health_monitor.py:58:            "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/provider_registry.py:100:            primary="llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/provider_registry.py:107:            primary="llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/provider_registry.py:114:            primary="llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:89:            ModelType.LLAMA_CPP: self._check_llama_cpp_dependencies,
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:386:            issues.extend(await self._validate_basic_llama_cpp(path))
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:394:    async def _validate_basic_llama_cpp(self, path: Path) -> List[ValidationIssue]:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:512:    async def _check_llama_cpp_dependencies(self) -> List[ValidationIssue]:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:518:            import llama_cpp
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:520:            if hasattr(llama_cpp, '__version__'):
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/model_validation_system.py:521:                logger.debug(f"llama-cpp-python version: {llama_cpp.__version__}")
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/orchestration_agent.py:85:            "llamacpp",      # Llama-CPP (DL models with huggingface)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/orchestration_agent.py:95:            "provider": "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/orchestration_agent.py:333:                "llama-cpp": "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/orchestration_agent.py:334:                "llama_cpp": "llamacpp", 
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:43:llamacpp_inprocess_client = None
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:46:def _get_llamacpp_client():
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:48:    global llamacpp_inprocess_client, LLAMACPP_AVAILABLE
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:51:        return llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:62:            llamacpp_inprocess_client = module.llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:64:            return llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/smalllanguagmodel.py:143:            client = _get_llamacpp_client()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:50:llamacpp_inprocess_client = None
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:53:def _get_llamacpp_client():
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:55:    global llamacpp_inprocess_client, LLAMACPP_AVAILABLE
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:58:        return llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:69:            llamacpp_inprocess_client = module.llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:71:            return llamacpp_inprocess_client
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/small_language_model_service.py:245:                client = _get_llamacpp_client()
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/system_model_manager.py:312:                return self._validate_llama_cpp_config(config)
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/system_model_manager.py:323:    def _validate_llama_cpp_config(self, config: LlamaCppConfig) -> Dict[str, Any]:
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/user_service.py:523:                    "preferredLLMProvider", "llamacpp"
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/user_service.py:707:            "preferredLLMProvider": "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/user_service.py:722:            "preferredLLMProvider": "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/intelligent_model_router.py:205:            ModelType.LLAMA_CPP: "llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/intelligent_model_router.py:275:            if connection.provider == "local" or connection.provider == "llamacpp":
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_optimization.py:22:    LOCAL = "local"           # llama.cpp, Transformers
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_optimization.py:124:        # This would interface with llama.cpp, Transformers, or other local providers
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_optimization.py:309:                name="llamacpp:tinyllama-1.1b-chat-v2.0.Q4_K_M.gguf",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_optimization.py:310:                provider="llamacpp",
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_router.py:103:    LOCAL = 1  # llama.cpp, GGUF runtimes
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_router.py:221:            "llamacpp": ProviderPriority.LOCAL,
/mnt/Development/KIRO/AI-Karen/.kilo/backups/services_migration/llm_router.py:222:            "llama_cpp": ProviderPriority.LOCAL,
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:54:- `llama_cpp_provider.py` vs `llamacpp_provider.py`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:216:list_llama_cpp_models(models_dir=None) -> List[str]
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:439:- `llama_cpp_provider.py` vs `llamacpp_provider.py`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:442:1. **Keep** `llamacpp_provider.py` (underscores)
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:446:2. **Remove** `llama_cpp_provider.py`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1775933548202-calm-circuit.md:546:   - `llama_cpp_provider.py`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:1:# Plan to Enable CUDA Support for llama.cpp Runtime
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:8:2. llama_cpp_python package is installed (version 0.3.20)
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:9:3. However, llama_cpp module reports `GPU support: False`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:13:The root cause appears to be that the installed llama_cpp_python package was built without CUDA support, and compilation from source fails due to CUDA toolkit compatibility issues with GCC 14.
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:16:After testing environment variables and finding they don't enable GPU offloading in a CPU-only build, we have identified that the llama_cpp_python package was compiled without CUDA support. Since compilation from source fails due to toolchain incompatibility, we'll try:
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:24:- ✅ Confirm llama_cpp_python version (0.3.20)
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:57:1. **llama_cpp_python** was built without CUDA support (CPU-only)
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:64:AI-Karen is currently running with CPU-only llama.cpp inference, which provides:
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776065869588-quick-wizard.md:91:- **Separate Services**: CUDA-enabled llama.cpp service and main AI-Karen application
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776288465546-curious-circuit.md:33:        "llama-cpp": self._check_llamacpp,
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776288465546-curious-circuit.md:34:        "llamacpp": self._check_llamacpp,
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776298678777-lucky-cactus.md:10:3. **Optimized Provider**: Created and registered `llamacpp-optimized` provider with better async support
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776298678777-lucky-cactus.md:15:- NLP service manager prioritizes: `["llamacpp-optimized", "llamacpp", "fallback", "ollama"]`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776298678777-lucky-cactus.md:47:- [ ] Test health check logic for llamacpp providers
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776298678777-lucky-cactus.md:53:- Health checks correctly handle llamacpp permissive mode
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776463152952-witty-nebula.md:32:- `config/llamacpp/config.json`
/mnt/Development/KIRO/AI-Karen/.kilo/plans/1776463152952-witty-nebula.md:54:   - `load_llamacpp_config()` for llamacpp/config.json
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/design.md:48:    C --> I[llama.cpp Runtime]
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/design.md:201:### 6. llama.cpp Tools Integration
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/design.md:206:- Wrapper for llama.cpp binary tools (quantize, convert, merge-lora)
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:38:  - Implement llama.cpp as default always-on runtime for GGUF models
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:47:  - Build runtime registry for llama.cpp, Transformers, and vLLM with compatibility matching
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:51:- [x] 2.2 Implement llama.cpp runtime as default backbone
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:55:  - Implement health probes and resource monitoring for llama.cpp runtime
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:56:  - Use llama.cpp for summaries, background tasks, offline fallback, and privacy-sensitive operations
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:63:  - Add compatibility rules: GGUF → llama.cpp, safetensors → Transformers/vLLM
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:71:  - Add policy-based routing: privacy/context → llama.cpp, interactive → vLLM, flexibility → Transformers
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:79:  - Add privacy-aware routing (high privacy → llama.cpp) and performance routing (interactive → vLLM)
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:103:  - Add model conversion and quantization tools with llama.cpp integration
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:111:  - Add compatibility detection between models and runtimes (GGUF → llama.cpp, safetensors → Transformers/vLLM)
/mnt/Development/KIRO/AI-Karen/.kiro/specs/dynamic-llm-provider-management/tasks.md:125:  - Implement `src/ai_karen_engine/inference/llama_tools.py` wrapper for llama.cpp binaries
/mnt/Development/KIRO/AI-Karen/.kiro/specs/llm-response-routing-fix/design.md:358:      { provider: "llamacpp", model: "tinyllama-1.1b-chat-v2.0.Q4_K_M.gguf" }
/mnt/Development/KIRO/AI-Karen/.kiro/specs/llm-response-routing-fix/design.md:375:    primary: ["openai", "deepseek", "llamacpp"]
/mnt/Development/KIRO/AI-Karen/.kiro/specs/llm-response-routing-fix/design.md:376:    local_only: ["llamacpp", "huggingface"]
/mnt/Development/KIRO/AI-Karen/.kiro/specs/provider-logic-wiring-fix/design.md:423:2. **All Cloud Providers Fail**: Fall back to local providers (llama.cpp, transformers)
/mnt/Development/KIRO/AI-Karen/logs/startup_manual.log:62:2026-04-19 11:52:59,846 - ai_karen_engine.inference.llamacpp_runtime - INFO - Initializing global LlamaCppRuntime singleton
/mnt/Development/KIRO/AI-Karen/logs/startup_manual.log:65:2026-04-19 11:52:59,913 - ai_karen_engine.inference.llamacpp_runtime - WARNING - llama.cpp GPU offload requested but this llama-cpp-python build does not expose GPU offload. Use the CUDA image target and run the container with GPU devices enabled.
/mnt/Development/KIRO/AI-Karen/logs/startup_manual.log:66:2026-04-19 11:52:59,914 - ai_karen_engine.inference.llamacpp_runtime - INFO - Loading GGUF model: /mnt/Development/KIRO/AI-Karen/models/llama-cpp/Phi-3-mini-4k-instruct-q4.gguf
/mnt/Development/KIRO/AI-Karen/logs/startup_manual.log:343:2026-04-19 11:53:12,123 - ai_karen_engine.inference.llamacpp_runtime - INFO - Model loaded successfully in 12.21s
/mnt/Development/KIRO/AI-Karen/logs/startup_manual.log:344:2026-04-19 11:53:12,124 - ai_karen_engine.inference.llamacpp_runtime - INFO - GGUF model already loaded: /mnt/Development/KIRO/AI-Karen/models/llama-cpp/Phi-3-mini-4k-instruct-q4.gguf
/mnt/Development/KIRO/AI-Karen/runtime_refactor_reports/runtime_refactor_20260424_074711.md:7:## Legacy llama.cpp References
/mnt/Development/KIRO/AI-Karen/server/chat/providers/local.py:36:        self.provider_type = config.get("provider_type", "ollama")  # ollama, llama_cpp, custom
/mnt/Development/KIRO/AI-Karen/server/chat/providers/local.py:74:        if provider_type and provider_type not in ["ollama", "llama_cpp", "custom"]:
/mnt/Development/KIRO/AI-Karen/server/chat/providers/local.py:75:            errors.append("Provider type must be one of: ollama, llama_cpp, custom")
/mnt/Development/KIRO/AI-Karen/server/chat/providers/local.py:134:            elif self.provider_type == "llama_cpp":
/mnt/Development/KIRO/AI-Karen/server/startup.py:197:            if active_provider not in {"llama-cpp", "llamacpp", "local"}:
/mnt/Development/KIRO/AI-Karen/performance-test-cuda.sh:105:docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" ai-karen-llamacpp ai-karen-app
/mnt/Development/KIRO/AI-Karen/.pytest_cache/v/cache/nodeids:1509:  "tests/unit/ai/test_llamacpp_api_structure.py::test_backward_compatibility_structure",
/mnt/Development/KIRO/AI-Karen/.pytest_cache/v/cache/nodeids:1510:  "tests/unit/ai/test_llamacpp_api_structure.py::test_client_import_structure",
/mnt/Development/KIRO/AI-Karen/.pytest_cache/v/cache/nodeids:1511:  "tests/unit/ai/test_llamacpp_api_structure.py::test_plugin_import_structure",
/mnt/Development/KIRO/AI-Karen/.pytest_cache/v/cache/nodeids:1512:  "tests/unit/ai/test_llamacpp_api_structure.py::test_route_definitions",
/mnt/Development/KIRO/AI-Karen/.pytest_cache/v/cache/nodeids:2961:  "tests/unit/models/test_model_orchestrator_api_integration.py::TestLLMServiceIntegration::test_llama_cpp_model_registration",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain/llms/__init__.py:272:def _import_llamacpp() -> Any:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain/llms/__init__.py:273:    from langchain_community.llms.llamacpp import LlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain/llms/__init__.py:692:        "llamacpp": _import_llamacpp,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1193:langchain/embeddings/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1243:langchain/embeddings/llamacpp.py,sha256=Izw87kqiofsMKRrSGU0I4IBJvDcKvGXeGt_dbTBh7Nk,641
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1421:langchain/llms/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1505:langchain/llms/llamacpp.py,sha256=c452-Dz-lpgCsSUsMjp-6Nwic4KLFEsO6G4j6boA7UE,599
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/baichuan.py:63:from langchain_community.chat_models.llamacpp import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:62:    """llama.cpp model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:154:    """Any additional parameters to pass to llama_cpp.Llama."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:180:            from llama_cpp import Llama, LlamaGrammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:239:        Performs sanity check, preparing parameters in format needed by llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:247:        # llama_cpp expects the "stop" key not this, so we remove it:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:48:      backend: Literal["llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"] = "transformers"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:93:        "llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:98:    - "llamacpp": For GGUF models using llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:242:        if self.backend == "llamacpp":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:243:            check_packages_installed([("llama-cpp-python", "llama_cpp")])
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:248:                raise ValueError("GGUF file_name must be provided for llama.cpp.")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:249:            self.client = models.llamacpp(repo_id, file_name, **self.model_kwargs)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/outlines.py:338:        if self.backend == "llamacpp":  # get base_model_name from gguf repo_id
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/__init__.py:109:    from langchain_community.chat_models.llamacpp import ChatLlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/chat_models/__init__.py:326:    "ChatLlamaCpp": "langchain_community.chat_models.llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/embeddings/__init__.py:129:    from langchain_community.embeddings.llamacpp import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/embeddings/__init__.py:376:    "LlamaCppEmbeddings": "langchain_community.embeddings.llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/embeddings/llamacpp.py:9:    """llama.cpp embedding models.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/embeddings/llamacpp.py:93:                from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:18:    """llama.cpp model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:114:    """Any additional parameters to pass to llama_cpp.Llama."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:140:            from llama_cpp import Llama, LlamaGrammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:207:        """Get the default parameters for calling llama_cpp."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:231:        return "llamacpp"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:235:        Performs sanity check, preparing parameters in format needed by llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:238:            stop (Optional[List[str]]): List of stop sequences for llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/llamacpp.py:250:        # llama_cpp expects the "stop" key not this, so we remove it:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:36:        "llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:41:    - "llamacpp": For GGUF models using llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:185:        if self.backend == "llamacpp":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:190:                raise ValueError("GGUF file_name must be provided for llama.cpp.")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:191:            check_packages_installed([("llama-cpp-python", "llama_cpp")])
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/outlines.py:192:            self.client = models.llamacpp(repo_id, file_name, **self.model_kwargs)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/__init__.py:311:def _import_llamacpp() -> Type[BaseLLM]:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/__init__.py:312:    from langchain_community.llms.llamacpp import LlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/__init__.py:773:        return _import_llamacpp()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community/llms/__init__.py:1046:        "llamacpp": _import_llamacpp,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:405:langchain_community/chat_models/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:470:langchain_community/chat_models/llamacpp.py,sha256=LbZAEQSE4zBX0y1b_bKvxBEta5i7o6SZhQFI342NPkw,31408
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1031:langchain_community/embeddings/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1108:langchain_community/embeddings/llamacpp.py,sha256=IsBVteNHonNSr0pBfXiREk-NM8F6pce19sVxQeYLcQ4,4994
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1279:langchain_community/llms/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1383:langchain_community/llms/llamacpp.py,sha256=NxXXty_x4MdI22m9BT8hzU4X5LdF6CD7KzjLUy5JZxU,12390
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/ggml-metal.h:48:        "obsoleted by the new device interface - https://github.com/ggml-org/llama.cpp/pull/9713");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:190:    // TODO: simplify (https://github.com/ggml-org/llama.cpp/pull/9294#pullrequestreview-2286561979)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:296:    //       https://github.com/ggml-org/llama.cpp/pull/7544
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:309:        // ref: https://github.com/ggml-org/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:337:        bool swa_full;    // use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:339:                          //       ref: https://github.com/ggml-org/llama.cpp/pull/13845#issuecomment-2924800573
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:342:                          // ref: https://github.com/ggml-org/llama.cpp/pull/14363
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:381:    // TODO: update API to start accepting pointers to params structs (https://github.com/ggml-org/llama.cpp/discussions/9172)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:677:               "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:681:               "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:987:    // TODO: deprecate in favor of llama_get_logits_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1002:    // TODO: deprecate in favor of llama_get_embeddings_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1136:    /// NOTE: This function does not use a jinja parser. It only support a pre-defined list of template. See more: https://github.com/ggml-org/llama.cpp/wiki/Templates-supported-by-llama_chat_apply_template
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1245:        "will be removed in the future (see https://github.com/ggml-org/llama.cpp/pull/9896#discussion_r1800920915)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1254:    /// @details Minimum P sampling as described in https://github.com/ggml-org/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1315:    /// @details Lazy grammar sampler, introduced in https://github.com/ggml-org/llama.cpp/pull/9639
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/llama.h:1416:    // NOTE: Used by llama.cpp examples, avoid using in third-party apps. Instead, do your own performance measurements.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/include/mtmd.h:19: * libmtmd: A library for multimodal support in llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/huggingface_hub/constants.py:90:    "llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:308:                # Conditions should closely match those in llama_model_quantize_internal in llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:651:                    # The tokenizer in llama.cpp assumes the CONTROL and USER_DEFINED tokens are pre-normalized.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:674:    # ref:  https://github.com/ggml-org/llama.cpp/pull/6920
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:680:        # use in llama.cpp to implement the same pre-tokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:893:            logger.warning("** ref:     https://github.com/ggml-org/llama.cpp/pull/6920")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:2708:        # But llama.cpp moe graph works differently
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:3639:                    # The tokenizer in llama.cpp assumes the CONTROL and USER_DEFINED tokens are pre-normalized.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:4351:            #       https://github.com/ggml-org/llama.cpp/pull/6745#issuecomment-2067687048
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:4924:        # lm_head is not used in llama.cpp, while autoawq will include this tensor in model
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:4971:        # lm_head is not used in llama.cpp, while autoawq will include this tensor in model
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:5066:        # related to https://github.com/ggml-org/llama.cpp/issues/13025
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:5225:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:5306:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:5369:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:5481:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/bin/convert_hf_to_gguf.py:7525:        #   in llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/integrations/ggml.py:242:        # See: https://github.com/ggerganov/llama.cpp/blob/2e2f8f093cd4fb6bbb87ba84f6b9684fa082f3fa/convert_hf_to_gguf.py#L3293-L3294
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/integrations/ggml.py:258:        # See: https://github.com/ggml-org/llama.cpp/blob/fe5b78c89670b2f37ecb216306bed3e677b49d9f/convert_hf_to_gguf.py#L3495-L3496
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:90:        # https://github.com/ggerganov/llama.cpp/blob/a38b884c6c4b0c256583acfaaabdf556c62fabea/convert_hf_to_gguf.py#L1402-L1408
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:120:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L1994-L2022
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:145:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L972-L985
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:157:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L986-L998
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:187:        # https://github.com/ggerganov/llama.cpp/blob/a38b884c6c4b0c256583acfaaabdf556c62fabea/convert_hf_to_gguf.py#L2060-L2061
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:218:            # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L2975-L2977
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:227:    # ref : https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L4666
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:238:    # ref: https://github.com/ggerganov/llama.cpp/blob/d79d8f39b4da6deca4aea8bf130c6034c482b320/convert_hf_to_gguf.py#L3191
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:300:            "https://pytorch.org/ and https://github.com/ggerganov/llama.cpp/tree/master/gguf-py for installation instructions."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:327:            "https://github.com/ggerganov/llama.cpp/tree/master/gguf-py#development"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:380:            "https://pytorch.org/ and https://github.com/ggerganov/llama.cpp/tree/master/gguf-py for installation instructions."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:395:    # in llama.cpp mistral models use the same architecture as llama. We need
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:481:        ## llama.cpp defines the layers that are full-attention by looking at num_key_value_heads
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers/generation/utils.py:1277:                # Applied after temperature scaling (see https://github.com/ggerganov/llama.cpp/pull/3841#issuecomment-2073826084)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/transformers-4.57.6.dist-info/METADATA:618:and adjacent modeling libraries (llama.cpp, mlx, ...) which leverage the model definition from `transformers`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:42:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:43:import llama_cpp.llama_chat_format as llama_chat_format
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:45:from llama_cpp.llama_speculative import LlamaDraftModel
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:50:import llama_cpp._internals as internals
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:56:    """High-level Python wrapper for a llama.cpp model."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:66:        split_mode: int = llama_cpp.LLAMA_SPLIT_MODE_LAYER,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:74:        seed: int = llama_cpp.LLAMA_DEFAULT_SEED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:82:        ] = llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:83:        pooling_type: int = llama_cpp.LLAMA_POOLING_TYPE_UNSPECIFIED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:122:        """Load a llama.cpp model from `model_path`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:127:            >>> import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:128:            >>> model = llama_cpp.Llama(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:136:            >>> import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:137:            >>> model = llama_cpp.Llama(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:151:            split_mode: How to split the model across GPUs. See llama_cpp.LLAMA_SPLIT_* for options.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:164:            rope_scaling_type: RoPE scaling type, from `enum llama_rope_scaling_type`. ref: https://github.com/ggerganov/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:178:            swa_full: use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:187:            tokenizer: Optional tokenizer to override the default tokenizer from llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:206:                llama_cpp.llama_backend_init()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:211:                llama_cpp.GGML_NUMA_STRATEGY_DISTRIBUTE
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:213:                else llama_cpp.GGML_NUMA_STRATEGY_DISABLED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:218:        if self.numa != llama_cpp.GGML_NUMA_STRATEGY_DISABLED:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:220:                llama_cpp.llama_numa_init(self.numa)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:225:        self.model_params = llama_cpp.llama_model_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:234:            if len(self.tensor_split) > llama_cpp.LLAMA_MAX_DEVICES:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:236:                    f"Attempt to split tensors that exceed maximum supported devices. Current LLAMA_MAX_DEVICES={llama_cpp.LLAMA_MAX_DEVICES}"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:239:            FloatArray = ctypes.c_float * llama_cpp.LLAMA_MAX_DEVICES
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:254:                llama_cpp.llama_model_kv_override * kvo_array_len
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:262:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_BOOL
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:267:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_INT
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:272:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_FLOAT
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:281:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_STR
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:286:                        + llama_cpp.llama_model_kv_override_value.val_str.offset,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:307:        self._seed = seed or llama_cpp.LLAMA_DEFAULT_SEED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:310:        self.context_params = llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:319:            else llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:414:        self._lora_adapter: Optional[llama_cpp.llama_adapter_lora_p] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:417:            self._lora_adapter = llama_cpp.llama_adapter_lora_init(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:429:                llama_cpp.llama_adapter_lora_free(self._lora_adapter)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:434:            if llama_cpp.llama_set_adapter_lora(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:442:            print(llama_cpp.llama_print_system_info().decode("utf-8"), file=sys.stderr)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:490:        # Unfortunately the llama.cpp API does not return metadata arrays, so we can't get template names from tokenizer.chat_templates
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:550:    def ctx(self) -> llama_cpp.llama_context_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:554:    def model(self) -> llama_cpp.llama_model_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:693:            def apply_func(token_data_array: llama_cpp.llama_token_data_array_p):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:704:                    buf=(llama_cpp.llama_token_data * size).from_address(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1022:        logits_all = pooling_type == llama_cpp.LLAMA_POOLING_TYPE_NONE
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1030:            llama_cpp.llama_perf_context_reset(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1044:            llama_cpp.llama_kv_self_clear(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1049:            if pooling_type == llama_cpp.LLAMA_POOLING_TYPE_NONE:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1052:                    ptr = llama_cpp.llama_get_embeddings(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1065:                    ptr = llama_cpp.llama_get_embeddings_seq(self._ctx.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1111:            llama_cpp.llama_perf_context_print(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1115:        llama_cpp.llama_kv_self_clear(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1274:                f"Requested tokens ({len(prompt_tokens)}) exceed context window of {llama_cpp.llama_n_ctx(self.ctx)}"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1340:            if llama_cpp.llama_token_is_eog(self._model.vocab, token):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1779:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1876:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:1976:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:2130:        state_size = llama_cpp.llama_get_state_size(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:2136:        n_bytes = llama_cpp.llama_copy_state_data(self._ctx.ctx, llama_state)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:2142:        llama_cpp.ctypes.memmove(llama_state_compact, llama_state, int(n_bytes))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama.py:2169:        if llama_cpp.llama_set_state_data(self._ctx.ctx, llama_state) != state_size:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:12:import llama_cpp.llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:18:    """Base cache class for a llama.cpp model."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:35:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:44:        self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:50:    """Cache for a llama.cpp model using RAM."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:56:            Tuple[int, ...], "llama_cpp.llama.LlamaState"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:70:            (k, llama_cpp.llama.Llama.longest_token_prefix(k, key))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:79:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:91:    def __setitem__(self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:105:    """Cache for a llama.cpp model using disk."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:124:            prefix_len = llama_cpp.llama.Llama.longest_token_prefix(k, key)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:130:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:135:        value: "llama_cpp.llama.LlamaState" = self.cache.pop(_key)  # type: ignore
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cache.py:144:    def __setitem__(self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:32:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:33:import llama_cpp.llama as llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:34:import llama_cpp.llama_types as llama_types
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:35:import llama_cpp.llama_grammar as llama_grammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:71:        # llama.cpp instance
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:94:        # llama.cpp parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:2700:        import llama_cpp.mtmd_cpp as mtmd_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:2882:                n_past = llama_cpp.llama_pos(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:2918:                        new_n_past = llama_cpp.llama_pos(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:2923:                            llama_cpp.llama_pos(llama.n_tokens),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_chat_format.py:2924:                            llama_cpp.llama_seq_id(0),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:15:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:22:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:206:# NOTE: Deprecated and will be removed in the future. (already gone in llama.cpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:752:# //       https://github.com/ggml-org/llama.cpp/pull/7544
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:765:#     // ref: https://github.com/ggml-org/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:793:#     bool swa_full;    // use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:795:#                       //       ref: https://github.com/ggml-org/llama.cpp/pull/13845#issuecomment-2924800573
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:798:#                       // ref: https://github.com/ggml-org/llama.cpp/pull/14363
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:2046:#            "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:2057:#            "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:2856:# // TODO: deprecate in favor of llama_get_logits_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:2897:# // TODO: deprecate in favor of llama_get_embeddings_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:3517:# /// NOTE: This function does not use a jinja parser. It only support a pre-defined list of template. See more: https://github.com/ggml-org/llama.cpp/wiki/Templates-supported-by-llama_chat_apply_template
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:3808:#     "will be removed in the future (see https://github.com/ggml-org/llama.cpp/pull/9896#discussion_r1800920915)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:3833:# /// @details Minimum P sampling as described in https://github.com/ggml-org/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_cpp.py:3984:# /// @details Lazy grammar sampler, introduced in https://github.com/ggml-org/llama.cpp/pull/9639
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_grammar.py:1:"""Python implementation of llama grammar parser directly translated from C++ source file in vendor/llama.cpp/common/grammar-parser.cpp."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_grammar.py:50:"""llama.cpp gbnf rules from vendor/llama.cpp/grammars"""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_grammar.py:235:"""llama.cpp json-schema to grammar converter from vendor/llama.cpp/examples/json-schema-to-grammar.py"""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_grammar.py:505:        Output: https://github.com/ggerganov/llama.cpp/blob/master/grammars/README.md
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_tokenizer.py:10:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_tokenizer.py:11:from llama_cpp.llama_types import List
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_tokenizer.py:46:    def __init__(self, llama: llama_cpp.Llama):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llama_tokenizer.py:74:        return cls(llama_cpp.Llama(model_path=path, vocab_only=True))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:23:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:25:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:31:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:71:    [llama_cpp.llama_context_p_ctypes, clip_ctx_p_ctypes],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:75:    ctx_llama: llama_cpp.llama_context_p, ctx_clip: clip_ctx_p, /
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:122:        llama_cpp.llama_context_p_ctypes,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/llava_cpp.py:130:    ctx_llama: llama_cpp.llama_context_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:26:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:28:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:34:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:111:    [c_char_p, llama_cpp.llama_model_p_ctypes, mtmd_context_params],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:116:    text_model: llama_cpp.llama_model_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:217:    POINTER(llama_cpp.llama_token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:221:) -> Optional["_Pointer[llama_cpp.llama_token]"]:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:259:        llama_cpp.llama_context_p_ctypes,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:261:        llama_cpp.llama_pos,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:262:        llama_cpp.llama_seq_id,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:265:        POINTER(llama_cpp.llama_pos),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:271:    lctx: llama_cpp.llama_context_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:273:    n_past: llama_cpp.llama_pos,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:274:    seq_id: llama_cpp.llama_seq_id,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/mtmd_cpp.py:277:    new_n_past: "_Pointer[llama_cpp.llama_pos]",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:12:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:25:from llama_cpp.server.model import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:28:from llama_cpp.server.settings import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:34:from llama_cpp.server.types import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:45:from llama_cpp.server.errors import RouteErrorHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:136:        title="🦙 llama.cpp Python API",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:137:        version=llama_cpp.__version__,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:163:) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:178:        kwargs["grammar"] = llama_cpp.LlamaGrammar.from_string(body.grammar)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:181:        _min_tokens_logits_processor = llama_cpp.LogitsProcessorList(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:182:            [llama_cpp.MinTokensLogitsProcessor(body.min_tokens, llama.token_eos())]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:226:    llama: llama_cpp.Llama,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:269:        llama_cpp.CreateCompletionResponse,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:306:) -> llama_cpp.Completion:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:337:                llama_call=llama_cpp.Llama.__call__,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:380:    response_model=Union[llama_cpp.ChatCompletion, str],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:480:) -> llama_cpp.ChatCompletion:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/app.py:506:                llama_call=llama_cpp.Llama.create_chat_completion,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/errors.py:19:from llama_cpp.server.types import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/errors.py:105:    # key: regex pattern for original error message from llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:7:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:8:import llama_cpp.llama_speculative as llama_speculative
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:9:import llama_cpp.llama_tokenizer as llama_tokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:11:from llama_cpp.server.settings import ModelSettings
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:24:        self._current_model: Optional[llama_cpp.Llama] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:36:    def __call__(self, model: Optional[str] = None) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:74:    def load_llama_from_model_settings(settings: ModelSettings) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:80:                    llama_cpp.llama_chat_format.Llava15ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:87:                chat_handler = llama_cpp.llama_chat_format.Llava15ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:94:                    llama_cpp.llama_chat_format.ObsidianChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:101:                chat_handler = llama_cpp.llama_chat_format.ObsidianChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:108:                    llama_cpp.llama_chat_format.Llava16ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:115:                chat_handler = llama_cpp.llama_chat_format.Llava16ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:122:                    llama_cpp.llama_chat_format.MoondreamChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:129:                chat_handler = llama_cpp.llama_chat_format.MoondreamChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:136:                    llama_cpp.llama_chat_format.NanoLlavaChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:143:                chat_handler = llama_cpp.llama_chat_format.NanoLlavaChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:150:                    llama_cpp.llama_chat_format.Llama3VisionAlpha.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:157:                chat_handler = llama_cpp.llama_chat_format.Llama3VisionAlpha(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:164:                    llama_cpp.llama_chat_format.MiniCPMv26ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:171:                chat_handler = llama_cpp.llama_chat_format.MiniCPMv26ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:178:                    llama_cpp.llama_chat_format.Qwen25VLChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:185:                chat_handler = llama_cpp.llama_chat_format.Qwen25VLChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:193:                llama_cpp.llama_chat_format.hf_autotokenizer_to_chat_completion_handler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:201:            chat_handler = llama_cpp.llama_chat_format.hf_tokenizer_config_to_chat_completion_handler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:205:        tokenizer: Optional[llama_cpp.BaseLlamaTokenizer] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:242:                llama_cpp.Llama.from_pretrained,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:247:            create_fn = llama_cpp.Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:306:                cache = llama_cpp.LlamaDiskCache(capacity_bytes=settings.cache_size)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/model.py:310:                cache = llama_cpp.LlamaRAMCache(capacity_bytes=settings.cache_size)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:11:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:34:        default=llama_cpp.LLAMA_SPLIT_MODE_LAYER,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:50:        default=llama_cpp.llama_supports_mmap(),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:54:        default=llama_cpp.llama_supports_mlock(),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:67:        default=llama_cpp.LLAMA_DEFAULT_SEED, description="Random seed. -1 for random."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:74:        default=512, ge=1, description="The physical batch size used by llama.cpp"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/settings.py:87:        default=llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:8:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:146:    # llama.cpp specific parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:193:    messages: List[llama_cpp.ChatCompletionRequestMessage] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:196:    functions: Optional[List[llama_cpp.ChatCompletionFunction]] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:200:    function_call: Optional[llama_cpp.ChatCompletionRequestFunctionCall] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:204:    tools: Optional[List[llama_cpp.ChatCompletionTool]] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:208:    tool_choice: Optional[llama_cpp.ChatCompletionToolChoiceOption] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:235:    response_format: Optional[llama_cpp.ChatCompletionRequestResponseFormat] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/types.py:244:    # llama.cpp specific parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:1:"""Example FastAPI server for llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:12:uvicorn llama_cpp.server.app:create_app --reload
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:18:python3 -m llama_cpp.server
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:33:from llama_cpp.server.app import create_app
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:34:from llama_cpp.server.settings import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/server/__main__.py:40:from llama_cpp.server.cli import add_args_from_model, parse_model_from_args
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_ctypes_extensions.py:26:    # for llamacpp) and "llama" (default name for this repo)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_ggml.py:8:import llama_cpp._ctypes_extensions as ctypes_ext
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:25:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:32:    """Intermediate Python wrapper for a llama.cpp llama_model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:39:        params: llama_cpp.llama_model_params,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:53:            model = llama_cpp.llama_model_load_from_file(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:60:        vocab = llama_cpp.llama_model_get_vocab(model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:72:            llama_cpp.llama_model_free(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:79:            # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:81:                llama_cpp.llama_sampler_chain_remove(self.sampler, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:89:        return llama_cpp.llama_vocab_type(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:92:        return llama_cpp.llama_vocab_n_tokens(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:95:        return llama_cpp.llama_model_n_ctx_train(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:98:        return llama_cpp.llama_model_n_embd(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:101:        return llama_cpp.llama_model_rope_freq_scale_train(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:105:        llama_cpp.llama_model_desc(self.model, buf, 1024)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:109:        return llama_cpp.llama_model_size(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:112:        return llama_cpp.llama_model_n_params(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:115:        raise NotImplementedError("get_tensor is not implemented in llama.cpp")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:120:        return llama_cpp.llama_vocab_get_text(self.vocab, token).decode("utf-8")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:123:        return llama_cpp.llama_vocab_get_score(self.vocab, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:126:        return llama_cpp.llama_vocab_get_attr(self.vocab, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:131:        return llama_cpp.llama_vocab_bos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:134:        return llama_cpp.llama_vocab_eos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:137:        return llama_cpp.llama_vocab_cls(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:140:        return llama_cpp.llama_vocab_sep(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:143:        return llama_cpp.llama_vocab_nl(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:146:        return llama_cpp.llama_vocab_fim_pre(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:149:        return llama_cpp.llama_vocab_fim_mid(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:152:        return llama_cpp.llama_vocab_fim_suf(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:155:        return llama_cpp.llama_vocab_eot(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:158:        return llama_cpp.llama_vocab_get_add_bos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:161:        return llama_cpp.llama_vocab_get_add_eos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:167:        tokens = (llama_cpp.llama_token * n_ctx)()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:168:        n_tokens = llama_cpp.llama_tokenize(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:173:            tokens = (llama_cpp.llama_token * n_tokens)()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:174:            n_tokens = llama_cpp.llama_tokenize(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:185:        llama_cpp.llama_token_to_piece(self.vocab, token, buf, 32, 0, special)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:193:            n = llama_cpp.llama_token_to_piece(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:194:                self.vocab, llama_cpp.llama_token(token), buffer, size, 0, special
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:214:        for i in range(llama_cpp.llama_model_meta_count(self.model)):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:215:            nbytes = llama_cpp.llama_model_meta_key_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:221:                nbytes = llama_cpp.llama_model_meta_key_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:225:            nbytes = llama_cpp.llama_model_meta_val_str_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:231:                nbytes = llama_cpp.llama_model_meta_val_str_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:241:        return llama_cpp.llama_model_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:245:    """Intermediate Python wrapper for a llama.cpp llama_context.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:252:        params: llama_cpp.llama_context_params,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:260:        ctx = llama_cpp.llama_init_from_model(self.model.model, self.params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:266:        self.memory = llama_cpp.llama_get_memory(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:272:            llama_cpp.llama_free(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:284:        return llama_cpp.llama_n_ctx(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:287:        return llama_cpp.llama_pooling_type(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:291:        llama_cpp.llama_memory_clear(self.memory, True)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:296:        llama_cpp.llama_memory_seq_rm(self.memory, seq_id, p0, p1)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:300:        llama_cpp.llama_memory_seq_cp(self.memory, seq_id_src, seq_id_dst, p0, p1)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:304:        llama_cpp.llama_memory_seq_keep(self.memory, seq_id)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:308:        llama_cpp.llama_memory_seq_add(self.memory, seq_id, p0, p1, shift)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:311:        return llama_cpp.llama_state_get_size(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:322:        return_code = llama_cpp.llama_decode(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:330:        return_code = llama_cpp.llama_encode(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:338:        llama_cpp.llama_set_n_threads(self.ctx, n_threads, n_threads_batch)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:341:        return llama_cpp.llama_get_logits(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:344:        return llama_cpp.llama_get_logits_ith(self.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:347:        return llama_cpp.llama_get_embeddings(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:350:        return llama_cpp.llama_get_embeddings_ith(self.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:353:        return llama_cpp.llama_get_embeddings_seq(self.ctx, seq_id)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:363:        last_tokens_data: "llama_cpp.Array[llama_cpp.llama_token]",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:400:        mu: llama_cpp.CtypesPointerOrRef[ctypes.c_float],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:409:        mu: llama_cpp.CtypesPointerOrRef[ctypes.c_float],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:424:        llama_cpp.llama_perf_context_reset(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:427:        llama_cpp.llama_perf_context_print(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:433:        return llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:446:        batch = llama_cpp.llama_batch_init(self._n_tokens, self.embd, self.n_seq_max)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:457:            llama_cpp.llama_batch_free(self.batch)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:508:        self.candidates = llama_cpp.llama_token_data_array(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:509:            data=self.candidates_data.ctypes.data_as(llama_cpp.llama_token_data_p),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:572:    cur: list[llama_cpp.llama_token_data] = field(default_factory=list)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:613:        self, apply_func: Callable[[llama_cpp.llama_token_data_array], None]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:618:            sampler: llama_cpp.llama_sampler_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:619:            cur_p: llama_cpp.llama_token_data_array_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:623:        def free_wrapper(sampler: llama_cpp.llama_sampler_p):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:626:        sampler_i = llama_cpp.llama_sampler_i()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:627:        sampler_i.apply = llama_cpp.llama_sampler_i_apply(apply_wrapper)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:630:        sampler_i.name = llama_cpp.llama_sampler_i_name(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:631:        sampler_i.accept = llama_cpp.llama_sampler_i_accept(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:632:        sampler_i.reset = llama_cpp.llama_sampler_i_reset(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:633:        sampler_i.clone = llama_cpp.llama_sampler_i_clone(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:634:        sampler_i.free = llama_cpp.llama_sampler_i_free(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:636:        self.sampler = llama_cpp.llama_sampler()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:640:    def get_sampler(self) -> llama_cpp.llama_sampler_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:646:        params = llama_cpp.llama_sampler_chain_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:647:        self.sampler = llama_cpp.llama_sampler_chain_init(params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:653:                # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:655:                    llama_cpp.llama_sampler_chain_remove(self.sampler, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:656:                llama_cpp.llama_sampler_free(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:668:        sampler = llama_cpp.llama_sampler_init_greedy()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:669:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:672:        sampler = llama_cpp.llama_sampler_init_dist(seed)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:673:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:676:        sampler = llama_cpp.llama_sampler_init_softmax()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:677:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:680:        sampler = llama_cpp.llama_sampler_init_top_k(k)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:681:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:684:        sampler = llama_cpp.llama_sampler_init_top_p(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:685:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:688:        sampler = llama_cpp.llama_sampler_init_min_p(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:689:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:692:        sampler = llama_cpp.llama_sampler_init_typical(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:693:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:696:        sampler = llama_cpp.llama_sampler_init_temp(temp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:697:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:700:        sampler = llama_cpp.llama_sampler_init_temp_ext(t, delta, exponent)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:701:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:704:        sampler = llama_cpp.llama_sampler_init_xtc(p, t, min_keep, seed)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:705:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:708:        sampler = llama_cpp.llama_sampler_init_top_n_sigma(n)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:709:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:712:        sampler = llama_cpp.llama_sampler_init_mirostat(n_vocab, seed, tau, eta, m)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:713:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:716:        sampler = llama_cpp.llama_sampler_init_mirostat_v2(seed, tau, eta)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:717:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:720:        sampler = llama_cpp.llama_sampler_init_grammar(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:723:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:738:        token_array = (llama_cpp.llama_token * len(trigger_tokens))(*trigger_tokens)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:740:        sampler = llama_cpp.llama_sampler_init_grammar_lazy_patterns(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:749:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:758:        sampler = llama_cpp.llama_sampler_init_penalties(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:764:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:781:        sampler = llama_cpp.llama_sampler_init_dry(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:791:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:799:        bias_array = (llama_cpp.llama_logit_bias * len(logit_bias))()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:804:        sampler = llama_cpp.llama_sampler_init_logit_bias(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:809:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:812:        sampler = llama_cpp.llama_sampler_init_infill(model.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:813:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:816:        self, apply_func: Callable[[llama_cpp.llama_token_data_array], None]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:820:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:821:        # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:823:            (llama_cpp.llama_sampler_chain_n(self.sampler) - 1, custom_sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:827:        return llama_cpp.llama_sampler_get_seed(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:830:        return llama_cpp.llama_sampler_sample(self.sampler, ctx.ctx, idx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:833:        llama_cpp.llama_sampler_accept(self.sampler, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:836:        llama_cpp.llama_sampler_reset(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:843:        cloned_sampler = llama_cpp.llama_sampler_clone(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_internals.py:852:                llama_cpp.llama_sampler_free(new_sampler.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_logger.py:5:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_logger.py:29:@llama_cpp.llama_log_callback
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/_logger.py:43:llama_cpp.llama_log_set(llama_log_callback, ctypes.c_void_p(0))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp/__init__.py:1:from .llama_cpp import *
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:2:Name: llama_cpp_python
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:4:Summary: Python bindings for the llama.cpp library
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:48:Requires-Dist: llama_cpp_python[dev,server,test]; extra == "all"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:55:#  Python Bindings for [`llama.cpp`](https://github.com/ggerganov/llama.cpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:65:Simple Python bindings for **@ggerganov's** [`llama.cpp`](https://github.com/ggerganov/llama.cpp) library.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:71:    - [LangChain compatibility](https://python.langchain.com/docs/integrations/llms/llamacpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:72:    - [LlamaIndex compatibility](https://docs.llamaindex.ai/en/stable/examples/llm/llama_2_llama_cpp.html)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:97:This will also build `llama.cpp` from source and install it alongside this python package.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:112:`llama.cpp` supports a number of hardware acceleration backends to speed up inference as well as backend specific options. See the [llama.cpp README](https://github.com/ggerganov/llama.cpp#build) for a full list.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:114:All `llama.cpp` cmake build options can be set via the `CMAKE_ARGS` environment variable or via the `--config-settings / -C` cli flag during installation.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:275:If you run into issues where it complains it can't find `'nmake'` `'?'` or CMAKE_C_COMPILER, you can extract w64devkit as [mentioned in llama.cpp repo](https://github.com/ggerganov/llama.cpp#openblas) and add those manually to CMAKE_ARGS before running `pip` install:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:299:Otherwise, while installing it will build the llama.cpp x86 version which will be 10x slower on Apple Silicon (M1) Mac.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:320:The high-level API provides a simple managed interface through the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:325:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:366:Text completion is available through the [`__call__`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.__call__) and [`create_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_completion) methods of the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:370:You can download `Llama` models in `gguf` format directly from Hugging Face using the [`from_pretrained`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.from_pretrained) method.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:381:By default [`from_pretrained`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.from_pretrained) will download the model to the huggingface cache directory, you can then manage installed model files with the [`huggingface-cli`](https://huggingface.co/docs/huggingface_hub/en/guides/cli) tool.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:399:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:415:Chat completion is available through the [`create_chat_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion) method of the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:417:For OpenAI API v1 compatibility, you use the [`create_chat_completion_openai_v1`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion_openai_v1) method which will return pydantic models instead of dicts.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:422:To constrain chat responses to only valid JSON or a specific JSON Schema use the `response_format` argument in [`create_chat_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:429:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:451:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:478:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:527:Due to discrepancies between llama.cpp and HuggingFace's tokenizers, it is required to provide HF Tokenizer for functionary. The `LlamaHFTokenizer` class can be initialized and passed into the Llama class. This will override the default llama.cpp tokenizer used in Llama class. The tokenizer files are already included in the respective HF repositories hosting the gguf files.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:530:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:531:from llama_cpp.llama_tokenizer import LlamaHFTokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:563:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:564:from llama_cpp.llama_chat_format import Llava15ChatHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:588:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:589:from llama_cpp.llama_chat_format import MoondreamChatHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:661:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:662:from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:672:To generate text embeddings use [`create_embedding`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_embedding) or [`embed`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.embed). Note that you must pass `embedding=True` to the constructor upon model creation for these to work properly.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:675:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:677:llm = llama_cpp.Llama(model_path="path/to/model.gguf", embedding=True)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:705:This allows you to use llama.cpp compatible models with any OpenAI compatible client (language libraries, services, etc).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:711:python3 -m llama_cpp.server --model models/7B/llama-model.gguf
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:718:python3 -m llama_cpp.server --model models/7B/llama-model.gguf --n_gpu_layers 35
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:723:To bind to `0.0.0.0` to enable remote connections, use `python3 -m llama_cpp.server --host 0.0.0.0`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:729:python3 -m llama_cpp.server --model models/7B/llama-model.gguf --chat_format chatml
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:733:For possible options, see [llama_cpp/llama_chat_format.py](llama_cpp/llama_chat_format.py) and look for lines starting with "@register_chat_format".
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:738:python3 -m llama_cpp.server --hf_model_repo_id Qwen/Qwen2-0.5B-Instruct-GGUF --model '*q8_0.gguf'
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:762:The low-level API is a direct [`ctypes`](https://docs.python.org/3/library/ctypes.html) binding to the C API provided by `llama.cpp`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:763:The entire low-level API can be found in [llama_cpp/llama_cpp.py](https://github.com/abetlen/llama-cpp-python/blob/master/llama_cpp/llama_cpp.py) and directly mirrors the C API in [llama.h](https://github.com/ggerganov/llama.cpp/blob/master/llama.h).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:768:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:770:llama_cpp.llama_backend_init(False) # Must be called once at the start of each program
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:771:params = llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:773:model = llama_cpp.llama_load_model_from_file(b"./models/7b/llama-model.gguf", params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:774:ctx = llama_cpp.llama_new_context_with_model(model, params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:777:tokens = (llama_cpp.llama_token * int(max_tokens))()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:778:n_tokens = llama_cpp.llama_tokenize(ctx, b"Q: Name the planets in the solar system? A: ", tokens, max_tokens, llama_cpp.c_bool(True))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:779:llama_cpp.llama_free(ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:829:You can also test out specific commits of `llama.cpp` by checking out the desired commit in the `vendor/llama.cpp` submodule and then running `make clean` and `pip install -e .` again. Any changes in the `llama.h` API will require
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:830:changes to the `llama_cpp/llama_cpp.py` file to match the new API (additional changes may be required elsewhere).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:837:The reason for this is that `llama.cpp` is built with compiler optimizations that are specific to your system.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:845:### How does this compare to other Python bindings of `llama.cpp`?
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:849:- Provide a simple process to install `llama.cpp` and access the full C API in `llama.h` from Python
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:850:- Provide a high-level Python API that can be used as a drop-in replacement for the OpenAI API so existing apps can be easily ported to use `llama.cpp`
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:33:llama_cpp/__init__.py,sha256=TCpa8_yW00am6A9uqrhCmLdE2u-pMAQMtm2raiSVbOE,70
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:34:llama_cpp/__pycache__/__init__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:35:llama_cpp/__pycache__/_ctypes_extensions.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:36:llama_cpp/__pycache__/_ggml.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:37:llama_cpp/__pycache__/_internals.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:38:llama_cpp/__pycache__/_logger.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:39:llama_cpp/__pycache__/_utils.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:40:llama_cpp/__pycache__/llama.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:41:llama_cpp/__pycache__/llama_cache.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:42:llama_cpp/__pycache__/llama_chat_format.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:43:llama_cpp/__pycache__/llama_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:44:llama_cpp/__pycache__/llama_grammar.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:45:llama_cpp/__pycache__/llama_speculative.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:46:llama_cpp/__pycache__/llama_tokenizer.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:47:llama_cpp/__pycache__/llama_types.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:48:llama_cpp/__pycache__/llava_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:49:llama_cpp/__pycache__/mtmd_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:50:llama_cpp/_ctypes_extensions.py,sha256=nlJBgy_rYePEObDp5Nmp_056alSwgJqPWZXwF12EGHY,4085
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:51:llama_cpp/_ggml.py,sha256=DfF0pvbdo7iIC4sJynLA4efGAYKzTMmia25P9dXLYuQ,369
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:52:llama_cpp/_internals.py,sha256=yk3-wH3ZnzvOiPW4Wr7KAjcbBtL5rI48ITHowolxk2I,29562
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:53:llama_cpp/_logger.py,sha256=ccphvqDhQjiFRluIcG7aVOoCs4EKnvGrFC5mvEm8k1g,1309
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:54:llama_cpp/_utils.py,sha256=adbuDQP6KlQRpvQPSbOvfD7yiqR5VzmedauQTRtM1Yc,2260
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:55:llama_cpp/lib/libggml-base.so,sha256=Qs2IXq4_jVYc1Eq0EWRIebZyEvBmrYquTKXOPb9eagU,615864
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:56:llama_cpp/lib/libggml-cpu.so,sha256=y5PFJCVnk_xU9NOhKhs6BV3UdoZ7kFTkwRgo3cLH6uw,967608
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:57:llama_cpp/lib/libggml.so,sha256=tCnOnlbQgexMrQ_YOXFXmARbEQ6PHfk2q1NQqALkODo,47624
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:58:llama_cpp/lib/libllama.so,sha256=ks4mIQZFkKQnWacuWIHm1d1wEd3I7NItqv28LmmCMws,2150632
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:59:llama_cpp/lib/libmtmd.so,sha256=qw0Vqrd9FK5aGqtN8j1RxTHhTiVFmzVetwsyC8NRfEg,722296
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:60:llama_cpp/llama.py,sha256=M0sV8W7DHeZa3qWMhdvQQFf4h0nK3manrfQmhMTQENg,96173
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:61:llama_cpp/llama_cache.py,sha256=o8sQHL1eBviDZrEqc8ExpUwk-DvICFtkxQNajGcb3Gk,5010
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:62:llama_cpp/llama_chat_format.py,sha256=Nd4E_D4Wth9tcETNlh5pgCUsne8s4k9Y_NUmWqw44Yw,157215
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:63:llama_cpp/llama_cpp.py,sha256=Syf46SU3z9Aa4gNBdFxaInBL6BH_vz7576ZrpkRASSE,152717
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:64:llama_cpp/llama_grammar.py,sha256=TTlpkZeQn0qpj0UIbIJL0FIfvrJ8eq7iSacjxi4dDdg,32913
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:65:llama_cpp/llama_speculative.py,sha256=N9q_Humq0B2C2m1eafvAo3zevXrFvAQsrI6tTj1vtro,2088
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:66:llama_cpp/llama_tokenizer.py,sha256=SC5X2lY91Tf7qMXSrgncNSwwVN_YYilXosuRm4R4yp8,3876
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:67:llama_cpp/llama_types.py,sha256=EDqRqfiQ1_MUwfhRc65eHv0sEhOSAv_UMH-3VMBVhZ4,8666
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:68:llama_cpp/llava_cpp.py,sha256=5tDZrC9Blb71AhpJ074CavkujwZQFUg6y-Z2QsLA-0E,4552
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:69:llama_cpp/mtmd_cpp.py,sha256=5ShRxeaq89DgwWEnHD-qLXJJ_yg3gb6kcr9yX1XqeTA,8834
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:70:llama_cpp/py.typed,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:71:llama_cpp/server/__init__.py,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:72:llama_cpp/server/__main__.py,sha256=HL9yvPX0l7Fy_B4t7JbokucU9CX5UnCx4oRUnBiktpY,2849
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:73:llama_cpp/server/__pycache__/__init__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:74:llama_cpp/server/__pycache__/__main__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:75:llama_cpp/server/__pycache__/app.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:76:llama_cpp/server/__pycache__/cli.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:77:llama_cpp/server/__pycache__/errors.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:78:llama_cpp/server/__pycache__/model.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:79:llama_cpp/server/__pycache__/settings.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:80:llama_cpp/server/__pycache__/types.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:81:llama_cpp/server/app.py,sha256=epaKb0vzhlJNiu95zZ7tgVHfwILEPS6G3sIBKX5JUNo,19572
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:82:llama_cpp/server/cli.py,sha256=mW8NAy8-Gcp-uCSyvLNIaxARIntpPcD1_K1kciHRhSQ,3268
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:83:llama_cpp/server/errors.py,sha256=yl-VMzgp1Y0jO3pME35475nET1RCwnRtshPs9IHhc7M,7164
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:84:llama_cpp/server/model.py,sha256=osPi81ohIN58AAU_sE3oY6ew6iwfTnwVBHznY8MU6NQ,13556
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:85:llama_cpp/server/settings.py,sha256=zVci46BjUKx0gSJGKjIR8E9oWrrj5s3Hqj2hLn5Xd3c,8566
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:86:llama_cpp/server/types.py,sha256=psWzuEjfF4U3kks0HRE67uizMjml8gOf-zXvpsllIrs,12216
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:87:llama_cpp_python-0.3.16.dist-info/INSTALLER,sha256=zuuue4knoyJ-UwPPXg8fezS7VCrXJQrAP7zeNuwvFQg,4
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:88:llama_cpp_python-0.3.16.dist-info/METADATA,sha256=EkGG9Yg7178a2xyzgPwBLZ1N5dy24wN1opjgsMD1a0E,33608
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:89:llama_cpp_python-0.3.16.dist-info/RECORD,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:90:llama_cpp_python-0.3.16.dist-info/REQUESTED,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:91:llama_cpp_python-0.3.16.dist-info/WHEEL,sha256=K7nq3Hjz-S557B68yjvMEO-oGsD5aE0lD8QXdqCuqYk,109
/mnt/Development/KIRO/AI-Karen/.virEnv/lib/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:92:llama_cpp_python-0.3.16.dist-info/licenses/LICENSE.md,sha256=xHn7EaZqhf7SAEoX3Rs-RKGFjFZLFnrssg_2bLQi7XU,1069
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain/llms/__init__.py:272:def _import_llamacpp() -> Any:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain/llms/__init__.py:273:    from langchain_community.llms.llamacpp import LlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain/llms/__init__.py:692:        "llamacpp": _import_llamacpp,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1193:langchain/embeddings/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1243:langchain/embeddings/llamacpp.py,sha256=Izw87kqiofsMKRrSGU0I4IBJvDcKvGXeGt_dbTBh7Nk,641
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1421:langchain/llms/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain-0.3.27.dist-info/RECORD:1505:langchain/llms/llamacpp.py,sha256=c452-Dz-lpgCsSUsMjp-6Nwic4KLFEsO6G4j6boA7UE,599
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/baichuan.py:63:from langchain_community.chat_models.llamacpp import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:62:    """llama.cpp model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:154:    """Any additional parameters to pass to llama_cpp.Llama."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:180:            from llama_cpp import Llama, LlamaGrammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:239:        Performs sanity check, preparing parameters in format needed by llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/llamacpp.py:247:        # llama_cpp expects the "stop" key not this, so we remove it:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:48:      backend: Literal["llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"] = "transformers"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:93:        "llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:98:    - "llamacpp": For GGUF models using llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:242:        if self.backend == "llamacpp":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:243:            check_packages_installed([("llama-cpp-python", "llama_cpp")])
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:248:                raise ValueError("GGUF file_name must be provided for llama.cpp.")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:249:            self.client = models.llamacpp(repo_id, file_name, **self.model_kwargs)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/outlines.py:338:        if self.backend == "llamacpp":  # get base_model_name from gguf repo_id
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/__init__.py:109:    from langchain_community.chat_models.llamacpp import ChatLlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/chat_models/__init__.py:326:    "ChatLlamaCpp": "langchain_community.chat_models.llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/embeddings/__init__.py:129:    from langchain_community.embeddings.llamacpp import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/embeddings/__init__.py:376:    "LlamaCppEmbeddings": "langchain_community.embeddings.llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/embeddings/llamacpp.py:9:    """llama.cpp embedding models.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/embeddings/llamacpp.py:93:                from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:18:    """llama.cpp model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:114:    """Any additional parameters to pass to llama_cpp.Llama."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:140:            from llama_cpp import Llama, LlamaGrammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:207:        """Get the default parameters for calling llama_cpp."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:231:        return "llamacpp"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:235:        Performs sanity check, preparing parameters in format needed by llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:238:            stop (Optional[List[str]]): List of stop sequences for llama_cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/llamacpp.py:250:        # llama_cpp expects the "stop" key not this, so we remove it:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:36:        "llamacpp", "transformers", "transformers_vision", "vllm", "mlxlm"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:41:    - "llamacpp": For GGUF models using llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:185:        if self.backend == "llamacpp":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:190:                raise ValueError("GGUF file_name must be provided for llama.cpp.")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:191:            check_packages_installed([("llama-cpp-python", "llama_cpp")])
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/outlines.py:192:            self.client = models.llamacpp(repo_id, file_name, **self.model_kwargs)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/__init__.py:311:def _import_llamacpp() -> Type[BaseLLM]:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/__init__.py:312:    from langchain_community.llms.llamacpp import LlamaCpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/__init__.py:773:        return _import_llamacpp()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community/llms/__init__.py:1046:        "llamacpp": _import_llamacpp,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:405:langchain_community/chat_models/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:470:langchain_community/chat_models/llamacpp.py,sha256=LbZAEQSE4zBX0y1b_bKvxBEta5i7o6SZhQFI342NPkw,31408
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1031:langchain_community/embeddings/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1108:langchain_community/embeddings/llamacpp.py,sha256=IsBVteNHonNSr0pBfXiREk-NM8F6pce19sVxQeYLcQ4,4994
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1279:langchain_community/llms/__pycache__/llamacpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/langchain_community-0.3.31.dist-info/RECORD:1383:langchain_community/llms/llamacpp.py,sha256=NxXXty_x4MdI22m9BT8hzU4X5LdF6CD7KzjLUy5JZxU,12390
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/ggml-metal.h:48:        "obsoleted by the new device interface - https://github.com/ggml-org/llama.cpp/pull/9713");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:190:    // TODO: simplify (https://github.com/ggml-org/llama.cpp/pull/9294#pullrequestreview-2286561979)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:296:    //       https://github.com/ggml-org/llama.cpp/pull/7544
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:309:        // ref: https://github.com/ggml-org/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:337:        bool swa_full;    // use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:339:                          //       ref: https://github.com/ggml-org/llama.cpp/pull/13845#issuecomment-2924800573
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:342:                          // ref: https://github.com/ggml-org/llama.cpp/pull/14363
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:381:    // TODO: update API to start accepting pointers to params structs (https://github.com/ggml-org/llama.cpp/discussions/9172)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:677:               "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:681:               "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:987:    // TODO: deprecate in favor of llama_get_logits_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1002:    // TODO: deprecate in favor of llama_get_embeddings_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1136:    /// NOTE: This function does not use a jinja parser. It only support a pre-defined list of template. See more: https://github.com/ggml-org/llama.cpp/wiki/Templates-supported-by-llama_chat_apply_template
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1245:        "will be removed in the future (see https://github.com/ggml-org/llama.cpp/pull/9896#discussion_r1800920915)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1254:    /// @details Minimum P sampling as described in https://github.com/ggml-org/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1315:    /// @details Lazy grammar sampler, introduced in https://github.com/ggml-org/llama.cpp/pull/9639
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/llama.h:1416:    // NOTE: Used by llama.cpp examples, avoid using in third-party apps. Instead, do your own performance measurements.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/include/mtmd.h:19: * libmtmd: A library for multimodal support in llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/huggingface_hub/constants.py:90:    "llamacpp",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:308:                # Conditions should closely match those in llama_model_quantize_internal in llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:651:                    # The tokenizer in llama.cpp assumes the CONTROL and USER_DEFINED tokens are pre-normalized.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:674:    # ref:  https://github.com/ggml-org/llama.cpp/pull/6920
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:680:        # use in llama.cpp to implement the same pre-tokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:893:            logger.warning("** ref:     https://github.com/ggml-org/llama.cpp/pull/6920")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:2708:        # But llama.cpp moe graph works differently
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:3639:                    # The tokenizer in llama.cpp assumes the CONTROL and USER_DEFINED tokens are pre-normalized.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:4351:            #       https://github.com/ggml-org/llama.cpp/pull/6745#issuecomment-2067687048
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:4924:        # lm_head is not used in llama.cpp, while autoawq will include this tensor in model
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:4971:        # lm_head is not used in llama.cpp, while autoawq will include this tensor in model
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:5066:        # related to https://github.com/ggml-org/llama.cpp/issues/13025
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:5225:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:5306:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:5369:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:5481:        # required by llama.cpp, unused
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/bin/convert_hf_to_gguf.py:7525:        #   in llama.cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/integrations/ggml.py:242:        # See: https://github.com/ggerganov/llama.cpp/blob/2e2f8f093cd4fb6bbb87ba84f6b9684fa082f3fa/convert_hf_to_gguf.py#L3293-L3294
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/integrations/ggml.py:258:        # See: https://github.com/ggml-org/llama.cpp/blob/fe5b78c89670b2f37ecb216306bed3e677b49d9f/convert_hf_to_gguf.py#L3495-L3496
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:90:        # https://github.com/ggerganov/llama.cpp/blob/a38b884c6c4b0c256583acfaaabdf556c62fabea/convert_hf_to_gguf.py#L1402-L1408
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:120:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L1994-L2022
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:145:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L972-L985
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:157:        # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L986-L998
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:187:        # https://github.com/ggerganov/llama.cpp/blob/a38b884c6c4b0c256583acfaaabdf556c62fabea/convert_hf_to_gguf.py#L2060-L2061
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:218:            # https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L2975-L2977
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:227:    # ref : https://github.com/ggerganov/llama.cpp/blob/master/convert_hf_to_gguf.py#L4666
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:238:    # ref: https://github.com/ggerganov/llama.cpp/blob/d79d8f39b4da6deca4aea8bf130c6034c482b320/convert_hf_to_gguf.py#L3191
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:300:            "https://pytorch.org/ and https://github.com/ggerganov/llama.cpp/tree/master/gguf-py for installation instructions."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:327:            "https://github.com/ggerganov/llama.cpp/tree/master/gguf-py#development"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:380:            "https://pytorch.org/ and https://github.com/ggerganov/llama.cpp/tree/master/gguf-py for installation instructions."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:395:    # in llama.cpp mistral models use the same architecture as llama. We need
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/modeling_gguf_pytorch_utils.py:481:        ## llama.cpp defines the layers that are full-attention by looking at num_key_value_heads
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers/generation/utils.py:1277:                # Applied after temperature scaling (see https://github.com/ggerganov/llama.cpp/pull/3841#issuecomment-2073826084)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/transformers-4.57.6.dist-info/METADATA:618:and adjacent modeling libraries (llama.cpp, mlx, ...) which leverage the model definition from `transformers`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:42:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:43:import llama_cpp.llama_chat_format as llama_chat_format
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:45:from llama_cpp.llama_speculative import LlamaDraftModel
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:50:import llama_cpp._internals as internals
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:56:    """High-level Python wrapper for a llama.cpp model."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:66:        split_mode: int = llama_cpp.LLAMA_SPLIT_MODE_LAYER,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:74:        seed: int = llama_cpp.LLAMA_DEFAULT_SEED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:82:        ] = llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:83:        pooling_type: int = llama_cpp.LLAMA_POOLING_TYPE_UNSPECIFIED,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:122:        """Load a llama.cpp model from `model_path`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:127:            >>> import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:128:            >>> model = llama_cpp.Llama(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:136:            >>> import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:137:            >>> model = llama_cpp.Llama(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:151:            split_mode: How to split the model across GPUs. See llama_cpp.LLAMA_SPLIT_* for options.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:164:            rope_scaling_type: RoPE scaling type, from `enum llama_rope_scaling_type`. ref: https://github.com/ggerganov/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:178:            swa_full: use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:187:            tokenizer: Optional tokenizer to override the default tokenizer from llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:206:                llama_cpp.llama_backend_init()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:211:                llama_cpp.GGML_NUMA_STRATEGY_DISTRIBUTE
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:213:                else llama_cpp.GGML_NUMA_STRATEGY_DISABLED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:218:        if self.numa != llama_cpp.GGML_NUMA_STRATEGY_DISABLED:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:220:                llama_cpp.llama_numa_init(self.numa)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:225:        self.model_params = llama_cpp.llama_model_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:234:            if len(self.tensor_split) > llama_cpp.LLAMA_MAX_DEVICES:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:236:                    f"Attempt to split tensors that exceed maximum supported devices. Current LLAMA_MAX_DEVICES={llama_cpp.LLAMA_MAX_DEVICES}"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:239:            FloatArray = ctypes.c_float * llama_cpp.LLAMA_MAX_DEVICES
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:254:                llama_cpp.llama_model_kv_override * kvo_array_len
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:262:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_BOOL
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:267:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_INT
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:272:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_FLOAT
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:281:                    ].tag = llama_cpp.LLAMA_KV_OVERRIDE_TYPE_STR
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:286:                        + llama_cpp.llama_model_kv_override_value.val_str.offset,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:307:        self._seed = seed or llama_cpp.LLAMA_DEFAULT_SEED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:310:        self.context_params = llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:319:            else llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:414:        self._lora_adapter: Optional[llama_cpp.llama_adapter_lora_p] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:417:            self._lora_adapter = llama_cpp.llama_adapter_lora_init(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:429:                llama_cpp.llama_adapter_lora_free(self._lora_adapter)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:434:            if llama_cpp.llama_set_adapter_lora(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:442:            print(llama_cpp.llama_print_system_info().decode("utf-8"), file=sys.stderr)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:490:        # Unfortunately the llama.cpp API does not return metadata arrays, so we can't get template names from tokenizer.chat_templates
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:550:    def ctx(self) -> llama_cpp.llama_context_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:554:    def model(self) -> llama_cpp.llama_model_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:693:            def apply_func(token_data_array: llama_cpp.llama_token_data_array_p):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:704:                    buf=(llama_cpp.llama_token_data * size).from_address(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1022:        logits_all = pooling_type == llama_cpp.LLAMA_POOLING_TYPE_NONE
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1030:            llama_cpp.llama_perf_context_reset(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1044:            llama_cpp.llama_kv_self_clear(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1049:            if pooling_type == llama_cpp.LLAMA_POOLING_TYPE_NONE:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1052:                    ptr = llama_cpp.llama_get_embeddings(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1065:                    ptr = llama_cpp.llama_get_embeddings_seq(self._ctx.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1111:            llama_cpp.llama_perf_context_print(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1115:        llama_cpp.llama_kv_self_clear(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1274:                f"Requested tokens ({len(prompt_tokens)}) exceed context window of {llama_cpp.llama_n_ctx(self.ctx)}"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1340:            if llama_cpp.llama_token_is_eog(self._model.vocab, token):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1779:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1876:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:1976:            min_p: The min-p value to use for minimum p sampling. Minimum P sampling as described in https://github.com/ggerganov/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:2130:        state_size = llama_cpp.llama_get_state_size(self._ctx.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:2136:        n_bytes = llama_cpp.llama_copy_state_data(self._ctx.ctx, llama_state)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:2142:        llama_cpp.ctypes.memmove(llama_state_compact, llama_state, int(n_bytes))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama.py:2169:        if llama_cpp.llama_set_state_data(self._ctx.ctx, llama_state) != state_size:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:12:import llama_cpp.llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:18:    """Base cache class for a llama.cpp model."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:35:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:44:        self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:50:    """Cache for a llama.cpp model using RAM."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:56:            Tuple[int, ...], "llama_cpp.llama.LlamaState"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:70:            (k, llama_cpp.llama.Llama.longest_token_prefix(k, key))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:79:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:91:    def __setitem__(self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:105:    """Cache for a llama.cpp model using disk."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:124:            prefix_len = llama_cpp.llama.Llama.longest_token_prefix(k, key)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:130:    def __getitem__(self, key: Sequence[int]) -> "llama_cpp.llama.LlamaState":
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:135:        value: "llama_cpp.llama.LlamaState" = self.cache.pop(_key)  # type: ignore
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cache.py:144:    def __setitem__(self, key: Sequence[int], value: "llama_cpp.llama.LlamaState"):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:32:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:33:import llama_cpp.llama as llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:34:import llama_cpp.llama_types as llama_types
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:35:import llama_cpp.llama_grammar as llama_grammar
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:71:        # llama.cpp instance
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:94:        # llama.cpp parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:2700:        import llama_cpp.mtmd_cpp as mtmd_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:2882:                n_past = llama_cpp.llama_pos(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:2918:                        new_n_past = llama_cpp.llama_pos(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:2923:                            llama_cpp.llama_pos(llama.n_tokens),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_chat_format.py:2924:                            llama_cpp.llama_seq_id(0),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:15:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:22:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:206:# NOTE: Deprecated and will be removed in the future. (already gone in llama.cpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:752:# //       https://github.com/ggml-org/llama.cpp/pull/7544
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:765:#     // ref: https://github.com/ggml-org/llama.cpp/pull/2054
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:793:#     bool swa_full;    // use full-size SWA cache (https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:795:#                       //       ref: https://github.com/ggml-org/llama.cpp/pull/13845#issuecomment-2924800573
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:798:#                       // ref: https://github.com/ggml-org/llama.cpp/pull/14363
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:2046:#            "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:2057:#            "Use llama_kv_self_seq_pos_max() and llama_kv_self_seq_pos_min() instead (https://github.com/ggml-org/llama.cpp/issues/13793)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:2856:# // TODO: deprecate in favor of llama_get_logits_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:2897:# // TODO: deprecate in favor of llama_get_embeddings_ith() (ref: https://github.com/ggml-org/llama.cpp/pull/14853#issuecomment-3113143522)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:3517:# /// NOTE: This function does not use a jinja parser. It only support a pre-defined list of template. See more: https://github.com/ggml-org/llama.cpp/wiki/Templates-supported-by-llama_chat_apply_template
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:3808:#     "will be removed in the future (see https://github.com/ggml-org/llama.cpp/pull/9896#discussion_r1800920915)");
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:3833:# /// @details Minimum P sampling as described in https://github.com/ggml-org/llama.cpp/pull/3841
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_cpp.py:3984:# /// @details Lazy grammar sampler, introduced in https://github.com/ggml-org/llama.cpp/pull/9639
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_grammar.py:1:"""Python implementation of llama grammar parser directly translated from C++ source file in vendor/llama.cpp/common/grammar-parser.cpp."""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_grammar.py:50:"""llama.cpp gbnf rules from vendor/llama.cpp/grammars"""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_grammar.py:235:"""llama.cpp json-schema to grammar converter from vendor/llama.cpp/examples/json-schema-to-grammar.py"""
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_grammar.py:505:        Output: https://github.com/ggerganov/llama.cpp/blob/master/grammars/README.md
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_tokenizer.py:10:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_tokenizer.py:11:from llama_cpp.llama_types import List
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_tokenizer.py:46:    def __init__(self, llama: llama_cpp.Llama):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llama_tokenizer.py:74:        return cls(llama_cpp.Llama(model_path=path, vocab_only=True))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:23:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:25:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:31:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:71:    [llama_cpp.llama_context_p_ctypes, clip_ctx_p_ctypes],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:75:    ctx_llama: llama_cpp.llama_context_p, ctx_clip: clip_ctx_p, /
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:122:        llama_cpp.llama_context_p_ctypes,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/llava_cpp.py:130:    ctx_llama: llama_cpp.llama_context_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:26:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:28:from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:34:    from llama_cpp._ctypes_extensions import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:111:    [c_char_p, llama_cpp.llama_model_p_ctypes, mtmd_context_params],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:116:    text_model: llama_cpp.llama_model_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:217:    POINTER(llama_cpp.llama_token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:221:) -> Optional["_Pointer[llama_cpp.llama_token]"]:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:259:        llama_cpp.llama_context_p_ctypes,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:261:        llama_cpp.llama_pos,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:262:        llama_cpp.llama_seq_id,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:265:        POINTER(llama_cpp.llama_pos),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:271:    lctx: llama_cpp.llama_context_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:273:    n_past: llama_cpp.llama_pos,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:274:    seq_id: llama_cpp.llama_seq_id,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/mtmd_cpp.py:277:    new_n_past: "_Pointer[llama_cpp.llama_pos]",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:12:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:25:from llama_cpp.server.model import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:28:from llama_cpp.server.settings import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:34:from llama_cpp.server.types import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:45:from llama_cpp.server.errors import RouteErrorHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:136:        title="🦙 llama.cpp Python API",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:137:        version=llama_cpp.__version__,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:163:) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:178:        kwargs["grammar"] = llama_cpp.LlamaGrammar.from_string(body.grammar)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:181:        _min_tokens_logits_processor = llama_cpp.LogitsProcessorList(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:182:            [llama_cpp.MinTokensLogitsProcessor(body.min_tokens, llama.token_eos())]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:226:    llama: llama_cpp.Llama,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:269:        llama_cpp.CreateCompletionResponse,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:306:) -> llama_cpp.Completion:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:337:                llama_call=llama_cpp.Llama.__call__,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:380:    response_model=Union[llama_cpp.ChatCompletion, str],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:480:) -> llama_cpp.ChatCompletion:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/app.py:506:                llama_call=llama_cpp.Llama.create_chat_completion,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/errors.py:19:from llama_cpp.server.types import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/errors.py:105:    # key: regex pattern for original error message from llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:7:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:8:import llama_cpp.llama_speculative as llama_speculative
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:9:import llama_cpp.llama_tokenizer as llama_tokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:11:from llama_cpp.server.settings import ModelSettings
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:24:        self._current_model: Optional[llama_cpp.Llama] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:36:    def __call__(self, model: Optional[str] = None) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:74:    def load_llama_from_model_settings(settings: ModelSettings) -> llama_cpp.Llama:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:80:                    llama_cpp.llama_chat_format.Llava15ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:87:                chat_handler = llama_cpp.llama_chat_format.Llava15ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:94:                    llama_cpp.llama_chat_format.ObsidianChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:101:                chat_handler = llama_cpp.llama_chat_format.ObsidianChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:108:                    llama_cpp.llama_chat_format.Llava16ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:115:                chat_handler = llama_cpp.llama_chat_format.Llava16ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:122:                    llama_cpp.llama_chat_format.MoondreamChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:129:                chat_handler = llama_cpp.llama_chat_format.MoondreamChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:136:                    llama_cpp.llama_chat_format.NanoLlavaChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:143:                chat_handler = llama_cpp.llama_chat_format.NanoLlavaChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:150:                    llama_cpp.llama_chat_format.Llama3VisionAlpha.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:157:                chat_handler = llama_cpp.llama_chat_format.Llama3VisionAlpha(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:164:                    llama_cpp.llama_chat_format.MiniCPMv26ChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:171:                chat_handler = llama_cpp.llama_chat_format.MiniCPMv26ChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:178:                    llama_cpp.llama_chat_format.Qwen25VLChatHandler.from_pretrained(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:185:                chat_handler = llama_cpp.llama_chat_format.Qwen25VLChatHandler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:193:                llama_cpp.llama_chat_format.hf_autotokenizer_to_chat_completion_handler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:201:            chat_handler = llama_cpp.llama_chat_format.hf_tokenizer_config_to_chat_completion_handler(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:205:        tokenizer: Optional[llama_cpp.BaseLlamaTokenizer] = None
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:242:                llama_cpp.Llama.from_pretrained,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:247:            create_fn = llama_cpp.Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:306:                cache = llama_cpp.LlamaDiskCache(capacity_bytes=settings.cache_size)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/model.py:310:                cache = llama_cpp.LlamaRAMCache(capacity_bytes=settings.cache_size)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:11:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:34:        default=llama_cpp.LLAMA_SPLIT_MODE_LAYER,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:50:        default=llama_cpp.llama_supports_mmap(),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:54:        default=llama_cpp.llama_supports_mlock(),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:67:        default=llama_cpp.LLAMA_DEFAULT_SEED, description="Random seed. -1 for random."
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:74:        default=512, ge=1, description="The physical batch size used by llama.cpp"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/settings.py:87:        default=llama_cpp.LLAMA_ROPE_SCALING_TYPE_UNSPECIFIED
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:8:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:146:    # llama.cpp specific parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:193:    messages: List[llama_cpp.ChatCompletionRequestMessage] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:196:    functions: Optional[List[llama_cpp.ChatCompletionFunction]] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:200:    function_call: Optional[llama_cpp.ChatCompletionRequestFunctionCall] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:204:    tools: Optional[List[llama_cpp.ChatCompletionTool]] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:208:    tool_choice: Optional[llama_cpp.ChatCompletionToolChoiceOption] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:235:    response_format: Optional[llama_cpp.ChatCompletionRequestResponseFormat] = Field(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/types.py:244:    # llama.cpp specific parameters
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:1:"""Example FastAPI server for llama.cpp.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:12:uvicorn llama_cpp.server.app:create_app --reload
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:18:python3 -m llama_cpp.server
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:33:from llama_cpp.server.app import create_app
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:34:from llama_cpp.server.settings import (
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/server/__main__.py:40:from llama_cpp.server.cli import add_args_from_model, parse_model_from_args
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_ctypes_extensions.py:26:    # for llamacpp) and "llama" (default name for this repo)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_ggml.py:8:import llama_cpp._ctypes_extensions as ctypes_ext
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:25:import llama_cpp.llama_cpp as llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:32:    """Intermediate Python wrapper for a llama.cpp llama_model.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:39:        params: llama_cpp.llama_model_params,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:53:            model = llama_cpp.llama_model_load_from_file(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:60:        vocab = llama_cpp.llama_model_get_vocab(model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:72:            llama_cpp.llama_model_free(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:79:            # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:81:                llama_cpp.llama_sampler_chain_remove(self.sampler, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:89:        return llama_cpp.llama_vocab_type(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:92:        return llama_cpp.llama_vocab_n_tokens(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:95:        return llama_cpp.llama_model_n_ctx_train(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:98:        return llama_cpp.llama_model_n_embd(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:101:        return llama_cpp.llama_model_rope_freq_scale_train(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:105:        llama_cpp.llama_model_desc(self.model, buf, 1024)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:109:        return llama_cpp.llama_model_size(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:112:        return llama_cpp.llama_model_n_params(self.model)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:115:        raise NotImplementedError("get_tensor is not implemented in llama.cpp")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:120:        return llama_cpp.llama_vocab_get_text(self.vocab, token).decode("utf-8")
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:123:        return llama_cpp.llama_vocab_get_score(self.vocab, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:126:        return llama_cpp.llama_vocab_get_attr(self.vocab, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:131:        return llama_cpp.llama_vocab_bos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:134:        return llama_cpp.llama_vocab_eos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:137:        return llama_cpp.llama_vocab_cls(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:140:        return llama_cpp.llama_vocab_sep(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:143:        return llama_cpp.llama_vocab_nl(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:146:        return llama_cpp.llama_vocab_fim_pre(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:149:        return llama_cpp.llama_vocab_fim_mid(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:152:        return llama_cpp.llama_vocab_fim_suf(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:155:        return llama_cpp.llama_vocab_eot(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:158:        return llama_cpp.llama_vocab_get_add_bos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:161:        return llama_cpp.llama_vocab_get_add_eos(self.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:167:        tokens = (llama_cpp.llama_token * n_ctx)()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:168:        n_tokens = llama_cpp.llama_tokenize(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:173:            tokens = (llama_cpp.llama_token * n_tokens)()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:174:            n_tokens = llama_cpp.llama_tokenize(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:185:        llama_cpp.llama_token_to_piece(self.vocab, token, buf, 32, 0, special)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:193:            n = llama_cpp.llama_token_to_piece(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:194:                self.vocab, llama_cpp.llama_token(token), buffer, size, 0, special
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:214:        for i in range(llama_cpp.llama_model_meta_count(self.model)):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:215:            nbytes = llama_cpp.llama_model_meta_key_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:221:                nbytes = llama_cpp.llama_model_meta_key_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:225:            nbytes = llama_cpp.llama_model_meta_val_str_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:231:                nbytes = llama_cpp.llama_model_meta_val_str_by_index(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:241:        return llama_cpp.llama_model_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:245:    """Intermediate Python wrapper for a llama.cpp llama_context.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:252:        params: llama_cpp.llama_context_params,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:260:        ctx = llama_cpp.llama_init_from_model(self.model.model, self.params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:266:        self.memory = llama_cpp.llama_get_memory(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:272:            llama_cpp.llama_free(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:284:        return llama_cpp.llama_n_ctx(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:287:        return llama_cpp.llama_pooling_type(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:291:        llama_cpp.llama_memory_clear(self.memory, True)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:296:        llama_cpp.llama_memory_seq_rm(self.memory, seq_id, p0, p1)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:300:        llama_cpp.llama_memory_seq_cp(self.memory, seq_id_src, seq_id_dst, p0, p1)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:304:        llama_cpp.llama_memory_seq_keep(self.memory, seq_id)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:308:        llama_cpp.llama_memory_seq_add(self.memory, seq_id, p0, p1, shift)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:311:        return llama_cpp.llama_state_get_size(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:322:        return_code = llama_cpp.llama_decode(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:330:        return_code = llama_cpp.llama_encode(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:338:        llama_cpp.llama_set_n_threads(self.ctx, n_threads, n_threads_batch)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:341:        return llama_cpp.llama_get_logits(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:344:        return llama_cpp.llama_get_logits_ith(self.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:347:        return llama_cpp.llama_get_embeddings(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:350:        return llama_cpp.llama_get_embeddings_ith(self.ctx, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:353:        return llama_cpp.llama_get_embeddings_seq(self.ctx, seq_id)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:363:        last_tokens_data: "llama_cpp.Array[llama_cpp.llama_token]",
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:400:        mu: llama_cpp.CtypesPointerOrRef[ctypes.c_float],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:409:        mu: llama_cpp.CtypesPointerOrRef[ctypes.c_float],
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:424:        llama_cpp.llama_perf_context_reset(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:427:        llama_cpp.llama_perf_context_print(self.ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:433:        return llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:446:        batch = llama_cpp.llama_batch_init(self._n_tokens, self.embd, self.n_seq_max)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:457:            llama_cpp.llama_batch_free(self.batch)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:508:        self.candidates = llama_cpp.llama_token_data_array(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:509:            data=self.candidates_data.ctypes.data_as(llama_cpp.llama_token_data_p),
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:572:    cur: list[llama_cpp.llama_token_data] = field(default_factory=list)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:613:        self, apply_func: Callable[[llama_cpp.llama_token_data_array], None]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:618:            sampler: llama_cpp.llama_sampler_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:619:            cur_p: llama_cpp.llama_token_data_array_p,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:623:        def free_wrapper(sampler: llama_cpp.llama_sampler_p):
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:626:        sampler_i = llama_cpp.llama_sampler_i()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:627:        sampler_i.apply = llama_cpp.llama_sampler_i_apply(apply_wrapper)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:630:        sampler_i.name = llama_cpp.llama_sampler_i_name(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:631:        sampler_i.accept = llama_cpp.llama_sampler_i_accept(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:632:        sampler_i.reset = llama_cpp.llama_sampler_i_reset(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:633:        sampler_i.clone = llama_cpp.llama_sampler_i_clone(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:634:        sampler_i.free = llama_cpp.llama_sampler_i_free(0)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:636:        self.sampler = llama_cpp.llama_sampler()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:640:    def get_sampler(self) -> llama_cpp.llama_sampler_p:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:646:        params = llama_cpp.llama_sampler_chain_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:647:        self.sampler = llama_cpp.llama_sampler_chain_init(params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:653:                # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:655:                    llama_cpp.llama_sampler_chain_remove(self.sampler, i)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:656:                llama_cpp.llama_sampler_free(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:668:        sampler = llama_cpp.llama_sampler_init_greedy()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:669:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:672:        sampler = llama_cpp.llama_sampler_init_dist(seed)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:673:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:676:        sampler = llama_cpp.llama_sampler_init_softmax()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:677:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:680:        sampler = llama_cpp.llama_sampler_init_top_k(k)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:681:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:684:        sampler = llama_cpp.llama_sampler_init_top_p(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:685:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:688:        sampler = llama_cpp.llama_sampler_init_min_p(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:689:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:692:        sampler = llama_cpp.llama_sampler_init_typical(p, min_keep)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:693:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:696:        sampler = llama_cpp.llama_sampler_init_temp(temp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:697:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:700:        sampler = llama_cpp.llama_sampler_init_temp_ext(t, delta, exponent)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:701:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:704:        sampler = llama_cpp.llama_sampler_init_xtc(p, t, min_keep, seed)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:705:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:708:        sampler = llama_cpp.llama_sampler_init_top_n_sigma(n)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:709:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:712:        sampler = llama_cpp.llama_sampler_init_mirostat(n_vocab, seed, tau, eta, m)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:713:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:716:        sampler = llama_cpp.llama_sampler_init_mirostat_v2(seed, tau, eta)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:717:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:720:        sampler = llama_cpp.llama_sampler_init_grammar(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:723:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:738:        token_array = (llama_cpp.llama_token * len(trigger_tokens))(*trigger_tokens)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:740:        sampler = llama_cpp.llama_sampler_init_grammar_lazy_patterns(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:749:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:758:        sampler = llama_cpp.llama_sampler_init_penalties(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:764:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:781:        sampler = llama_cpp.llama_sampler_init_dry(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:791:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:799:        bias_array = (llama_cpp.llama_logit_bias * len(logit_bias))()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:804:        sampler = llama_cpp.llama_sampler_init_logit_bias(
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:809:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:812:        sampler = llama_cpp.llama_sampler_init_infill(model.vocab)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:813:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:816:        self, apply_func: Callable[[llama_cpp.llama_token_data_array], None]
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:820:        llama_cpp.llama_sampler_chain_add(self.sampler, sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:821:        # NOTE: Must remove custom samplers before free or llama.cpp will try to free them
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:823:            (llama_cpp.llama_sampler_chain_n(self.sampler) - 1, custom_sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:827:        return llama_cpp.llama_sampler_get_seed(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:830:        return llama_cpp.llama_sampler_sample(self.sampler, ctx.ctx, idx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:833:        llama_cpp.llama_sampler_accept(self.sampler, token)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:836:        llama_cpp.llama_sampler_reset(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:843:        cloned_sampler = llama_cpp.llama_sampler_clone(self.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_internals.py:852:                llama_cpp.llama_sampler_free(new_sampler.sampler)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_logger.py:5:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_logger.py:29:@llama_cpp.llama_log_callback
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/_logger.py:43:llama_cpp.llama_log_set(llama_log_callback, ctypes.c_void_p(0))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp/__init__.py:1:from .llama_cpp import *
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:2:Name: llama_cpp_python
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:4:Summary: Python bindings for the llama.cpp library
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:48:Requires-Dist: llama_cpp_python[dev,server,test]; extra == "all"
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:55:#  Python Bindings for [`llama.cpp`](https://github.com/ggerganov/llama.cpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:65:Simple Python bindings for **@ggerganov's** [`llama.cpp`](https://github.com/ggerganov/llama.cpp) library.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:71:    - [LangChain compatibility](https://python.langchain.com/docs/integrations/llms/llamacpp)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:72:    - [LlamaIndex compatibility](https://docs.llamaindex.ai/en/stable/examples/llm/llama_2_llama_cpp.html)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:97:This will also build `llama.cpp` from source and install it alongside this python package.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:112:`llama.cpp` supports a number of hardware acceleration backends to speed up inference as well as backend specific options. See the [llama.cpp README](https://github.com/ggerganov/llama.cpp#build) for a full list.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:114:All `llama.cpp` cmake build options can be set via the `CMAKE_ARGS` environment variable or via the `--config-settings / -C` cli flag during installation.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:275:If you run into issues where it complains it can't find `'nmake'` `'?'` or CMAKE_C_COMPILER, you can extract w64devkit as [mentioned in llama.cpp repo](https://github.com/ggerganov/llama.cpp#openblas) and add those manually to CMAKE_ARGS before running `pip` install:
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:299:Otherwise, while installing it will build the llama.cpp x86 version which will be 10x slower on Apple Silicon (M1) Mac.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:320:The high-level API provides a simple managed interface through the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:325:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:366:Text completion is available through the [`__call__`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.__call__) and [`create_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_completion) methods of the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:370:You can download `Llama` models in `gguf` format directly from Hugging Face using the [`from_pretrained`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.from_pretrained) method.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:381:By default [`from_pretrained`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.from_pretrained) will download the model to the huggingface cache directory, you can then manage installed model files with the [`huggingface-cli`](https://huggingface.co/docs/huggingface_hub/en/guides/cli) tool.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:399:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:415:Chat completion is available through the [`create_chat_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion) method of the [`Llama`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama) class.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:417:For OpenAI API v1 compatibility, you use the [`create_chat_completion_openai_v1`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion_openai_v1) method which will return pydantic models instead of dicts.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:422:To constrain chat responses to only valid JSON or a specific JSON Schema use the `response_format` argument in [`create_chat_completion`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_chat_completion).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:429:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:451:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:478:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:527:Due to discrepancies between llama.cpp and HuggingFace's tokenizers, it is required to provide HF Tokenizer for functionary. The `LlamaHFTokenizer` class can be initialized and passed into the Llama class. This will override the default llama.cpp tokenizer used in Llama class. The tokenizer files are already included in the respective HF repositories hosting the gguf files.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:530:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:531:from llama_cpp.llama_tokenizer import LlamaHFTokenizer
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:563:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:564:from llama_cpp.llama_chat_format import Llava15ChatHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:588:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:589:from llama_cpp.llama_chat_format import MoondreamChatHandler
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:661:from llama_cpp import Llama
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:662:from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:672:To generate text embeddings use [`create_embedding`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.create_embedding) or [`embed`](https://llama-cpp-python.readthedocs.io/en/latest/api-reference/#llama_cpp.Llama.embed). Note that you must pass `embedding=True` to the constructor upon model creation for these to work properly.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:675:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:677:llm = llama_cpp.Llama(model_path="path/to/model.gguf", embedding=True)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:705:This allows you to use llama.cpp compatible models with any OpenAI compatible client (language libraries, services, etc).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:711:python3 -m llama_cpp.server --model models/7B/llama-model.gguf
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:718:python3 -m llama_cpp.server --model models/7B/llama-model.gguf --n_gpu_layers 35
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:723:To bind to `0.0.0.0` to enable remote connections, use `python3 -m llama_cpp.server --host 0.0.0.0`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:729:python3 -m llama_cpp.server --model models/7B/llama-model.gguf --chat_format chatml
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:733:For possible options, see [llama_cpp/llama_chat_format.py](llama_cpp/llama_chat_format.py) and look for lines starting with "@register_chat_format".
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:738:python3 -m llama_cpp.server --hf_model_repo_id Qwen/Qwen2-0.5B-Instruct-GGUF --model '*q8_0.gguf'
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:762:The low-level API is a direct [`ctypes`](https://docs.python.org/3/library/ctypes.html) binding to the C API provided by `llama.cpp`.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:763:The entire low-level API can be found in [llama_cpp/llama_cpp.py](https://github.com/abetlen/llama-cpp-python/blob/master/llama_cpp/llama_cpp.py) and directly mirrors the C API in [llama.h](https://github.com/ggerganov/llama.cpp/blob/master/llama.h).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:768:import llama_cpp
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:770:llama_cpp.llama_backend_init(False) # Must be called once at the start of each program
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:771:params = llama_cpp.llama_context_default_params()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:773:model = llama_cpp.llama_load_model_from_file(b"./models/7b/llama-model.gguf", params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:774:ctx = llama_cpp.llama_new_context_with_model(model, params)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:777:tokens = (llama_cpp.llama_token * int(max_tokens))()
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:778:n_tokens = llama_cpp.llama_tokenize(ctx, b"Q: Name the planets in the solar system? A: ", tokens, max_tokens, llama_cpp.c_bool(True))
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:779:llama_cpp.llama_free(ctx)
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:829:You can also test out specific commits of `llama.cpp` by checking out the desired commit in the `vendor/llama.cpp` submodule and then running `make clean` and `pip install -e .` again. Any changes in the `llama.h` API will require
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:830:changes to the `llama_cpp/llama_cpp.py` file to match the new API (additional changes may be required elsewhere).
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:837:The reason for this is that `llama.cpp` is built with compiler optimizations that are specific to your system.
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:845:### How does this compare to other Python bindings of `llama.cpp`?
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:849:- Provide a simple process to install `llama.cpp` and access the full C API in `llama.h` from Python
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/METADATA:850:- Provide a high-level Python API that can be used as a drop-in replacement for the OpenAI API so existing apps can be easily ported to use `llama.cpp`
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:33:llama_cpp/__init__.py,sha256=TCpa8_yW00am6A9uqrhCmLdE2u-pMAQMtm2raiSVbOE,70
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:34:llama_cpp/__pycache__/__init__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:35:llama_cpp/__pycache__/_ctypes_extensions.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:36:llama_cpp/__pycache__/_ggml.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:37:llama_cpp/__pycache__/_internals.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:38:llama_cpp/__pycache__/_logger.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:39:llama_cpp/__pycache__/_utils.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:40:llama_cpp/__pycache__/llama.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:41:llama_cpp/__pycache__/llama_cache.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:42:llama_cpp/__pycache__/llama_chat_format.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:43:llama_cpp/__pycache__/llama_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:44:llama_cpp/__pycache__/llama_grammar.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:45:llama_cpp/__pycache__/llama_speculative.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:46:llama_cpp/__pycache__/llama_tokenizer.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:47:llama_cpp/__pycache__/llama_types.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:48:llama_cpp/__pycache__/llava_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:49:llama_cpp/__pycache__/mtmd_cpp.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:50:llama_cpp/_ctypes_extensions.py,sha256=nlJBgy_rYePEObDp5Nmp_056alSwgJqPWZXwF12EGHY,4085
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:51:llama_cpp/_ggml.py,sha256=DfF0pvbdo7iIC4sJynLA4efGAYKzTMmia25P9dXLYuQ,369
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:52:llama_cpp/_internals.py,sha256=yk3-wH3ZnzvOiPW4Wr7KAjcbBtL5rI48ITHowolxk2I,29562
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:53:llama_cpp/_logger.py,sha256=ccphvqDhQjiFRluIcG7aVOoCs4EKnvGrFC5mvEm8k1g,1309
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:54:llama_cpp/_utils.py,sha256=adbuDQP6KlQRpvQPSbOvfD7yiqR5VzmedauQTRtM1Yc,2260
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:55:llama_cpp/lib/libggml-base.so,sha256=Qs2IXq4_jVYc1Eq0EWRIebZyEvBmrYquTKXOPb9eagU,615864
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:56:llama_cpp/lib/libggml-cpu.so,sha256=y5PFJCVnk_xU9NOhKhs6BV3UdoZ7kFTkwRgo3cLH6uw,967608
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:57:llama_cpp/lib/libggml.so,sha256=tCnOnlbQgexMrQ_YOXFXmARbEQ6PHfk2q1NQqALkODo,47624
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:58:llama_cpp/lib/libllama.so,sha256=ks4mIQZFkKQnWacuWIHm1d1wEd3I7NItqv28LmmCMws,2150632
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:59:llama_cpp/lib/libmtmd.so,sha256=qw0Vqrd9FK5aGqtN8j1RxTHhTiVFmzVetwsyC8NRfEg,722296
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:60:llama_cpp/llama.py,sha256=M0sV8W7DHeZa3qWMhdvQQFf4h0nK3manrfQmhMTQENg,96173
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:61:llama_cpp/llama_cache.py,sha256=o8sQHL1eBviDZrEqc8ExpUwk-DvICFtkxQNajGcb3Gk,5010
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:62:llama_cpp/llama_chat_format.py,sha256=Nd4E_D4Wth9tcETNlh5pgCUsne8s4k9Y_NUmWqw44Yw,157215
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:63:llama_cpp/llama_cpp.py,sha256=Syf46SU3z9Aa4gNBdFxaInBL6BH_vz7576ZrpkRASSE,152717
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:64:llama_cpp/llama_grammar.py,sha256=TTlpkZeQn0qpj0UIbIJL0FIfvrJ8eq7iSacjxi4dDdg,32913
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:65:llama_cpp/llama_speculative.py,sha256=N9q_Humq0B2C2m1eafvAo3zevXrFvAQsrI6tTj1vtro,2088
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:66:llama_cpp/llama_tokenizer.py,sha256=SC5X2lY91Tf7qMXSrgncNSwwVN_YYilXosuRm4R4yp8,3876
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:67:llama_cpp/llama_types.py,sha256=EDqRqfiQ1_MUwfhRc65eHv0sEhOSAv_UMH-3VMBVhZ4,8666
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:68:llama_cpp/llava_cpp.py,sha256=5tDZrC9Blb71AhpJ074CavkujwZQFUg6y-Z2QsLA-0E,4552
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:69:llama_cpp/mtmd_cpp.py,sha256=5ShRxeaq89DgwWEnHD-qLXJJ_yg3gb6kcr9yX1XqeTA,8834
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:70:llama_cpp/py.typed,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:71:llama_cpp/server/__init__.py,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:72:llama_cpp/server/__main__.py,sha256=HL9yvPX0l7Fy_B4t7JbokucU9CX5UnCx4oRUnBiktpY,2849
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:73:llama_cpp/server/__pycache__/__init__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:74:llama_cpp/server/__pycache__/__main__.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:75:llama_cpp/server/__pycache__/app.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:76:llama_cpp/server/__pycache__/cli.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:77:llama_cpp/server/__pycache__/errors.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:78:llama_cpp/server/__pycache__/model.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:79:llama_cpp/server/__pycache__/settings.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:80:llama_cpp/server/__pycache__/types.cpython-313.pyc,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:81:llama_cpp/server/app.py,sha256=epaKb0vzhlJNiu95zZ7tgVHfwILEPS6G3sIBKX5JUNo,19572
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:82:llama_cpp/server/cli.py,sha256=mW8NAy8-Gcp-uCSyvLNIaxARIntpPcD1_K1kciHRhSQ,3268
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:83:llama_cpp/server/errors.py,sha256=yl-VMzgp1Y0jO3pME35475nET1RCwnRtshPs9IHhc7M,7164
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:84:llama_cpp/server/model.py,sha256=osPi81ohIN58AAU_sE3oY6ew6iwfTnwVBHznY8MU6NQ,13556
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:85:llama_cpp/server/settings.py,sha256=zVci46BjUKx0gSJGKjIR8E9oWrrj5s3Hqj2hLn5Xd3c,8566
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:86:llama_cpp/server/types.py,sha256=psWzuEjfF4U3kks0HRE67uizMjml8gOf-zXvpsllIrs,12216
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:87:llama_cpp_python-0.3.16.dist-info/INSTALLER,sha256=zuuue4knoyJ-UwPPXg8fezS7VCrXJQrAP7zeNuwvFQg,4
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:88:llama_cpp_python-0.3.16.dist-info/METADATA,sha256=EkGG9Yg7178a2xyzgPwBLZ1N5dy24wN1opjgsMD1a0E,33608
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:89:llama_cpp_python-0.3.16.dist-info/RECORD,,
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:90:llama_cpp_python-0.3.16.dist-info/REQUESTED,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:91:llama_cpp_python-0.3.16.dist-info/WHEEL,sha256=K7nq3Hjz-S557B68yjvMEO-oGsD5aE0lD8QXdqCuqYk,109
/mnt/Development/KIRO/AI-Karen/.virEnv/lib64/python3.13/site-packages/llama_cpp_python-0.3.16.dist-info/RECORD:92:llama_cpp_python-0.3.16.dist-info/licenses/LICENSE.md,sha256=xHn7EaZqhf7SAEoX3Rs-RKGFjFZLFnrssg_2bLQi7XU,1069
/mnt/Development/KIRO/AI-Karen/setup/poetry.lock:2535:description = "Python bindings for the llama.cpp library"
/mnt/Development/KIRO/AI-Karen/setup/poetry.lock:2540:    {file = "llama_cpp_python-0.3.16.tar.gz", hash = "sha256:34ed0f9bd9431af045bb63d9324ae620ad0536653740e9bb163a2e1fcb973be6"},
/mnt/Development/KIRO/AI-Karen/setup/poetry.lock:2550:all = ["llama_cpp_python[dev,server,test]"]

FAIL: legacy llama.cpp references remain.

## Direct Provider Call Sites

/mnt/Development/KIRO/AI-Karen/.kilo/2025-12-21_intelligent-fallback-system/enhanced-technical-specifications.md:582:                        provider.generate_text("health check", max_tokens=10),

FAIL: direct provider call sites remain.

## Runtime Authority

ModelManager: /mnt/Development/KIRO/AI-Karen/src/ai_karen_engine/core/model_runtime/model_manager.py:57:class ModelManager:
vLLM runtime: /mnt/Development/KIRO/AI-Karen/src/ai_karen_engine/inference/vllm_runtime.py:19:class VLLMRuntime:
Transformers runtime: /mnt/Development/KIRO/AI-Karen/src/ai_karen_engine/inference/transformers_runtime.py:20:class TransformersRuntime:

AUDIT ONLY: no files changed.

Report written to: /mnt/Development/KIRO/AI-Karen/runtime_refactor_reports/runtime_refactor_20260424_074711.md
