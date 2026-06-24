from pxr import Usd

# Open your specific file
stage = Usd.Stage.Open('./g1_brainco_extension/assets/g1_with_brainco_hands.usd')

# Walk through the stage and format it like usdtree
for prim in stage.Traverse():
    depth = str(prim.GetPath()).count('/') - 1
    indent = '    ' * depth
    prim_type = prim.GetTypeName()
    type_str = f" ({prim_type})" if prim_type else ""
    
    print(f"{indent}└── {prim.GetName()}{type_str}")
