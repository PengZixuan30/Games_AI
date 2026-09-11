import os
import asyncio
import json
import threading
import websockets
import hashlib
import sys
import subprocess
import signal
import logging
import re
import time

from mcdreforged.command.command_source import CommandSource
from .games_ai_tool import register_tool, register_bot_tool

_active_client: "MineflayerWSClient | None" = None
_client_lock = threading.Lock()
_process: subprocess.Popen | None = None

_DEPS_PACKAGES = ("mineflayer", "ws", "vec3", "mineflayer-pathfinder", "mineflayer-mcefly")
_DEPS_MARKER_NAME = ".games_ai_deps_ok"
_UNSUPPORTED_VERSION_RE = re.compile(
    r"UNSUPPORTED_SERVER_VERSION|Server version .*? is not supported",
    re.IGNORECASE,
)
_DEPS_REPAIR_COOLDOWN = 600.0
_DEPS_REPAIR_MAX = 3
_deps_repair_lock = threading.Lock()
_deps_repair_count = 0
_deps_repair_last = 0.0


def is_node_running() -> bool:
    return _process is not None and _process.poll() is None


def get_mineflayer_client() -> "MineflayerWSClient | None":
    return _active_client


def start_mineflayer_client(url: str, logger = None, reconnect_interval: float = 10, timeout: float = 60) -> "MineflayerWSClient":
    global _active_client
    with _client_lock:
        if _active_client is not None:
            _active_client.stop()
        _active_client = MineflayerWSClient(url, logger, reconnect_interval, timeout)
        _active_client.start()
        return _active_client


def stop_mineflayer_client():
    global _active_client
    with _client_lock:
        if _active_client is not None:
            _active_client.stop()
            _active_client = None


class MineflayerWSClient:

    def __init__(self, url: str, logger: logging.Logger | None = None, reconnect_interval: float = 10, timeout: float = 60):
        self.url = url
        self._log = logger or logging.getLogger(__name__)
        self.reconnect_interval = reconnect_interval
        self.timeout = timeout
        self._ws: websockets.ClientConnection | None = None
        self._running = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._send_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._first_connect = True

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set() and self._ws is not None


    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._connected.clear()
        self._first_connect = True
        if self._loop is not None and self._loop.is_running():
            try:
                for fut in list(self._pending.values()):
                    if not fut.done():
                        self._loop.call_soon_threadsafe(fut.cancel)

                async def _close_ws():
                    if self._ws is not None:
                        await self._ws.close()
                asyncio.run_coroutine_threadsafe(_close_ws(), self._loop)
            except RuntimeError:
                self._log.warning("[WSClient] Runtime error when stopping!")
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)


    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connection_loop())
        except RuntimeError:
            self._log.warning("[WSClient] Runtime error when starting!")
        finally:
            self._loop.close()

    async def _connection_loop(self):
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    self._first_connect = False
                    await self._message_loop(ws)
            except asyncio.TimeoutError:
                if self._first_connect:
                    self._log.info("[WSClient] Connection timed out (Node.js server not ready yet), will retry...")
                else:
                    self._log.warning("[WSClient] Connection timed out, retrying in %ss", self.reconnect_interval)
            except (websockets.ConnectionClosed, OSError):
                self._log.warning("[WSClient] Connection error, retrying in %ss", self.reconnect_interval)
            except websockets.exceptions.InvalidMessage:
                if self._first_connect:
                    self._log.info("[WSClient] First connection attempt failed (Node.js server not ready yet), will retry...")
                else:
                    self._log.exception("[WSClient] Unexpected InvalidMessage after initial connection!")
            except Exception as e:
                self._log.exception(e)
            finally:
                self._connected.clear()
                self._ws = None
                if self._running:
                    await asyncio.sleep(self.reconnect_interval)

    async def _message_loop(self, ws: websockets.ClientConnection):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rid = msg.get("request_id")
            if rid is not None and rid in self._pending:
                future = self._pending.pop(rid)
                if not future.done():
                    future.get_loop().call_soon_threadsafe(
                        lambda f=future, m=msg: f.set_result(m) if not f.done() else None
                    )


    def send_command(self, action: str, params: dict | None = None, timeout: float | None = None) -> dict:
        if not self.is_connected:
            raise ConnectionError("Not connected to Mineflayer bot")

        timeout = timeout or self.timeout
        with self._send_lock:
            self._request_id += 1
            rid = self._request_id

        loop = self._loop
        if loop is None:
            raise ConnectionError("Event loop is not running")

        future = asyncio.run_coroutine_threadsafe(
            self._send_and_wait(action, params or {}, rid),
            loop,
        )

        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(f"Command '{action}' timed out after {timeout}s")
        except Exception:
            self._pending.pop(rid, None)
            raise

    async def _send_and_wait(self, action: str, params: dict, rid: int) -> dict:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[rid] = future

        await self._ws.send(json.dumps({
            "request_id": rid,
            "action": action,
            "params": params,
        }))

        return await future


def _get_client():
    client = get_mineflayer_client()
    if client is None:
        return None, "Mineflayer Bot was not started. Please start the bot first."
    if not client.is_connected:
        return None, "Mineflayer Bot WebSocket is not connected. Attempting to reconnect..."
    return client, None


@register_tool(
    description="Send a message to the Minecraft chat as the Mineflayer bot",
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Chat message to send",
            }
        },
        "required": ["message"],
    },
)
@register_bot_tool()
def bot_chat(source: CommandSource, ai_prefix: str, message: str):
    message = re.sub(r'§.', '', message)
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("chat", {"message": message})
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_chat', message=message)}")
        return f"Bot sent the message: {message}"
    except TimeoutError:
        return "Timed out while sending the message; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to send the message: {e}"


@register_tool(
    description="Send a private message from the Mineflayer bot to a player",
    parameters={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Name of the player to whisper",
            },
            "message": {
                "type": "string",
                "description": "Private message to send",
            },
        },
        "required": ["username", "message"],
    },
)
@register_bot_tool()
def bot_whisper(source: CommandSource, ai_prefix: str, username: str, message: str):
    message = re.sub(r'§.', '', message)
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("whisper", {"username": username, "message": message})
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_whisper')}")
        return f"Bot whispered {username}"
    except TimeoutError:
        return "Timed out while sending the whisper; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to send the whisper: {e}"


@register_tool(
    description="Get the current state of the Mineflayer bot (position, health, hunger, game mode, inventory)",
)
@register_bot_tool()
def bot_get_state(source: CommandSource, ai_prefix: str):
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        result = client.send_command("get_state")
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_get_state')}")
        data = result.get("data", result)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TimeoutError:
        return "Timed out while getting the bot state; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to get the bot state: {e}"


@register_tool(
    description=(
        "Send any action to the Mineflayer bot. Available actions:\n"
        "- get_state: full bot state, params: {}\n"
        "- goto: pathfind to coordinates, params: {x, y, z, range?}\n"
        "- efly: fly to coordinates with an elytra (an elytra must be equipped and flight already started), params: {x, y, z}\n"
        "- stopEfly: stop elytra flight, params: {}\n"
        "- stop: stop all movement, params: {}\n"
        "- lookAt: look at coordinates or set the view rotation, params: {x, y, z, force?: bool} or {yaw, pitch, force?: bool}. Direction reference (radians): south=0, west=1.57(pi/2), north=3.14(pi), east=-1.57(-pi/2); pitch: up=-1.57, down=1.57, horizontal=0\n"
        "- dig: break a block, params: {x, y, z}\n"
        "- place: place a block, params: {x, y, z, face?: {x, y, z}}\n"
        "- activateBlock: right-click a block (open a chest, press a button, ...), params: {x, y, z}\n"
        "- equip: equip an item, params: {itemName: string, destination?: string}. destination: hand/head/torso/legs/feet/off-hand"
        "- unequip: take equipment off, params: {destination?: string}. destination: head/torso/chest/legs/feet, default torso\n"
        "- toss: drop items, params: {itemName?: string, amount?: int}\n"
        "- setQuickBarSlot: switch the hotbar slot, params: {slot: int(0-8)}\n"
        "- attack: attack an entity, params: {entityName?: string, range?: float}\n"
        "- useOn: use an item on an entity, params: {entityName: string}\n"
        "- activateItem: use the held item (for example eat), params: {}\n"
        "- deactivateItem: stop using the held item, params: {}\n"
        "- nearbyEntities: list nearby entities, params: {maxDistance?: float, limit?: int}\n"
        "- findBlocks: search for nearby blocks, params: {blockName: string, maxDistance?: float, count?: int}\n"
        "- getBlock: get block information at coordinates, params: {x, y, z}\n"
        "- sleep: sleep in a nearby bed, params: {}\n"
        "- wake: wake up, params: {}\n"
        "- mount: ride an entity (minecart/boat/horse, ...), params: {entityName?: string} (the nearest one is used when omitted)\n"
        "- dismount: leave the ridden entity, params: {}\n"
        "- setControlState: control the ridden entity (forward/back/left/right/jump/sneak/sprint), params: {control: string, state?: bool}\n"
        "- findContainers: find nearby containers, params: {maxDistance?: float, count?: int}\n"
        "- viewContainer: view the contents of a container, params: {x, y, z}\n"
        "- takeFromContainer: take items from a container into the inventory, params: {x, y, z, itemName: string, count?: int}\n"
        "- putToContainer: put items from the inventory into a container, params: {x, y, z, itemName: string, count?: int}\n"
        "- openFurnace: open a furnace and view its state, params: {x, y, z}\n"
        "- furnacePutInput: put items into a furnace to smelt them, params: {x, y, z, itemName: string, count?: int}\n"
        "- furnacePutFuel: put fuel into a furnace, params: {x, y, z, itemName: string, count?: int}\n"
        "- furnaceTakeOutput: take the smelted output out of a furnace, params: {x, y, z}\n"
        "- craft: craft an item (inventory or crafting table), params: {itemName: string, count?: int, x?, y?, z?} (crafts in the inventory when no coordinates are given)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action name to run, e.g. 'goto' or 'get_state'. Note: send messages with bot_chat or bot_whisper instead of this tool",
            },
            "params": {
                "type": "object",
                "description": "Parameters for the action, as a JSON object, e.g. {'message': 'hello'} or {}",
            },
        },
        "required": ["action"],
    },
)
@register_bot_tool()
def bot_call_action(source: CommandSource, ai_prefix: str, action: str, params: dict | None = None):
    if action in ("chat", "whisper"):
        return "Do not send messages through bot_call_action; use the dedicated bot_chat or bot_whisper tool instead"
    server = source.get_server()
    client, err = _get_client()
    if err is not None:
        return err
    try:
        timeout = 90 if action == 'goto' else None
        result = client.send_command(action, params or {}, timeout=timeout)
        source.reply(f"{ai_prefix}{server.rtr('games_ai.tools.bot_call_action', action=action)}")
        data = result.get("data", result)
        status = result.get("status", "unknown")
        if status == "error":
            return f"The bot returned an error: {data.get('error', data)}"
        return json.dumps(data, ensure_ascii=False, indent=2)
    except TimeoutError:
        return f"Action '{action}' timed out; the bot may not be responding"
    except ConnectionError as e:
        return f"Connection error: {e}"
    except Exception as e:
        return f"Failed to run action '{action}': {e}"


_INIT_JS_CONTENT = r"""// This is the script for the Mineflayer bot service.
const mineflayer = require('mineflayer');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const url = require('url');
const Vec3 = require('vec3');

// ── Optional: pathfinder plugin ──
let pathfinder = null;
try {
    pathfinder = require('mineflayer-pathfinder');
} catch (e) {
    console.log('[Bot] mineflayer-pathfinder not installed, goto action will be unavailable');
}

// ── Optional: mcefly plugin ──
let mcefly = null;
try {
    mcefly = require('mineflayer-mcefly');
} catch (e) {
    console.log('[Bot] mineflayer-mcefly not installed, efly action will be unavailable');
}

// ---------- Configuration Loading ----------
const CONFIG_PATH = path.join(__dirname, 'config.json');

// Default configuration (matches the provided structure)
const DEFAULT_CONFIG = {
    enabled: false,
    websocket: {
        url: "ws://127.0.0.1:8080",
        reconnect_interval: 10,
        timeout: 60
    },
    bot: {
        server_host: "<Your Minecraft Server Host>",
        server_port: 25565,
        username: "<Your Minecraft Bot Username>",
        password: "<Your Minecraft Bot Password>",
        auth: "microsoft"
    }
};

let config = { ...DEFAULT_CONFIG };

/**
 * Load configuration from JSON file, merging with defaults.
 */
function loadConfig() {
    try {
        const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
        const parsed = JSON.parse(raw);
        config = {
            enabled: parsed.enabled !== undefined ? parsed.enabled : DEFAULT_CONFIG.enabled,
            websocket: {
                url: parsed.websocket?.url || DEFAULT_CONFIG.websocket.url,
                reconnect_interval: parsed.websocket?.reconnect_interval || DEFAULT_CONFIG.websocket.reconnect_interval,
                timeout: parsed.websocket?.timeout || DEFAULT_CONFIG.websocket.timeout
            },
            bot: {
                server_host: parsed.bot?.server_host || DEFAULT_CONFIG.bot.server_host,
                server_port: parsed.bot?.server_port || DEFAULT_CONFIG.bot.server_port,
                username: parsed.bot?.username || DEFAULT_CONFIG.bot.username,
                password: parsed.bot?.password || DEFAULT_CONFIG.bot.password,
                auth: parsed.bot?.auth || DEFAULT_CONFIG.bot.auth
            }
        };
        console.log('[Config] Configuration loaded successfully');
    } catch (e) {
        console.warn('[Config] Failed to read config file, using defaults:', e.message);
        config = { ...DEFAULT_CONFIG };
    }
}

loadConfig();

// ---------- Helper: Extract port from WebSocket URL ----------
function getWSPortFromUrl(urlString) {
    const parsed = new url.URL(urlString);
    let port = parseInt(parsed.port, 10);
    if (isNaN(port)) {
        // Default ports based on protocol
        port = parsed.protocol === 'wss:' ? 443 : 80;
    }
    return port;
}

// ---------- Bot and WebSocket state ----------
let bot = null;
let wss = null;
let reconnectTimer = null;
let chatMessages = [];

// ── Custom Physics: Knockback & Entity Collision ──
// Mineflayer's built-in physics only handles gravity and block collisions.
// This adds server-side knockback response and entity-to-entity pushing (cramming).

let physicsTickInterval = null;
let velocityQueue = [];

function clearCustomPhysics() {
    if (physicsTickInterval) {
        clearInterval(physicsTickInterval);
        physicsTickInterval = null;
    }
    velocityQueue = [];
}

function setupCustomPhysics(botInstance) {
    clearCustomPhysics();
    velocityQueue = [];

    // ── Knockback approach 1: Listen for raw velocity packets ──
    // Packet name is 'entity_velocity' in minecraft-protocol (NOT 'set_entity_velocity')
    try {
        botInstance._client.on('entity_velocity', (packet) => {
            if (!botInstance || !botInstance.entity) return;
            if (packet.entityId === botInstance.entity.id) {
                // Server velocity is in fixed-point (1/8000 blocks per tick)
                const vx = packet.velocityX / 8000;
                const vy = packet.velocityY / 8000;
                const vz = packet.velocityZ / 8000;
                if (Math.abs(vx) > 0.001 || Math.abs(vz) > 0.001 || Math.abs(vy) > 0.001) {
                    velocityQueue.push({ vx, vy, vz, ticks: 8 });
                }
            }
        });
    } catch (e) {
        console.log('[CustomPhysics] Could not attach entity_velocity listener:', e.message);
    }

    // Tick-based physics: apply knockback and entity collision every 50ms (~20 tps)
    physicsTickInterval = setInterval(() => {
        if (!botInstance || !botInstance.entity || !botInstance.entity.position) return;

        // ── Knockback approach 1: apply queued velocity from raw packets ──
        for (let i = velocityQueue.length - 1; i >= 0; i--) {
            const kb = velocityQueue[i];
            if (kb.ticks <= 0) {
                velocityQueue.splice(i, 1);
                continue;
            }
            const factor = kb.ticks / 8;
            botInstance.entity.position.x += kb.vx * factor;
            botInstance.entity.position.z += kb.vz * factor;
            if (Math.abs(kb.vy) > 0.001) {
                botInstance.entity.position.y += kb.vy * factor;
            }
            kb.ticks--;
        }

        // ── Knockback approach 2: Poll entity.velocity as fallback ──
        // Only trigger on large velocities (knockback), NOT on normal walking (≈0.1)
        const vel = botInstance.entity.velocity;
        if (vel && (Math.abs(vel.x) > 0.3 || Math.abs(vel.z) > 0.3)) {
            botInstance.entity.position.x += vel.x;
            botInstance.entity.position.z += vel.z;
            if (Math.abs(vel.y) > 0.001) {
                botInstance.entity.position.y += vel.y;
            }
            // Clear to prevent double-application
            vel.x = 0;
            vel.z = 0;
            vel.y *= 0.3;
        }

        // ── Entity collision / cramming ──
        // Skip during pathfinder navigation to avoid interfering with goto
        const isPathfinding = pathfinder && botInstance.pathfinder && botInstance.pathfinder.goal;
        if (!isPathfinding) {
            const COLLISION_DIST = 0.6;
            const pos = botInstance.entity.position;
            for (const other of Object.values(botInstance.entities)) {
                if (other === botInstance.entity || !other.position) continue;
                if (other.type !== 'player' && other.type !== 'mob') continue;

                const dx = pos.x - other.position.x;
                const dz = pos.z - other.position.z;
                const distH = Math.sqrt(dx * dx + dz * dz);

                if (distH < COLLISION_DIST && distH > 0.01) {
                    const push = (COLLISION_DIST - distH) * 0.2;
                    pos.x += (dx / distH) * push;
                    pos.z += (dz / distH) * push;
                }
            }
        }
    }, 50);
}

/**
 * Create and start the Mineflayer bot.
 * Also sets up event handlers.
 */
function startBot() {
    if (bot) {
        // If bot already exists, end it cleanly
        bot.end();
        bot = null;
    }
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    // Map configuration to Mineflayer options
    const auth = config.bot.auth || (config.bot.password ? 'microsoft' : 'offline');
    const botOptions = {
        host: config.bot.server_host,
        port: config.bot.server_port,
        username: config.bot.username,
        auth: auth,
    };
    if (auth !== 'offline' && config.bot.password) {
        botOptions.password = config.bot.password;
    }

    // ── Version-unsupported handling ──
    // When the installed mineflayer does not support the server version (e.g.
    // the Minecraft server was upgraded), print a distinctive marker line and
    // exit with code 3. The MCDR plugin detects the marker, refreshes the npm
    // dependencies and restarts this process automatically.
    let versionUnsupportedReported = false;
    const reportVersionUnsupported = (err) => {
        if (versionUnsupportedReported) return false;
        const msg = (err && err.message) ? err.message : String(err);
        if (!/is not supported|not supported|unsupported version/i.test(msg)) return false;
        versionUnsupportedReported = true;
        const m = msg.match(/version '([^']+)'/i);
        console.error(`[Bot] UNSUPPORTED_SERVER_VERSION: ${m ? m[1] : 'unknown'}`);
        console.error('[Bot] The installed mineflayer does not support this server version. The plugin will update the npm dependencies and restart the bot automatically...');
        setTimeout(() => process.exit(3), 1500);
        return true;
    };

    try {
        bot = mineflayer.createBot(botOptions);
    } catch (err) {
        console.error('[Bot] Failed to create bot:', err);
        if (!reportVersionUnsupported(err)) {
            setTimeout(() => process.exit(1), 1500);
        }
        return;
    }

    if (pathfinder) {
        bot.loadPlugin(pathfinder.pathfinder);
    }

    if (mcefly) {
        bot.loadPlugin(mcefly);
    }

    bot.on('login', () => {
        console.log(`[Bot] Logged in as ${bot.username}`);
        if (config.bot.password && !config.bot.password.startsWith('<')) {
            bot.chat('/login ' + config.bot.password);
        }
    });

    bot.on('spawn', () => {
        console.log('[Bot] Entered the game world');
        bot.physicsEnabled = true;
        setupCustomPhysics(bot);
        console.log('[Bot] Physics enabled:', bot.physicsEnabled);
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (pathfinder) {
            const mcData = require('minecraft-data')(bot.version);
            const movements = new pathfinder.Movements(bot, mcData);
            movements.canDig = false;
            bot.pathfinder.setMovements(movements);
            console.log('[Bot] Pathfinder configured (canDig=false)');
        }
        if (mcefly) {
            bot.mcefly.setConfig({
                navigationSpeed: 0.08,
                maxSpeed: 3.0,
                flightTimeout: 36600000,
                quiet: false,
            });
            console.log('[Bot] McEfly configured (navigationSpeed=0.08, maxSpeed=3.0=60m/s)');
        }
    });

    bot.on('chat', (username, message, translate, jsonMsg, matches) => {
        if (username === bot.username) return;
        chatMessages.push({ type: 'chat', username: username, content: message, timestamp: Date.now() });
    });

    bot.on('whisper', (username, message, translate, jsonMsg, matches) => {
        if (username === bot.username) return;
        chatMessages.push({ type: 'whisper', username: username, content: message, timestamp: Date.now() });
    });

    bot.on('message', (jsonMsg, position, sender, verified) => {
        if (position === 'system') {
            chatMessages.push({ type: 'server', content: jsonMsg.toString(), timestamp: Date.now() });
        }
    });

    bot.on('error', (err) => {
        console.error('[Bot] Error:', err);
        reportVersionUnsupported(err);
    });

    bot.on('kicked', (reason, loggedIn) => {
        console.log('[Bot] Kicked from server. Reason:', JSON.stringify(reason));
    });

    bot.on('end', (reason) => {
        console.log('[Bot] Disconnected. Reason:', reason);
        const delay = 5000;
        console.log(`[Bot] Reconnecting in ${delay/1000} seconds...`);
        reconnectTimer = setTimeout(() => {
            if (config.enabled) {
                startBot();
            } else {
                console.log('[Bot] Reconnect cancelled because service is disabled');
            }
        }, delay);
    });

    bot.on('death', () => {
        console.log('[Bot] Died, respawning...');
        bot.respawn();
    });
}

/**
 * Stop the bot (if running).
 */
function stopBot() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    clearCustomPhysics();
    if (bot) {
        bot.end();
        bot = null;
        console.log('[Bot] Stopped');
    }
}

/**
 * Start the WebSocket server.
 */
function startWebSocketServer() {
    if (wss) {
        console.log('[WS] WebSocket server already running');
        return;
    }
    const port = getWSPortFromUrl(config.websocket.url);
    wss = new WebSocket.Server({ port });
    console.log(`[WS] WebSocket server started on port ${port} (from ${config.websocket.url})`);

    // Helper to send response
    function sendResponse(ws, requestId, status, data = null) {
        const msg = JSON.stringify({ request_id: requestId, status, data });
        ws.send(msg);
    }

    wss.on('connection', (ws) => {
        console.log('[WS] Client connected');

        ws.on('message', (message) => {
            let command;
            try {
                command = JSON.parse(message);
            } catch (e) {
                ws.send(JSON.stringify({ status: 'error', error: 'Invalid JSON format' }));
                return;
            }

            const { request_id, action, params = {} } = command;
            console.log(`[WS] Received command: ${action} (ID: ${request_id})`);

            if (!bot || !bot.entity) {
                sendResponse(ws, request_id, 'error', { error: 'Bot not ready' });
                return;
            }

            switch (action) {
                case 'get_state': {
                    // ── Equipment / armor (version-adaptive) ──
                    const heldItem = bot.heldItem ? { name: bot.heldItem.name, displayName: bot.heldItem.displayName, count: bot.heldItem.count } : null;
                    const armor = {};
                    // Armor slots: old versions = 5-8, 1.20.5+ may differ
                    // Detect by scanning inventory.slots for items whose slot index is in the known armor range
                    const armorSlotNames = { 5: 'head', 6: 'chest', 7: 'legs', 8: 'feet' };
                    // Try known indices first
                    for (const [slot, part] of Object.entries(armorSlotNames)) {
                        const piece = bot.inventory.slots[parseInt(slot)];
                        if (piece && piece.name && piece.name !== 'air') {
                            armor[part] = { name: piece.name, displayName: piece.displayName, count: piece.count };
                        }
                    }
                    // Fallback: if armor is empty, scan all slots for items that look like armor
                    if (Object.keys(armor).length === 0) {
                        for (const item of bot.inventory.items()) {
                            const slot = item.slot;
                            const name = (item.name || '').toLowerCase();
                            if (slot >= 5 && slot <= 8 && name !== 'air') {
                                const part = armorSlotNames[slot];
                                if (part) {
                                    armor[part] = { name: item.name, displayName: item.displayName, count: item.count };
                                }
                            }
                        }
                    }

                    const state = {
                        // ── Position & orientation ──
                        position: bot.entity.position,
                        yaw: bot.entity.yaw,
                        pitch: bot.entity.pitch,
                        velocity: bot.entity.velocity,
                        onGround: bot.entity.onGround,
                        // ── Entity flags ──
                        isInWater: bot.entity.isInWater,
                        isInLava: bot.entity.isInLava,
                        isInWeb: bot.entity.isInWeb,
                        isCollidedHorizontally: bot.entity.isCollidedHorizontally,
                        isCollidedVertically: bot.entity.isCollidedVertically,
                        isSleeping: bot.isSleeping,
                        // ── World ──
                        dimension: bot.game.dimension,
                        gamemode: bot.game.gameMode,
                        difficulty: bot.game.difficulty,
                        hardcore: bot.game.hardcore,
                        worldTime: bot.time.timeOfDay,
                        isDay: bot.time.isDay,
                        isRaining: bot.rainState > 0,
                        rainState: bot.rainState,
                        thunderState: bot.thunderState,
                        // ── Vital stats ──
                        health: bot.health,
                        food: bot.food,
                        foodSaturation: bot.foodSaturation,
                        oxygenLevel: bot.oxygenLevel,
                        experience: bot.experience,
                        experienceLevel: bot.experienceLevel,
                        // ── Equipment ──
                        heldItem: heldItem,
                        quickBarSlot: bot.quickBarSlot,
                        armor: armor,
                        // ── Riding ──
                        vehicle: bot.vehicle ? {
                            name: bot.vehicle.name || bot.vehicle.username || 'unknown',
                            type: bot.vehicle.type,
                            position: bot.vehicle.position,
                        } : null,
                        // ── Inventory ──
                        inventory: bot.inventory.items().map(i => ({ name: i.name, displayName: i.displayName, count: i.count, slot: i.slot })),
                    };
                    sendResponse(ws, request_id, 'success', state);
                    break;
                }

                case 'chat': {
                    if (!params.message) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing message parameter' });
                        return;
                    }
                    bot.chat(params.message);
                    sendResponse(ws, request_id, 'success', { message: 'Message sent' });
                    break;
                }

                case 'goto': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    if (!pathfinder) {
                        sendResponse(ws, request_id, 'error', { error: 'pathfinder plugin not installed. Run: npm install mineflayer-pathfinder' });
                        return;
                    }
                    const goal = new pathfinder.goals.GoalNear(params.x, params.y, params.z, params.range || 2);
                    const gotoTimeout = params.timeout || 60000;
                    let gotoResolved = false;

                    const onGoalReached = () => {
                        if (gotoResolved) return;
                        gotoResolved = true;
                        cleanup();
                        sendResponse(ws, request_id, 'success', { message: `Reached (${params.x}, ${params.y}, ${params.z})` });
                    };

                    const onPathUpdate = (result) => {
                        if (gotoResolved) return;
                        if (result.status === 'noPath') {
                            gotoResolved = true;
                            cleanup();
                            sendResponse(ws, request_id, 'error', { error: 'No path found - destination unreachable or blocked' });
                        }
                    };

                    const cleanup = () => {
                        bot.removeListener('goal_reached', onGoalReached);
                        bot.removeListener('path_update', onPathUpdate);
                        if (!gotoResolved) {
                            bot.pathfinder.setGoal(null);
                        }
                    };

                    bot.on('goal_reached', onGoalReached);
                    bot.on('path_update', onPathUpdate);
                    bot.pathfinder.setGoal(goal);

                    setTimeout(() => {
                        if (gotoResolved) return;
                        gotoResolved = true;
                        cleanup();
                        sendResponse(ws, request_id, 'error', { error: 'Pathfinding timeout - could not reach destination' });
                    }, gotoTimeout);
                    break;
                }

                case 'efly': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    if (!mcefly) {
                        sendResponse(ws, request_id, 'error', { error: 'mcefly plugin not installed. Run: npm install mineflayer-mcefly' });
                        return;
                    }
                    bot.mcefly.goto(new Vec3(params.x, params.y, params.z))
                        .then(() => {
                            sendResponse(ws, request_id, 'success', { message: `Arrived at (${params.x}, ${params.y}, ${params.z})` });
                        })
                        .catch((err) => {
                            bot.mcefly.kill();
                            sendResponse(ws, request_id, 'error', { error: 'Elytra flight failed: ' + err.message });
                        });
                    return;
                }

                case 'stopEfly': {
                    if (!mcefly) {
                        sendResponse(ws, request_id, 'error', { error: 'mcefly plugin not installed' });
                        return;
                    }
                    bot.mcefly.stop()
                        .then(() => {
                            sendResponse(ws, request_id, 'success', { message: 'Elytra flight stopped and landed' });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Stop failed: ' + err.message });
                        });
                    return;
                }

                case 'stop': {
                    if (pathfinder) {
                        bot.pathfinder.setGoal(null);
                    }
                    bot.clearControlStates();
                    sendResponse(ws, request_id, 'success', { message: 'Stopped all movement' });
                    break;
                }

                case 'lookAt': {
                    if (params.yaw != null || params.pitch != null) {
                        // Direct yaw/pitch mode
                        const yaw = params.yaw != null ? params.yaw : bot.entity.yaw;
                        const pitch = params.pitch != null ? params.pitch : bot.entity.pitch;
                        bot.look(yaw, pitch, params.force);
                        sendResponse(ws, request_id, 'success', {
                            yaw: bot.entity.yaw,
                            pitch: bot.entity.pitch,
                        });
                    } else if (params.x != null && params.y != null && params.z != null) {
                        // Coordinate mode
                        bot.lookAt(new Vec3(params.x, params.y, params.z), params.force);
                        sendResponse(ws, request_id, 'success', {
                            position: bot.entity.position,
                            yaw: bot.entity.yaw,
                            pitch: bot.entity.pitch,
                        });
                    } else {
                        sendResponse(ws, request_id, 'error', { error: 'Provide either (yaw, pitch) or (x, y, z)' });
                    }
                    break;
                }

                // ── Block interaction ──

                case 'dig': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const digBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!digBlock || digBlock.name === 'air') {
                        sendResponse(ws, request_id, 'error', { error: 'No breakable block at this position' });
                        return;
                    }
                    bot.dig(digBlock).then(() => {
                        sendResponse(ws, request_id, 'success', {
                            block: digBlock.name,
                            position: { x: params.x, y: params.y, z: params.z }
                        });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return; // Promise callback, skip sync sendResponse
                }

                case 'place': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const refBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!refBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No reference block at this position' });
                        return;
                    }
                    const faceVec = params.face ? new Vec3(params.face.x, params.face.y, params.face.z) : new Vec3(0, 1, 0);
                    bot.placeBlock(refBlock, faceVec).then(() => {
                        sendResponse(ws, request_id, 'success', { message: 'Block placed' });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                case 'activateBlock': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const actBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!actBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    bot.activateBlock(actBlock).then(() => {
                        sendResponse(ws, request_id, 'success', { message: 'Block activated' });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                // ── Inventory ──

                case 'equip': {
                    if (!params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing itemName parameter' });
                        return;
                    }
                    const dest = params.destination || 'hand';
                    const item = bot.inventory.items().find(i => i.name.includes(params.itemName));
                    if (!item) {
                        sendResponse(ws, request_id, 'error', { error: `Item '${params.itemName}' not found in inventory` });
                        return;
                    }
                    bot.equip(item, dest).then(() => {
                        sendResponse(ws, request_id, 'success', { item: item.name, destination: dest });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                case 'unequip': {
                    const dest = params.destination || 'torso';
                    const armorSlotMap = { head: 5, torso: 6, chest: 6, legs: 7, feet: 8 };
                    const slot = armorSlotMap[dest];
                    if (slot == null) {
                        sendResponse(ws, request_id, 'error', { error: `Invalid destination '${dest}'. Use head/torso/chest/legs/feet` });
                        return;
                    }
                    const piece = bot.inventory.slots[slot];
                    if (!piece || piece.name === 'air') {
                        sendResponse(ws, request_id, 'success', { message: `No armor equipped in ${dest} slot` });
                        return;
                    }
                    try {
                        // Shift-click the armor slot to move it back to inventory
                        bot.clickWindow(slot, 0, 1);
                        sendResponse(ws, request_id, 'success', { message: `Unequipped ${piece.name} from ${dest}` });
                    } catch (err) {
                        sendResponse(ws, request_id, 'error', { error: 'Unequip failed: ' + err.message });
                    }
                    break;
                }

                case 'toss': {
                    if (!params.itemName && params.amount == null) {
                        // Toss entire held stack
                        bot.tossStack(null).then(() => {
                            sendResponse(ws, request_id, 'success', { message: 'Tossed held stack' });
                        }).catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: err.message });
                        });
                        return;
                    }
                    const tossItem = params.itemName
                        ? bot.inventory.items().find(i => i.name.includes(params.itemName))
                        : bot.heldItem;
                    if (!tossItem) {
                        sendResponse(ws, request_id, 'error', { error: `Item not found for tossing` });
                        return;
                    }
                    const tossAmount = params.amount || 1;
                    bot.toss(tossItem.type, null, tossAmount).then(() => {
                        sendResponse(ws, request_id, 'success', { message: `Tossed ${tossAmount}x ${tossItem.name}` });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                case 'setQuickBarSlot': {
                    if (params.slot == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing slot parameter (0-8)' });
                        return;
                    }
                    bot.setQuickBarSlot(params.slot);
                    sendResponse(ws, request_id, 'success', { slot: params.slot, heldItem: bot.heldItem ? bot.heldItem.name : null });
                    break;
                }

                // ── Combat ──

                case 'attack': {
                    let target;
                    if (params.entityName) {
                        target = Object.values(bot.entities).find(e =>
                            e.name && e.name.toLowerCase().includes(params.entityName.toLowerCase()) &&
                            e !== bot.entity
                        );
                    } else {
                        // Attack nearest hostile
                        target = Object.values(bot.entities).find(e =>
                            e.type === 'mob' && e !== bot.entity &&
                            bot.entity.position.distanceTo(e.position) < (params.range || 5)
                        );
                    }
                    if (!target) {
                        sendResponse(ws, request_id, 'error', { error: 'No target found' });
                        return;
                    }
                    bot.attack(target);
                    sendResponse(ws, request_id, 'success', {
                        target: target.name || target.username || 'unknown',
                        health: target.health,
                        position: target.position
                    });
                    break;
                }

                case 'useOn': {
                    if (!params.entityName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing entityName parameter' });
                        return;
                    }
                    const useTarget = Object.values(bot.entities).find(e =>
                        e.name && e.name.toLowerCase().includes(params.entityName.toLowerCase())
                    );
                    if (!useTarget) {
                        sendResponse(ws, request_id, 'error', { error: `Entity '${params.entityName}' not found` });
                        return;
                    }
                    try {
                        bot.useOn(useTarget);
                        sendResponse(ws, request_id, 'success', { message: `Used on ${useTarget.name || useTarget.username || 'unknown'}` });
                    } catch (err) {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    }
                    break;
                }

                case 'activateItem': {
                    bot.activateItem();
                    sendResponse(ws, request_id, 'success', { message: 'Item activated' });
                    break;
                }

                case 'deactivateItem': {
                    bot.deactivateItem();
                    sendResponse(ws, request_id, 'success', { message: 'Item deactivated' });
                    break;
                }

                // ── World query ──

                case 'nearbyEntities': {
                    const maxDist = params.maxDistance || 16;
                    const entities = Object.values(bot.entities)
                        .filter(e => e !== bot.entity && bot.entity.position.distanceTo(e.position) <= maxDist)
                        .map(e => ({
                            name: e.name || e.username || 'unknown',
                            type: e.type,
                            position: e.position,
                            health: e.health,
                            distance: bot.entity.position.distanceTo(e.position)
                        }))
                        .sort((a, b) => a.distance - b.distance)
                        .slice(0, params.limit || 20);
                    sendResponse(ws, request_id, 'success', { entities });
                    break;
                }

                case 'findBlocks': {
                    if (!params.blockName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing blockName parameter' });
                        return;
                    }
                    const maxDistance = params.maxDistance || 64;
                    const count = params.count || 10;
                    const pos = bot.entity.position;
                    const blocks = bot.findBlocks({
                        matching: (block) => block.name.includes(params.blockName),
                        maxDistance: maxDistance,
                        count: count,
                        point: pos
                    });
                    sendResponse(ws, request_id, 'success', {
                        blockName: params.blockName,
                        blocks: blocks.map(b => {
                            const blk = bot.blockAt(b);
                            return blk ? { name: blk.name, position: { x: b.x, y: b.y, z: b.z } }
                                       : { name: 'unknown', position: { x: b.x, y: b.y, z: b.z } };
                        })
                    });
                    break;
                }

                case 'getBlock': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const block = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!block) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position (chunk not loaded?)' });
                        return;
                    }
                    sendResponse(ws, request_id, 'success', {
                        name: block.name,
                        displayName: block.displayName,
                        hardness: block.hardness,
                        boundingBox: block.boundingBox,
                        position: block.position
                    });
                    break;
                }

                // ── Chat / messaging ──

                case 'whisper': {
                    if (!params.username || !params.message) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing username or message parameter' });
                        return;
                    }
                    bot.whisper(params.username, params.message);
                    sendResponse(ws, request_id, 'success', { message: `Whispered to ${params.username}` });
                    break;
                }

                case 'sleep': {
                    const bed = bot.findBlock({
                        matching: (block) => bot.isABed(block),
                        maxDistance: 16
                    });
                    if (!bed) {
                        sendResponse(ws, request_id, 'error', { error: 'No bed found nearby' });
                        return;
                    }
                    bot.sleep(bed).then(() => {
                        sendResponse(ws, request_id, 'success', { message: 'Sleeping' });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                case 'wake': {
                    bot.wake().then(() => {
                        sendResponse(ws, request_id, 'success', { message: 'Woken up' });
                    }).catch((err) => {
                        sendResponse(ws, request_id, 'error', { error: err.message });
                    });
                    return;
                }

                // ── Riding / mounting ──

                case 'mount': {
                    let targetEntity = null;
                    if (params.entityName) {
                        targetEntity = Object.values(bot.entities).find(e =>
                            (e.name && e.name.toLowerCase().includes(params.entityName.toLowerCase())) ||
                            (e.username && e.username.toLowerCase().includes(params.entityName.toLowerCase()))
                        );
                    } else {
                        // Mount nearest rideable entity (minecart, boat, horse, etc.)
                        const rideables = ['minecart', 'boat', 'horse', 'donkey', 'mule', 'llama', 'pig', 'strider'];
                        let nearest = null;
                        let nearestDist = Infinity;
                        for (const e of Object.values(bot.entities)) {
                            if (e === bot.entity) continue;
                            const name = (e.name || '').toLowerCase();
                            if (!rideables.some(r => name.includes(r))) continue;
                            const dist = bot.entity.position.distanceTo(e.position);
                            if (dist < nearestDist) {
                                nearestDist = dist;
                                nearest = e;
                            }
                        }
                        targetEntity = nearest;
                    }
                    if (!targetEntity) {
                        sendResponse(ws, request_id, 'error', { error: params.entityName ? `Entity '${params.entityName}' not found` : 'No rideable entity nearby' });
                        return;
                    }
                    bot.mount(targetEntity);
                    sendResponse(ws, request_id, 'success', {
                        mounted: targetEntity.name || targetEntity.username || 'unknown',
                        position: targetEntity.position,
                    });
                    break;
                }

                case 'dismount': {
                    if (!bot.vehicle) {
                        sendResponse(ws, request_id, 'success', { message: 'Not riding anything' });
                        return;
                    }
                    bot.dismount();
                    sendResponse(ws, request_id, 'success', { message: 'Dismounted' });
                    break;
                }

                case 'setControlState': {
                    if (!params.control) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing control parameter (forward/back/left/right/jump/sneak/sprint)' });
                        return;
                    }
                    const state = params.state !== false;
                    bot.setControlState(params.control, state);
                    sendResponse(ws, request_id, 'success', { control: params.control, state: state });
                    break;
                }

                // ── Container / inventory inspection ──

                case 'findContainers': {
                    const maxDistance = params.maxDistance || 32;
                    const containerNames = [
                        'chest', 'trapped_chest', 'ender_chest',
                        'barrel', 'shulker_box',
                        'furnace', 'blast_furnace', 'smoker',
                        'dispenser', 'dropper', 'hopper',
                        'brewing_stand',
                    ];
                    const blocks = bot.findBlocks({
                        matching: (block) => containerNames.some(n => block.name.includes(n)),
                        maxDistance: maxDistance,
                        count: params.count || 20,
                        point: bot.entity.position,
                    });
                    const result = blocks.map(pos => {
                        const b = bot.blockAt(pos);
                        return {
                            name: b ? b.name : 'unknown',
                            position: { x: pos.x, y: pos.y, z: pos.z },
                        };
                    });
                    sendResponse(ws, request_id, 'success', {
                        containers: result,
                        count: result.length,
                    });
                    break;
                }

                case 'viewContainer': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const containerBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!containerBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    bot.openContainer(containerBlock)
                        .then((window) => {
                            const items = window.containerItems().map(i => ({
                                name: i.name,
                                count: i.count,
                                displayName: i.displayName || i.name,
                            }));
                            bot.closeWindow(window);
                            sendResponse(ws, request_id, 'success', {
                                block: containerBlock.name,
                                position: { x: params.x, y: params.y, z: params.z },
                                items: items,
                                totalSlots: window.inventoryStart !== undefined ? items.length : items.length,
                            });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open container: ' + err.message });
                        });
                    return;
                }

                case 'takeFromContainer': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    if (!params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing itemName parameter' });
                        return;
                    }
                    const takeBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!takeBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    const takeCount = params.count || 1;
                    bot.openContainer(takeBlock)
                        .then((window) => {
                            const target = window.containerItems().find(i => i.name.includes(params.itemName));
                            if (!target) {
                                bot.closeWindow(window);
                                sendResponse(ws, request_id, 'error', { error: `Item '${params.itemName}' not found in container` });
                                return;
                            }
                            const actual = Math.min(takeCount, target.count);
                            window.withdraw(target.type, target.metadata, actual)
                                .then(() => {
                                    bot.closeWindow(window);
                                    sendResponse(ws, request_id, 'success', {
                                        taken: { name: target.name, count: actual },
                                        from: { name: takeBlock.name, position: { x: params.x, y: params.y, z: params.z } },
                                    });
                                })
                                .catch((err) => {
                                    bot.closeWindow(window);
                                    sendResponse(ws, request_id, 'error', { error: 'Withdraw failed: ' + err.message });
                                });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open container: ' + err.message });
                        });
                    return;
                }

                case 'putToContainer': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    if (!params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing itemName parameter' });
                        return;
                    }
                    const putBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!putBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    const putCount = params.count || 1;
                    const botItem = bot.inventory.items().find(i => i.name.includes(params.itemName));
                    if (!botItem) {
                        sendResponse(ws, request_id, 'error', { error: `Item '${params.itemName}' not found in bot inventory` });
                        return;
                    }
                    const actual = Math.min(putCount, botItem.count);
                    bot.openContainer(putBlock)
                        .then((window) => {
                            window.deposit(botItem.type, botItem.metadata, actual)
                                .then(() => {
                                    bot.closeWindow(window);
                                    sendResponse(ws, request_id, 'success', {
                                        deposited: { name: botItem.name, count: actual },
                                        into: { name: putBlock.name, position: { x: params.x, y: params.y, z: params.z } },
                                    });
                                })
                                .catch((err) => {
                                    bot.closeWindow(window);
                                    sendResponse(ws, request_id, 'error', { error: 'Deposit failed: ' + err.message });
                                });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open container: ' + err.message });
                        });
                    return;
                }

                case 'openFurnace': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const furnaceBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!furnaceBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    bot.openFurnace(furnaceBlock)
                        .then((furnace) => {
                            const status = {
                                inputItem: furnace.inputItem() ? furnace.inputItem().name : null,
                                fuelItem: furnace.fuelItem() ? furnace.fuelItem().name : null,
                                outputItem: furnace.outputItem() ? furnace.outputItem().name : null,
                                fuel: furnace.fuel,
                                progress: furnace.progress,
                            };
                            sendResponse(ws, request_id, 'success', status);
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open furnace: ' + err.message });
                        });
                    return;
                }

                case 'furnacePutInput': {
                    if (params.x == null || params.y == null || params.z == null || !params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z or itemName parameter' });
                        return;
                    }
                    const fBlock = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!fBlock) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    const botItem = bot.inventory.items().find(i => i.name.includes(params.itemName));
                    if (!botItem) {
                        sendResponse(ws, request_id, 'error', { error: `Item '${params.itemName}' not found in inventory` });
                        return;
                    }
                    bot.openFurnace(fBlock)
                        .then((furnace) => {
                            furnace.putInput(botItem.type, botItem.metadata, params.count || botItem.count)
                                .then(() => {
                                    sendResponse(ws, request_id, 'success', { message: `Put ${botItem.name} into furnace` });
                                })
                                .catch((err) => {
                                    sendResponse(ws, request_id, 'error', { error: 'putInput failed: ' + err.message });
                                });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open furnace: ' + err.message });
                        });
                    return;
                }

                case 'furnacePutFuel': {
                    if (params.x == null || params.y == null || params.z == null || !params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z or itemName parameter' });
                        return;
                    }
                    const fBlock2 = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!fBlock2) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    const fuelItem = bot.inventory.items().find(i => i.name.includes(params.itemName));
                    if (!fuelItem) {
                        sendResponse(ws, request_id, 'error', { error: `Item '${params.itemName}' not found in inventory` });
                        return;
                    }
                    bot.openFurnace(fBlock2)
                        .then((furnace) => {
                            furnace.putFuel(fuelItem.type, fuelItem.metadata, params.count || 1)
                                .then(() => {
                                    sendResponse(ws, request_id, 'success', { message: `Put ${fuelItem.name} as fuel` });
                                })
                                .catch((err) => {
                                    sendResponse(ws, request_id, 'error', { error: 'putFuel failed: ' + err.message });
                                });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open furnace: ' + err.message });
                        });
                    return;
                }

                case 'furnaceTakeOutput': {
                    if (params.x == null || params.y == null || params.z == null) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing x, y, z parameters' });
                        return;
                    }
                    const fBlock3 = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    if (!fBlock3) {
                        sendResponse(ws, request_id, 'error', { error: 'No block at this position' });
                        return;
                    }
                    bot.openFurnace(fBlock3)
                        .then((furnace) => {
                            furnace.takeOutput()
                                .then((item) => {
                                    sendResponse(ws, request_id, 'success', { message: `Took ${item.name} (${item.count}) from furnace` });
                                })
                                .catch((err) => {
                                    sendResponse(ws, request_id, 'error', { error: 'takeOutput failed: ' + err.message });
                                });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Cannot open furnace: ' + err.message });
                        });
                    return;
                }

                case 'craft': {
                    if (!params.itemName) {
                        sendResponse(ws, request_id, 'error', { error: 'Missing itemName parameter' });
                        return;
                    }
                    const craftItem = bot.registry.itemsByName[params.itemName];
                    if (!craftItem) {
                        sendResponse(ws, request_id, 'error', { error: `Unknown item: ${params.itemName}` });
                        return;
                    }
                    let craftTable = null;
                    if (params.x != null && params.y != null && params.z != null) {
                        craftTable = bot.blockAt(new Vec3(params.x, params.y, params.z));
                    }
                    const recipes = bot.recipesFor(craftItem.id, null, params.count || 1, craftTable);
                    if (!recipes || recipes.length === 0) {
                        sendResponse(ws, request_id, 'error', { error: `No recipe found for ${params.itemName}` });
                        return;
                    }
                    bot.craft(recipes[0], params.count || 1, craftTable)
                        .then(() => {
                            sendResponse(ws, request_id, 'success', { message: `Crafted ${params.count || 1}x ${params.itemName}` });
                        })
                        .catch((err) => {
                            sendResponse(ws, request_id, 'error', { error: 'Craft failed: ' + err.message });
                        });
                    return;
                }

                case 'get_chat_messages': {
                    const msgs = chatMessages.splice(0, chatMessages.length);
                    sendResponse(ws, request_id, 'success', { messages: msgs });
                    break;
                }

                default:
                    sendResponse(ws, request_id, 'error', { error: `Unknown action: ${action}` });
            }
        });

        ws.on('close', () => {
            console.log('[WS] Client disconnected');
        });
    });

    wss.on('error', (err) => {
        console.error('[WS] Server error:', err);
    });
}

/**
 * Stop the WebSocket server.
 */
function stopWebSocketServer() {
    if (wss) {
        wss.close(() => {
            console.log('[WS] WebSocket server stopped');
            wss = null;
        });
    }
}

/**
 * Start the entire service (bot + WebSocket) if enabled.
 */
function startService() {
    if (config.enabled) {
        console.log('[Service] Starting bot and WebSocket service...');
        startBot();
        startWebSocketServer();
    } else {
        console.log('[Service] Service is disabled (enabled=false). Nothing started. Please press Ctrl+C (or Command+c) to terminate the process');
        // Ensure any running instances are stopped
        stopBot();
        stopWebSocketServer();
    }
}

/**
 * Stop the entire service.
 */
function stopService() {
    stopBot();
    stopWebSocketServer();
}

// ---------- Initial startup ----------
startService();

// ---------- Hot-reload on configuration changes ----------
fs.watchFile(CONFIG_PATH, (curr, prev) => {
    if (curr.mtimeMs === prev.mtimeMs) return;
    console.log('[HotReload] Configuration file changed, reloading...');

    const oldEnabled = config.enabled;
    const oldWsUrl = config.websocket.url;
    const oldHost = config.bot.server_host;
    const oldPort = config.bot.server_port;

    loadConfig();

    // Check if the enabled state changed
    if (config.enabled !== oldEnabled) {
        if (config.enabled) {
            console.log('[HotReload] Service enabled, starting...');
            // If URL or bot parameters changed, they will be picked up by startService
            startService();
        } else {
            console.log('[HotReload] Service disabled, stopping...');
            stopService();
        }
    } else if (config.enabled) {
        // If still enabled, check for changes that require restart
        const wsPortChanged = getWSPortFromUrl(config.websocket.url) !== getWSPortFromUrl(oldWsUrl);
        const botHostChanged = config.bot.server_host !== oldHost;
        const botPortChanged = config.bot.server_port !== oldPort;

        if (wsPortChanged || botHostChanged || botPortChanged) {
            console.log('[HotReload] Critical parameters changed, restarting service...');
            // Stop and restart the whole service
            stopService();
            startService();
        } else {
            // Other changes (username, password, reconnect_interval, timeout) – 
            // we can apply them without full restart by calling startBot again but that may not be necessary.
            // For simplicity, we just log that parameters changed; user may want to restart manually.
            console.log('[HotReload] Non-critical parameters changed (username, password, etc.). Restart manually if needed.');
        }
    }

    console.log('[HotReload] Configuration applied');
});

console.log('[Bot] Service initialized. Waiting for commands...');
"""


def write_default_init(mineflayer_path: str):
    with open(os.path.join(mineflayer_path), "w", encoding="utf-8") as f:
        f.write(_INIT_JS_CONTENT)


def get_default_init_hash() -> str:
    return hashlib.md5(_INIT_JS_CONTENT.encode("utf-8")).hexdigest()


_PACKAGE_JSON_CONTENT = json.dumps({
    "name": "games-ai-mineflayer",
    "version": "1.0.0",
    "description": "Mineflayer bot service for Games-AI MCDR plugin",
    "private": True,
    "dependencies": {
        "mineflayer": "latest",
        "ws": "latest",
        "vec3": "latest",
        "mineflayer-pathfinder": "latest",
        "mineflayer-mcefly": "latest"
    }
}, indent=2)


def write_package_json(package_json_path: str):
    with open(package_json_path, "w", encoding="utf-8") as f:
        f.write(_PACKAGE_JSON_CONTENT)


def _install_dependencies(script_dir: str, logger=None, refresh: bool = False):
    """Install (or refresh to latest) the npm dependencies of the bot service.

    Explicit package names are always passed so that ``refresh=True`` upgrades
    every package to the current ``latest`` dist-tag even when node_modules
    already exists. ``--no-save`` keeps the plugin-owned package.json intact.
    A marker file is written on success so that a later launch can skip the
    refresh when the dependencies are already up to date.
    """
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    if logger:
        logger.info("[Mineflayer] Installing/updating npm dependencies, this may take a while...")
    try:
        result = subprocess.run(
            [npm_cmd, "install", "--no-save", "--no-audit", "--no-fund", *list(_DEPS_PACKAGES)],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if logger:
            for line in (result.stdout + result.stderr).splitlines():
                line = line.strip()
                if line:
                    logger.info(f"[Mineflayer] {line}")
        if result.returncode != 0:
            msg = f"npm install failed (exit {result.returncode}): {result.stderr[-500:]}"
            if logger:
                logger.error(f"[Mineflayer] {msg}")
            raise RuntimeError(msg)
        with open(os.path.join(script_dir, _DEPS_MARKER_NAME), "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        if logger:
            logger.info("[Mineflayer] npm dependencies installed successfully")
    except FileNotFoundError:
        msg = "npm is not installed or not in PATH"
        if logger:
            logger.error(f"[Mineflayer] {msg}")
        raise RuntimeError(msg) from None


def _launch_node(init_js_path: str, logger=None) -> subprocess.Popen:
    """Launch the Node.js bot service and stream its output to the logger."""
    global _process
    script_dir = os.path.dirname(os.path.abspath(init_js_path))
    abs_init_js = os.path.abspath(init_js_path)
    if not os.path.isfile(abs_init_js):
        raise FileNotFoundError(f"init.js not found at {abs_init_js}")

    if logger:
        logger.info(f"[Mineflayer] Launching node {abs_init_js}")

    node_cmd = "node"
    use_output = logger is not None
    if sys.platform == "win32":
        _process = subprocess.Popen(
            [node_cmd, abs_init_js],
            cwd=script_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if use_output else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if use_output else subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        _process = subprocess.Popen(
            [node_cmd, abs_init_js],
            cwd=script_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if use_output else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if use_output else subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    if use_output:
        threading.Thread(
            target=_stream_process_output,
            args=(_process, logger, abs_init_js),
            daemon=True,
            name="MineflayerBotLog",
        ).start()

    return _process


def run_node(init_js_path: str, logger=None) -> subprocess.Popen | None:
    """Start the Mineflayer Node.js service.

    Dependencies are installed when node_modules is missing. Existing
    installations created by older plugin versions (no marker file) are
    refreshed once to the latest versions, so the bot keeps working after the
    Minecraft server is upgraded to a newer version.
    """
    global _process
    with _deps_repair_lock:
        _kill_mineflayer_process()
        script_dir = os.path.dirname(os.path.abspath(init_js_path))

        node_modules_dir = os.path.join(script_dir, "node_modules")
        marker_path = os.path.join(script_dir, _DEPS_MARKER_NAME)

        if not os.path.isdir(node_modules_dir):
            _install_dependencies(script_dir, logger, refresh=False)
        elif not os.path.isfile(marker_path):
            # node_modules exists but was installed by an older plugin version
            # (or manually): refresh it once so the installed mineflayer
            # supports the current server version.
            try:
                _install_dependencies(script_dir, logger, refresh=True)
            except RuntimeError as e:
                if logger:
                    logger.warning(
                        f"[Mineflayer] Could not refresh npm dependencies ({e}), "
                        "starting with the existing dependencies..."
                    )

        return _launch_node(init_js_path, logger)


def _handle_version_unsupported(proc: subprocess.Popen, logger, init_js_path: str | None):
    """Auto-repair when the bot reports an unsupported server version.

    Refreshes the npm dependencies to the latest versions and restarts the
    Node.js service. Guarded by a cooldown and an attempt cap to avoid
    restart loops when the latest mineflayer still does not support the
    server version.
    """
    global _process, _deps_repair_count, _deps_repair_last
    with _deps_repair_lock:
        if _process is not proc:
            return  # the process was already replaced or stopped; nothing to repair here
        now = time.time()
        if _deps_repair_count >= _DEPS_REPAIR_MAX:
            if logger:
                logger.error(
                    "[Mineflayer] Server version is not supported by mineflayer and the "
                    f"dependency refresh was already attempted {_deps_repair_count} time(s). "
                    "Please update this plugin or wait for a newer mineflayer release on npm."
                )
            return
        if now - _deps_repair_last < _DEPS_REPAIR_COOLDOWN:
            if logger:
                logger.warning(
                    "[Mineflayer] Unsupported server version detected again, "
                    "will retry the dependency refresh later..."
                )
            return
        _deps_repair_count += 1
        _deps_repair_last = now
        if logger:
            logger.warning(
                "[Mineflayer] Detected unsupported server version. Updating npm "
                "dependencies and restarting the bot..."
            )
        try:
            # Install first so a failed refresh does not kill the (broken but
            # alive) old process.
            script_dir = os.path.dirname(os.path.abspath(init_js_path)) if init_js_path else None
            if script_dir:
                _install_dependencies(script_dir, logger, refresh=True)
            _kill_mineflayer_process()
            if init_js_path:
                _launch_node(init_js_path, logger)
        except Exception as e:
            if logger:
                logger.error(f"[Mineflayer] Failed to update dependencies and restart the bot: {e}")


def _stream_process_output(proc: subprocess.Popen, logger, init_js_path: str | None = None):
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            line = line.rstrip('\n\r')
            if line:
                logger.info(f"[Mineflayer] {line}")
                if _UNSUPPORTED_VERSION_RE.search(line):
                    _handle_version_unsupported(proc, logger, init_js_path)
    except (ValueError, OSError):
        pass
    finally:
        try:
            proc.stdout.close()
        except (ValueError, OSError):
            pass


def stop_mineflayer_process():
    global _process
    _kill_mineflayer_process()


def _kill_mineflayer_process():
    global _process
    if _process is None:
        return
    pid = _process.pid
    if pid is None:
        return

    _process.terminate()
    try:
        _process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        _process.kill()
        try:
            _process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
            try:
                _process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    _process = None
