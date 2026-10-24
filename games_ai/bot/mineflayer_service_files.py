"""The service files the Mineflayer bot is generated from: ``init.js`` and ``package.json``.

The bot service is one long JavaScript program. It used to live at the top of
``mineflayer.py`` and took 70% of that file, which buried the Python half -- the peer client,
the four bot tools and the node process lifecycle -- under a wall of unreadable text. A syntax
error in the JS is a failure of a running Node process, not an import error here, so the two
halves never needed to be read together in the first place.

This module holds the file templates and their writers, and nothing else: no connection, no
process, no lock. ``on_load`` writes ``init.js`` when the file is missing or when its md5 no
longer matches :func:`get_default_init_hash`, and ``!!gamesai reload`` does the same with the
path from ``plugin_config.mineflayer_init_js_path``. That comparison is the only reason the
hash exists: **if the JavaScript below changes, this hash changes with it**, and every deployed
bot gets the new file on its next load.

The writers keep the encoding and newline handling they always had (``open(..., "w")`` with the
platform's default translation), so a file written here is byte-identical to one written by the
previous version of this code.
"""

import hashlib
import json
import os


_INIT_JS_CONTENT = r"""// This is the script for the Mineflayer bot service.
const mineflayer = require('mineflayer');
const WebSocket = require('ws');          // the hub client socket
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
                timeout: parsed.websocket?.timeout || DEFAULT_CONFIG.websocket.timeout,
                token: parsed.websocket?.token || '',
                version: parsed.websocket?.version || ''
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

// ---------- Bot and hub state ----------
let bot = null;
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
// ---------- GamesAI hub link ----------
// The bot is a *client* of the cross-server hub, exactly like every MCDR instance is: it
// registers under its Minecraft username and answers `bot_action` requests. The plugin never
// listens for the bot, and the bot no longer owns a port.
const PEER_APP = 'mineflayer_bot';   // what this bot announces to the hub
const HUB_APP = 'games_ai_mcdr';     // what a GamesAI-MCDR hub identifies itself as
const PROTOCOL_VERSION = 1;
// Close codes that mean "retrying cannot help" (see websockets_server.py). 4007/4008 are the
// enrolment ones: the bot has to be given a token before it can register at all.
const FATAL_CLOSE_CODES = new Set([4001, 4002, 4003, 4004, 4005, 4007, 4008]);

let hubSocket = null;
let hubReconnectTimer = null;
// request_id -> the peer that asked, so the answer can be routed back to it.
const pendingRequestSources = new Map();
const MAX_PENDING_REQUESTS = 4096;

/**
 * Answer one request. This is the single reply path of the action switch below.
 */
function sendResponse(ws, requestId, status, data = null) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const target = pendingRequestSources.get(requestId) || null;
    pendingRequestSources.delete(requestId);
    ws.send(JSON.stringify({
        type: 'reply',
        request_id: requestId,
        source: config.bot.username,
        target: target,
        // `ok` means the request was processed; the action outcome travels in data.status.
        ok: true,
        data: { status: status, data: data }
    }));
}

/**
 * Run one bot action and answer it.
 */
function handleBotAction(ws, request_id, action, params) {
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
            let gotoTimer = null;

            const cleanup = () => {
                if (gotoTimer !== null) {
                    clearTimeout(gotoTimer);
                    gotoTimer = null;
                }
                bot.removeListener('goal_reached', onGoalReached);
                bot.removeListener('path_update', onPathUpdate);
                // Always drop the goal, also when the answer is a timeout/no-path failure:
                // leaving it set would let the bot keep walking after the tool already said
                // it stopped (and the next action would run while it is still moving).
                bot.pathfinder.setGoal(null);
            };

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

            bot.on('goal_reached', onGoalReached);
            bot.on('path_update', onPathUpdate);
            bot.pathfinder.setGoal(goal);

            gotoTimer = setTimeout(() => {
                gotoTimer = null;
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

}

/**
 * Handle one frame from the hub.
 */
function handleHubFrame(raw) {
    let msg;
    try {
        msg = JSON.parse(raw);
    } catch (e) {
        console.warn('[WS] Ignoring a non-JSON frame from the hub');
        return;
    }
    if (!msg || typeof msg !== 'object') return;

    if (msg.type === 'hello_ack') {
        if (msg.app !== HUB_APP || msg.protocol !== PROTOCOL_VERSION) {
            console.error('[WS] That address is not a GamesAI hub; closing the link');
            if (hubSocket) hubSocket.close();
            return;
        }
        if (msg.token) {
            // The hub provisioned this bot: it had no token, so the hub issued one and put it
            // in the ack. Keep it in memory for the next reconnect (the plugin also stores it
            // in this config file, so a restart picks it up again).
            config.websocket.token = msg.token;
            console.log('[WS] The hub issued this bot a token; it will be reused on reconnect');
        }
        if (msg.expires_in) {
            console.log(`[WS] This bot's token expires in ${msg.expires_in}s`);
        }
        console.log(`[WS] Registered on hub '${msg.hub}' as '${config.bot.username}'`);
        return;
    }
    if (msg.type === 'event') return;                      // peer list updates and the like
    if (msg.type !== 'message') return;

    const requestId = msg.request_id;
    const payload = msg.data || {};
    if (pendingRequestSources.size > MAX_PENDING_REQUESTS) pendingRequestSources.clear();
    pendingRequestSources.set(requestId, msg.source);

    if (msg.action === 'bot_action') {
        // Model-generated arguments reach this switch directly. A thrown switch used to escape
        // the frame handler, leave the request with no answer and take the whole bot process
        // down (no chat, no reconnect): answer with an error frame instead, keep serving.
        try {
            handleBotAction(hubSocket, requestId, payload.action, payload.params || {});
        } catch (err) {
            const detail = (err && err.message) ? err.message : String(err);
            console.error(`[WS] bot_action ${payload.action} failed: ${detail}`);
            try {
                sendResponse(hubSocket, requestId, 'error', { error: `invalid parameters: ${detail}` });
            } catch (sendErr) {
                console.error('[WS] could not report the failed action:',
                              (sendErr && sendErr.message) ? sendErr.message : sendErr);
            }
        }
    } else if (msg.action === 'ping') {
        sendResponse(hubSocket, requestId, 'success', { message: 'pong' });
    } else {
        sendResponse(hubSocket, requestId, 'error', { error: `Unknown action: ${msg.action}` });
    }
}

/**
 * Open (or keep open) the link to the GamesAI hub.
 */
function connectToHub() {
    if (hubSocket && (hubSocket.readyState === WebSocket.OPEN || hubSocket.readyState === WebSocket.CONNECTING)) {
        return;
    }
    const hubUrl = config.websocket.url;
    let socket;
    try {
        socket = new WebSocket(hubUrl);
    } catch (e) {
        console.error(`[WS] Invalid hub address '${hubUrl}': ${e.message}`);
        return;
    }
    hubSocket = socket;
    console.log(`[WS] Connecting to the GamesAI hub at ${hubUrl}`);

    socket.on('open', () => {
        const hello = {
            type: 'hello',
            app: PEER_APP,
            protocol: PROTOCOL_VERSION,
            server: config.bot.username,
            version: config.websocket.version || 'unknown'
        };
        if (config.websocket.token) {
            hello.token = config.websocket.token;
        } else {
            // No token yet: ask the hub to provision this bot. A hub on the same machine, or
            // one that already knows a node on this machine, answers with a token in the ack;
            // any other hub records the request and closes with 4007.
            hello.enroll = true;
        }
        socket.send(JSON.stringify(hello));
    });
    socket.on('message', (raw) => handleHubFrame(raw));
    socket.on('error', (err) => console.error('[WS] Hub connection error:', err.message));
    socket.on('close', (code, reason) => {
        const text = reason ? reason.toString() : '';
        console.log(`[WS] Disconnected from the hub (code ${code}${text ? ', ' + text : ''})`);
        if (hubSocket === socket) hubSocket = null;
        if (FATAL_CLOSE_CODES.has(code)) {
            if (code === 4007) {
                console.error('[WS] This bot is not enrolled yet: the hub recorded the request, so now run !!gamesai node token ' + config.bot.username + ' on the hub and put the token into websocket.token here.');
            } else if (code === 4008) {
                console.error('[WS] This bot\'s enrolment token expired: run !!gamesai node rotate ' + config.bot.username + ' on the hub and put the new token into websocket.token here.');
            } else {
                console.error('[WS] The hub rejected this bot; not retrying. Check websocket.uri and the bot username.');
            }
            return;
        }
        scheduleHubReconnect();
    });
}

function scheduleHubReconnect() {
    if (hubReconnectTimer || !config.enabled) return;
    const delay = Math.max(1, config.websocket.reconnect_interval || 10) * 1000;
    hubReconnectTimer = setTimeout(() => {
        hubReconnectTimer = null;
        connectToHub();
    }, delay);
}

/**
 * Close the link to the hub.
 */
function disconnectFromHub() {
    if (hubReconnectTimer) {
        clearTimeout(hubReconnectTimer);
        hubReconnectTimer = null;
    }
    if (hubSocket) {
        const socket = hubSocket;
        hubSocket = null;
        try {
            socket.close(1000, 'service stopping');
        } catch (e) {
            // already gone
        }
        console.log('[WS] Hub link closed');
    }
}


/**
 * Start the entire service (bot + hub link) if enabled.
 */
function startService() {
    if (config.enabled) {
        console.log('[Service] Starting bot and cross-server link...');
        startBot();
        connectToHub();
    } else {
        console.log('[Service] Service is disabled (enabled=false). Nothing started. Please press Ctrl+C (or Command+c) to terminate the process');
        // Ensure any running instances are stopped
        stopBot();
        disconnectFromHub();
    }
}

/**
 * Stop the entire service.
 */
function stopService() {
    stopBot();
    disconnectFromHub();
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
        const wsUrlChanged = config.websocket.url !== oldWsUrl;
        const botHostChanged = config.bot.server_host !== oldHost;
        const botPortChanged = config.bot.server_port !== oldPort;

        if (wsUrlChanged || botHostChanged || botPortChanged) {
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
