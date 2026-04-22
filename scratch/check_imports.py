
import sys
import os

# Add the project root to sys.path
sys.path.append('/Users/astrutt/Documents/AutomataGrid')

try:
    from ai_grid.models import Base
    print("Successfully imported ai_grid.models")
except Exception as e:
    print(f"Error importing ai_grid.models: {e}")
    import traceback
    traceback.print_exc()

try:
    from ai_grid.database.core import CONFIG
    print("Successfully imported ai_grid.database.core")
except Exception as e:
    print(f"Error importing ai_grid.database.core: {e}")
    import traceback
    traceback.print_exc()

try:
    from ai_grid.database.repositories.navigation_repo import NavigationRepository
    print("Successfully imported NavigationRepository")
except Exception as e:
    print(f"Error importing NavigationRepository: {e}")
    import traceback
    traceback.print_exc()
