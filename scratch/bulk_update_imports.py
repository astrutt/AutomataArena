
import os
import re

repo_dir = '/Users/astrutt/Documents/AutomataGrid/ai_grid/database/repositories'

replacements = [
    (r'from \.\.\.models import', 'from ai_grid.models import'),
    (r'from \.\.core import', 'from ai_grid.database.core import'),
    (r'from \.\.base_repo import', 'from ai_grid.database.base_repo import'),
]

for filename in os.listdir(repo_dir):
    if filename.endswith('.py'):
        filepath = os.path.join(repo_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
        
        new_content = content
        for pattern, replacement in replacements:
            new_content = re.sub(pattern, replacement, new_content)
        
        if new_content != content:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"Updated {filename}")
