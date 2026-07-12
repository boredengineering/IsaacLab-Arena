import sys
import os

# Ensure the project root is in sys.path
sys.path.append(os.getcwd())

try:
    from isaaclab_arena.assets.asset_registry import AssetRegistry
    import g1_brainco_extension.assets  # Trigger registration
    
    registry = AssetRegistry()
    assets = registry.get_all_keys()
    
    print(f"Registered assets: {assets}")
    
    for asset_name in ["redbull", "ice_bucket_metal"]:
        if asset_name in assets:
            print(f"SUCCESS: {asset_name} is registered.")
        else:
            print(f"FAILURE: {asset_name} is NOT registered.")
            sys.exit(1)
            
    print("All target assets are registered successfully.")
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
