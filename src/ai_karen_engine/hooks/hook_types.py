"""
Standard hook types for the unified hook system.
"""


class HookTypes:
    """Standard hook types for chat enhancement and system integration."""
    
    # Message lifecycle hooks
    PRE_MESSAGE = "pre_message"
    POST_MESSAGE = "post_message"
    MESSAGE_PROCESSED = "message_processed"
    MESSAGE_FAILED = "message_failed"
    
    # AI assistance hooks
    AI_SUGGESTION_REQUEST = "ai_suggestion_request"
    AI_SUGGESTION_GENERATED = "ai_suggestion_generated"
    CODE_ANALYSIS_REQUEST = "code_analysis_request"
    CODE_ANALYSIS_COMPLETED = "code_analysis_completed"
    
    # UI enhancement hooks
    UI_COMPONENT_RENDER = "ui_component_render"
    GRID_DATA_LOAD = "grid_data_load"
    CHART_DATA_LOAD = "chart_data_load"
    UI_THEME_CHANGED = "ui_theme_changed"
    
    # Plugin integration hooks
    PLUGIN_EXECUTION_START = "plugin_execution_start"
    PLUGIN_EXECUTION_END = "plugin_execution_end"
    PLUGIN_LOADED = "plugin_loaded"
    PLUGIN_UNLOADED = "plugin_unloaded"
    PLUGIN_ERROR = "plugin_error"
    
    # Extension integration hooks
    EXTENSION_ACTIVATED = "extension_activated"
    EXTENSION_DEACTIVATED = "extension_deactivated"
    EXTENSION_LOADED = "extension_loaded"
    EXTENSION_UNLOADED = "extension_unloaded"
    EXTENSION_ERROR = "extension_error"
    
    # Memory system hooks
    MEMORY_STORE = "memory_store"
    MEMORY_RETRIEVE = "memory_retrieve"
    MEMORY_UPDATE = "memory_update"
    MEMORY_DELETE = "memory_delete"
    
    # LLM provider hooks
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    LLM_ERROR = "llm_error"
    LLM_PROVIDER_CHANGED = "llm_provider_changed"
    
    # Event bus hooks
    EVENT_PUBLISHED = "event_published"
    EVENT_CONSUMED = "event_consumed"
    EVENT_FILTERED = "event_filtered"
    
    # System lifecycle hooks
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SYSTEM_ERROR = "system_error"

    # Workflow lifecycle hooks
    WORKFLOW_REGISTERED = "workflow_registered"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_STEP_STARTED = "workflow_step_started"
    WORKFLOW_STEP_COMPLETED = "workflow_step_completed"
    
    # Authentication hooks
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    AUTH_FAILED = "auth_failed"
    
    # File handling hooks
    FILE_PRE_UPLOAD = "file_pre_upload"
    FILE_POST_UPLOAD = "file_post_upload"
    FILE_UPLOADED = "file_uploaded"
    FILE_PROCESSED = "file_processed"
    FILE_DELETED = "file_deleted"
    FILE_SECURITY_SCAN = "file_security_scan"
    FILE_CONTENT_ANALYSIS = "file_content_analysis"
    FILE_MULTIMEDIA_PROCESS = "file_multimedia_process"
    FILE_THUMBNAIL_GENERATE = "file_thumbnail_generate"
    
    @classmethod
    def get_all_types(cls) -> list[str]:
        """Get all defined hook types."""
        return [
            value for name, value in cls.__dict__.items()
            if isinstance(value, str) and not name.startswith('_')
        ]
    
    @classmethod
    def is_valid_type(cls, hook_type: str) -> bool:
        """Check if a hook type is valid."""
        return hook_type in cls.get_all_types()
    
    @classmethod
    def get_lifecycle_hooks(cls) -> list[str]:
        """Get hooks related to component lifecycle."""
        return [
            cls.PLUGIN_LOADED, cls.PLUGIN_UNLOADED,
            cls.EXTENSION_ACTIVATED, cls.EXTENSION_DEACTIVATED,
            cls.EXTENSION_LOADED, cls.EXTENSION_UNLOADED,
            cls.SYSTEM_STARTUP, cls.SYSTEM_SHUTDOWN
        ]
    
    @classmethod
    def get_error_hooks(cls) -> list[str]:
        """Get hooks related to error handling."""
        return [
            cls.MESSAGE_FAILED, cls.PLUGIN_ERROR,
            cls.EXTENSION_ERROR, cls.LLM_ERROR,
            cls.SYSTEM_ERROR, cls.AUTH_FAILED
        ]
