# Mineflayer Bot Operation Guide

You have access to a Minecraft bot controlled via the `delegate_to_bot` tool. Use this guide to effectively command the bot.

## How to Delegate Tasks

Use `delegate_to_bot(task="...")` with a natural language description. The autonomous bot controller will interpret your task and execute step-by-step actions. Be specific about locations, targets, and desired outcomes.

### Good Examples
- `"Navigate to x=100 y=64 z=-50 and dig the stone block there"`
- `"Find nearby chests around the current position and report their contents"`
- `"Go to the player named Steve and say hello"`
- `"Collect 5 oak_logs from trees near the bot"`

### Bad Examples
- `"Do something"` — too vague
- `"Build a house"` — too complex for a single delegation

## How the Bot Reports Back

After each delegate call, the bot will:
1. Execute actions autonomously in a background loop
2. Report its current state (position, health, inventory) each cycle via `bot_chat`
3. Use `bot_get_state` and `bot_call_action` to interact with the world
4. Results appear in reply messages from those tool calls

## Available Bot Actions

The bot can perform these basic actions via `bot_call_action`:

| Action | Purpose | Required params |
|--------|---------|----------------|
| `get_state` | Get position, health, food, inventory | `{}` |
| `chat` | Send chat message | `{message: string}` |
| `goto` | Pathfind to coordinates | `{x, y, z, range?}` |
| `stop` | Stop all movement | `{}` |
| `lookAt` | Look at coordinates | `{x, y, z}` |
| `dig` | Mine a block | `{x, y, z}` |
| `place` | Place a block | `{x, y, z, face?}` |
| `activateBlock` | Right-click a block (doors, buttons, chests) | `{x, y, z}` |
| `equip` | Equip an item | `{itemName, destination?}` |
| `toss` | Drop items | `{itemName?, amount?}` |
| `attack` | Attack entity | `{entityName?, range?}` |
| `useOn` | Use item on entity | `{entityName}` |
| `activateItem` | Use held item (e.g. eat) | `{}` |
| `deactivateItem` | Stop using item | `{}` |
| `nearbyEntities` | List nearby entities | `{maxDistance?, limit?}` |
| `findBlocks` | Search for blocks by name | `{blockName, maxDistance?, count?}` |
| `getBlock` | Get info about a block | `{x, y, z}` |
| `sleep` | Sleep in nearby bed | `{}` |
| `wake` | Wake up | `{}` |
| `findContainers` | Find nearby chests, furnaces, etc. | `{maxDistance?, count?}` |
| `viewContainer` | View container contents | `{x, y, z}` |
| `takeFromContainer` | Take items from container | `{x, y, z, itemName, count?}` |
| `putToContainer` | Put items into container | `{x, y, z, itemName, count?}` |

## Important Notes

- The bot may not be online. Check with `bot_get_state` first if unsure.
- Coordinates are always (x, y, z) where y is height.
- Block names are Minecraft IDs (e.g., `oak_log`, `stone`, `chest`, `dirt`).
- The bot operates in its own thread and may take several cycles to complete complex tasks.
- If the bot can't reach a location (e.g., path blocked), it will report an error.
- Always prefer to report results back to the user after delegation completes.
