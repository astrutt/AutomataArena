import asyncio
import sys
import os

# Set up paths
sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

async def smoke_test_manager():
    try:
        from ai_grid.manager import GridNode, MasterHub
        print("MasterHub and GridNode imported.")
        
        hub = MasterHub()
        print("MasterHub instantiated.")
        
        # Test a small call that uses player facade
        # Let's mock a node
        class MockNode:
            def __init__(self, db):
                self.db = db
                self.net_name = "MockNet"
                self.llm = None
        
        node = MockNode(hub.db)
        print("Verifying player.add_experience access...")
        # Just check if it exists and is callable
        if hasattr(node.db.player, 'add_experience'):
            print("SUCCESS: node.db.player.add_experience is accessible.")
        else:
            print("ERROR: node.db.player.add_experience missing!")
            
    except Exception as e:
        print(f"Smoke Test Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'hub' in locals():
            await hub.db.close()

if __name__ == "__main__":
    asyncio.run(smoke_test_manager())
