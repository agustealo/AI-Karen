import os
import re

mapping = {
    "ai_orchestrator_routes": "agents.orchestration",
    "audit": "monitoring.audit",
    "auth_routes": "auth.auth",
    "code_execution_routes": "tools.code_execution",
    "conversation_routes": "chat.conversation",
    "communications_center_routes": "content.communications",
    "copilot_routes": "chat.copilot",
    "events": "system.events",
    "extensions": "extensions.extensions",
    "plugin_management": "plugins.management",
    "file_attachment_routes": "content.attachments",
    "memory_routes": "memory.memory",
    "plugin_routes": "plugins.plugins",
    "tool_routes": "tools.tools",
    "websocket_routes": "chat.websocket",
    "chat_runtime": "chat.runtime",
    "llm_routes": "models.llm",
    "provider_routes": "models.providers",
    "profile_routes": "users.profile",
    "settings_routes": "system.settings",
    "model_settings_routes": "models.settings",
    "error_response_routes": "shared.error_response",
    "analytics_routes": "monitoring.analytics",
    "agent_integration_routes": "agents.integration",
    "tasks_routes": "automation.tasks",
    "automation_jobs_routes": "automation.jobs",
    "health": "monitoring.health",
    "model_management_routes": "models.management",
    "huggingface_routes": "models.huggingface",
    "scheduler_routes": "automation.scheduler",
    "public_routes": "public.public",
    "model_library_routes": "models.library",
    "model_orchestrator_routes": "models.model_orchestrator",
    "validation_metrics_routes": "monitoring.validation",
    "performance_routes": "monitoring.performance",
    "persona_routes": "users.persona",
    "model_organization_routes": "models.organization",
    "user_preferences_routes": "users.preferences",
    "user_data_routes": "users.data",
    "users": "users.users",
    "training_data_routes": "training.data",
    "privacy_routes": "auth.privacy",
    "runtime_admin_routes": "admin.runtime",
    "multimodal_routes": "content.multimodal",
    "ai_routes": "models.ai",
    "cognitive_routes": "cognition.cognitive",
    "reasoning_routes": "cognition.reasoning",
}

def update_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content
    modified = False

    for old, new in mapping.items():
        # Match ai_karen_engine.api_routes.<old> but NOT ai_karen_engine.api_routes.<new_part>
        # We use a regex that matches the old module name specifically.
        # We need to be careful not to match if it's already part of the new path.
        
        # Example: ai_karen_engine.api_routes.extensions.extensions -> ai_karen_engine.api_routes.extensions.extensions
        # If we match "extensions", we might match "extensions.extensions" and change it to "extensions.extensions.extensions".
        # So we match ai_karen_engine.api_routes.old (\b|$)
        
        pattern = r'ai_karen_engine\.api_routes\.' + re.escape(old) + r'(\b)'
        # Before replacing, check if it's already updated.
        # Actually, if we use the full path in the pattern, it's safer.
        
        # Replacement should only happen if it's not already the new path.
        # Wait, if we replace ai_karen_engine.api_routes.extensions.extensions with ai_karen_engine.api_routes.extensions.extensions,
        # and then we run it again, it will match ai_karen_engine.api_routes.extensions.extensions and replace it again.
        
        # To avoid this, we can use a negative lookahead if the tool supports it, or just do it carefully.
        # In Python re, we can use negative lookahead.
        # We want to match 'ai_karen_engine.api_routes.old' NOT followed by the rest of the 'new' path if it's different.
        
        # Actually, simpler: only replace if the full match is NOT already containing the new path in a way that would be redundant.
        
        # Let's try to match the whole thing and replace it.
        
        old_full = f"ai_karen_engine.api_routes.{old}"
        new_full = f"ai_karen_engine.api_routes.{new}"
        
        if old_full == new_full:
            continue
            
        # Use regex to match exact module name
        regex = r'\b' + re.escape(old_full) + r'\b'
        
        if re.search(regex, new_content):
            new_content = re.sub(regex, new_full, new_content)
            modified = True

    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

def main():
    for root, dirs, files in os.walk('.'):
        if '.git' in dirs:
            dirs.remove('.git')
        if '.venv' in dirs:
            dirs.remove('.venv')
        if '.virEnv' in dirs:
            dirs.remove('.virEnv')
        if 'node_modules' in dirs:
            dirs.remove('node_modules')
            
        for file in files:
            if file.endswith('.py'):
                update_file(os.path.join(root, file))

if __name__ == "__main__":
    main()
