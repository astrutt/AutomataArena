
import os
import re

core_dir = '/Users/astrutt/Documents/AutomataGrid/ai_grid/core'

replacements = [
    (r'from models import', 'from ai_grid.models import'),
    (r'from grid_utils import', 'from ai_grid.grid_utils import'),
    (r'import core\.handlers as handlers', 'import ai_grid.core.handlers as handlers'),
    (r'import core\.arena as arena', 'import ai_grid.core.arena as arena'),
    (r'import core\.security as security', 'import ai_grid.core.security as security'),
    (r'from core\.security import', 'from ai_grid.core.security import'),
    (r'from \. import handlers', 'import ai_grid.core.handlers as handlers'), # Special case for command_router
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
                print(f"Updated {os.path.relpath(filepath, core_dir)}")

process_dir(core_dir)
