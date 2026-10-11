What a 1.5B Model Can Do Reliably

Parse pipe-delimited or simple structured output (your Text mode)
Execute single, clear commands (map, explore, hack <target>)
Follow a simple decision tree with 2-3 options
Maintain a very short memory of immediate context (last 2-3 exchanges)

This is enough to survive early game — spawning, exploring nearby nodes, probing, basic raiding. A 1.5B running your Text mode output with a tight system prompt could plausibly play the discovery loop on its own.

## Local and Remote Grid Operations

Commands without a network target operate on your local grid:

- `!a raid explore`
- `!a raid probe <target>`
- `!a raid hack <target>`
- `!a raid siphon <target>`
- `!a raid exploit <target>`
- `!a raid <target>` to raid a breached node

For remote operations, stand at a node you own, install NET hardware, and point it at a configured network:

1. `!a grid hardware install NET`
2. `!a grid net <network>`
3. `!a net <network> <explore|probe|hack|siphon|exploit|raid> [target]`

The `!a raid <network> <action> [target]` form is also supported. Remote operations require the owned node's NET device to be installed and linked to the requested network.

