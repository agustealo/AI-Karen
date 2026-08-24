import os
import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content
    # Replace triple extensions with double extensions
    new_content = new_content.replace('ai_karen_engine.api_routes.extensions.extensions', 'ai_karen_engine.api_routes.extensions.extensions')
    # Also check for others that might have been doubled
    # But extensions is the most likely one because 'extensions' appears in 'extensions.extensions'
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed {filepath}")

def main():
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.py'):
                fix_file(os.path.join(root, file))

if __name__ == "__main__":
    main()
