
import os
import re

root_dir = '/Users/astrutt/Documents/AutomataGrid/ai_grid'

replacements = [
    (r'from models import', 'from ai_grid.models import'),
    (r'from grid_utils import', 'from ai_grid.grid_utils import'),
    (r'from grid_llm import', 'from ai_grid.grid_llm import'),
    (r'from grid_db import', 'from ai_grid.grid_db import'),
    (r'from grid_combat import', 'from ai_grid.grid_combat import'),
    (r'import grid_utils', 'import ai_grid.grid_utils as grid_utils'),
    (r'import grid_llm', 'import ai_grid.grid_llm as grid_llm'),
    (r'import grid_db', 'import ai_grid.grid_db as grid_db'),
    (r'import grid_combat', 'import ai_grid.grid_combat as grid_combat'),
]

def process_dir(directory):
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isdir(filepath):
            if filename != '__pycache__':
                process_dir(filepath)
        elif filename.endswith('.py'):
            with open(filepath, 'r') as f:
                content = f.read()
            
            new_content = content
            for pattern, replacement in replacements:
                new_content = re.sub(pattern, replacement, new_content)
            
            if new_content != content:
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"Updated {os.path.relpath(filepath, root_dir)}")

process_dir(root_dir)
