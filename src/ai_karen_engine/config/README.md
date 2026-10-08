# Config Code System - `src/ai_karen_engine/config/`

## Overview

This directory contains the **canonical configuration code system** for AI-Karen. It owns all runtime configuration logic, loading, validation, and management. This is the **only active config system** in the application - there are no competing or parallel config architectures.

## Architecture Principles

- **Single Source of Truth**: All config logic resides here
- **DRY (Don't Repeat Yourself)**: No duplicate config code elsewhere
- **Explicit Separation**: Code (this directory) vs Assets (`config_assets/`)
- **Safe Loading**: Centralized validation and error handling
- **Observable**: Config access is logged and trackable
- **Startup Validatable**: Pre-boot config validation happens here

## Directory Structure & File Purposes

### Canonical Assets (within config code system)

#### `settings.json`
**Purpose**: UI and copilot-specific settings configuration.

**Structure**:
```json
{
  "ui_settings": {
    "theme": "dark",
    "show_debug_info": false
  },
  "copilot_settings": {
    "enabled": true,
    "max_suggestions": 5
  }
}
```

**Usage**: Loaded by the settings manager for UI/copilot configuration. This is a canonical asset that belongs in the config code system because it's tightly coupled with the settings management logic.

#### `plugin_schema.json`
**Purpose**: JSON schema for validating plugin configurations.

**Usage**: Used by the plugin system for configuration validation. This schema defines the expected structure for plugin configs.

### Core Management

#### `config_manager.py`
**Purpose**: Main configuration management system for AI-Karen runtime.

**Responsibilities**:
- Loads and manages the main application configuration (`config_assets/config.json`)
- Provides thread-safe config access and updates
- Handles environment variable overrides
- Manages config observers for hot-reload capabilities
- Provides backup/restore functionality
- Validates config schemas and constraints

**Usage**:
```python
from ai_karen_engine.config.config_manager import get_config, save_config

# Get current config
config = get_config()

# Access nested config values
provider = config.llm.default_provider
model = config.llm.default_model

# Update config
config.llm.default_model = "new-model"
save_config()
```

**Key Classes**:
- `AIKarenConfig`: Main application config dataclass
- `LLMConfig`: LLM provider and model settings
- `DatabaseConfig`: Database connection settings
- `SecurityConfig`: Authentication and security settings

#### `config_asset_loaders.py`
**Purpose**: Centralized loaders for static configuration assets.

**Responsibilities**:
- Provides canonical functions to load config assets from `config_assets/`
- Handles file parsing, validation, and fallback logic
- Ensures consistent asset loading across the application
- Provides logging and error handling for asset access

**Available Loaders**:
- `load_optimization_config()`: Loads `config_assets/optimization_config.json`
- `load_permissions_config()`: Loads `config_assets/permissions.json`
- `load_model_runtime_discovery_config()`: Loads model runtime discovery configuration
- `load_extension_configs()`: Loads all YAML files from `config_assets/extensions/`
- `load_memory_policy_config()`: Loads `config_assets/memory.yml`
- `load_llm_profiles_config()`: Loads `config_assets/llm_profiles.yml`
- `load_performance_config()`: Loads `config_assets/performance.yml`
- `load_deployment_config()`: Loads `config_assets/services.yml`

**Usage**:
```python
from ai_karen_engine.config import load_permissions_config

perms = load_permissions_config()
# Returns dict with role_permissions or empty dict if file missing
```

### Web Search Provider Configuration

#### `web_search.py`
**Purpose**: Canonical defaults and merge logic for live web-search providers.

**Runtime authority**:
- Shipped provider configuration lives at the root `search` key in `config_assets/config.json`.
- `WebSearchProviderRegistry` consumes this canonical configuration for enablement, priority, endpoints, and provider selection.
- Higher numeric `priority` wins among enabled, healthy, policy-permitted providers unless a permitted provider is explicitly requested.
- Legacy `plugins.intelligent-search.search` configuration is migrated into root `search` during config validation and removed from the plugin section. New code must not write or read provider settings from the legacy location.
- Plugin manifests do not own provider routing or availability.

**Environment override**:
`KARI_SEARCH` accepts a JSON object and overrides the root `search` configuration through the standard ConfigManager environment adapter. Example:

```bash
export KARI_SEARCH='{"duckduckgo":{"enabled":false},"wikipedia":{"enabled":true,"priority":200}}'
```

Provider credentials belong in validated runtime configuration or secret/environment adapters. Do not hardcode credentials in manifests, UI code, or search clients.

### Provider & Runtime Management

#### `llm_provider_config.py`
**Purpose**: Configuration management for LLM providers.

**Responsibilities**:
- Loads and validates provider configurations
- Manages provider authentication settings
- Handles provider-specific parameters and constraints
- Provides provider discovery and validation
- Supports hot-reload of provider configurations

**Key Features**:
- Provider registry management
- Authentication credential handling
- Rate limiting and quota management
- Provider health monitoring integration

#### `runtime_provider_manager.py`
**Purpose**: Runtime selection and management of LLM providers.

**Responsibilities**:
- Implements provider selection algorithms based on task requirements
- Manages provider fallback chains
- Handles provider availability and health checks
- Provides runtime provider switching capabilities
- Integrates with performance monitoring

**Key Classes**:
- `RuntimeProviderManager`: Main provider selection logic
- Provider scoring and ranking algorithms
- Runtime compatibility validation

#### `provider_authentication.py`
**Purpose**: Authentication and credential management for LLM providers.

**Responsibilities**:
- Manages API keys and authentication tokens
- Handles credential encryption and secure storage
- Provides credential validation and rotation
- Integrates with secret management systems
- Supports multiple authentication methods per provider

### Profile & User Management

#### `profile_manager.py`
**Purpose**: Management of LLM profiles and user-specific configurations.

**Responsibilities**:
- Loads profile configurations from `config_assets/llm_profiles.yml`
- Manages user profile assignments and preferences
- Handles profile validation and compatibility checking
- Supports profile switching and customization
- Provides default profile fallbacks

**Key Classes**:
- `ProfileManager`: Main profile management logic
- Profile validation and migration utilities

#### `user_profiles.py`
**Purpose**: User profile management and task assignment logic.

**Responsibilities**:
- Manages user-specific LLM provider assignments
- Handles task-to-provider routing based on user profiles
- Provides profile-based performance optimization
- Supports user preference persistence
- Integrates with authentication systems

**Key Classes**:
- `UserProfilesManager`: User profile lifecycle management
- `UserProfile`: Individual user configuration model

### Model & Registry Management

#### `model_registry.py`
**Purpose**: Registry for available models and their metadata.

**Responsibilities**:
- Maintains catalog of available models across providers
- Provides model capability and compatibility information
- Handles model version management
- Supports model discovery and selection
- Integrates with model validation systems

### Performance & Optimization

#### `performance_config.py`
**Purpose**: Performance optimization configuration management.

**Responsibilities**:
- Loads performance settings from `config_assets/performance.yml`
- Manages optimization parameters and thresholds
- Handles performance monitoring integration
- Provides performance-based provider selection
- Supports dynamic performance tuning

#### `hot_reload_service.py`
**Purpose**: Hot-reload functionality for configuration changes.

**Responsibilities**:
- Monitors config files for changes
- Provides zero-downtime config updates
- Handles config validation during reload
- Manages reload event distribution
- Supports rollback capabilities

### Deployment & Integration

#### `deployment_config_manager.py`
**Purpose**: Deployment-specific configuration management.

**Responsibilities**:
- Loads deployment configurations from `config_assets/services.yml`
- Manages service discovery and registration
- Handles deployment environment detection
- Provides deployment-specific overrides
- Supports multi-environment configurations

#### `deployment_integration.py`
**Purpose**: Integration logic for deployment environments.

**Responsibilities**:
- Manages deployment-specific initialization
- Handles environment-specific configuration
- Provides deployment readiness validation
- Supports deployment automation integration
- Manages deployment lifecycle events

#### `deployment_validator.py`
**Purpose**: Validation of deployment configurations.

**Responsibilities**:
- Validates deployment configuration schemas
- Checks deployment environment compatibility
- Performs deployment readiness assessments
- Provides deployment validation reports
- Supports pre-deployment checks

### Validation & Startup

#### `startup_validation.py`
**Purpose**: Pre-startup configuration validation.

**Responsibilities**:
- Validates all configuration before application boot
- Checks config consistency and completeness
- Performs dependency validation
- Provides startup validation reports
- Prevents startup with invalid configurations

## Usage Guidelines

### For Developers

1. **Never import config directly from `config_assets/`**: Always use the canonical loaders in this package
2. **Add new config logic here**: If you need new config management features, add them to this package
3. **Use canonical loaders**: Import from `ai_karen_engine.config` for asset loading
4. **Validate early**: Use startup validation to catch config issues before runtime
5. **Log config access**: Config operations should be observable for debugging

### For Configuration Management

1. **Single point of control**: All config changes flow through these modules
2. **Version control**: Config logic changes are tracked in git
3. **Testing**: Config logic is unit-tested like other code
4. **Documentation**: Config behavior is documented and versioned

### For Runtime Access

```python
# Correct: Use canonical config system
from ai_karen_engine.config import get_config, load_permissions_config

config = get_config()
perms = load_permissions_config()

# Incorrect: Direct file access (breaks encapsulation)
import json
with open('config_assets/permissions.json') as f:
    perms = json.load(f)
```

## Testing

All config logic should be thoroughly tested:
- Unit tests for individual functions
- Integration tests for config loading
- Startup validation tests
- Hot-reload functionality tests

## Security Considerations

- Config values containing secrets are handled securely
- File permissions are validated
- Config loading is logged for audit trails
- Malformed configs are rejected with clear error messages

## Troubleshooting

**Config not loading**: Check file permissions and paths in `config_assets/`
**Validation errors**: Review startup logs for specific validation failures
**Hot reload not working**: Verify file watcher permissions and config file accessibility
**Provider issues**: Check provider configs in `llm_provider_config.py`</content>
<parameter name="filePath">src/ai_karen_engine/config/README.md
