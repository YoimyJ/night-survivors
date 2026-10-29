"""Night Survivors - the game rules.

This file holds only the rules: no pygame, no drawing, no sound.
Time always moves in one fixed step (TICK), and every timer in the game is
counted in whole ticks so nothing drifts.
"""

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

TICK = 1.0 / 60.0

DATA_FILE = Path(__file__).resolve().parent / "data" / "game.json"


def load_config(path=DATA_FILE):
    """Read all the numbers from data/game.json."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def ticks_for(seconds):
    """How many whole ticks make up this many seconds."""
    return max(1, int(round(float(seconds) / TICK)))


@dataclass
class Hero:
    x: float = 0.0
    y: float = 0.0
    hp: float = 0.0
    max_hp: float = 0.0
    speed: float = 0.0  # base speed, before the Swift Boots


@dataclass
class Enemy:
    kind: str
    x: float
    y: float
    hp: float
    last_hit_tick: int = -10 ** 9  # game tick when this enemy last hurt the hero
    blade_hits: dict = field(default_factory=dict)  # blade number -> tick of its last hit

    def is_boss(self, config):
        return bool(config["enemies"][self.kind].get("boss"))


@dataclass
class Spark:
    x: float
    y: float
    vx: float
    vy: float
    damage: float
    life: float  # seconds left before it disappears
    radius: float = 4.0


@dataclass
class Gem:
    x: float
    y: float
    xp: float


@dataclass
class State:
    config: dict
    rng: random.Random = field(default_factory=random.Random)
    ticks: int = 0
    time: float = 0.0  # seconds, only for the screen
    status: str = "playing"  # "playing", "levelup" (paused, cards shown) or "dead"
    hero: Hero = field(default_factory=Hero)
    enemies: list = field(default_factory=list)
    sparks: list = field(default_factory=list)
    gems: list = field(default_factory=list)
    kills: int = 0
    level: int = 1
    xp: float = 0.0
    boss_spawned: bool = False
    weapons: dict = field(default_factory=dict)
    passives: dict = field(default_factory=dict)
    choices: list = field(default_factory=list)  # the cards on screen while status == "levelup"
    events: list = field(default_factory=list)  # what just happened, for the sounds and effects
    blade_angle: float = 0.0
    next_spawn_tick: int = 0
    next_fire_tick: int = 0
    next_ring_tick: int = 0
    # where the hero walks to (world pixels) and whether that target is real
    target_x: float = 0.0
    target_y: float = 0.0
    has_target: bool = False


def new_game(config, rng=None):
    """Make a fresh game state from the numbers in the config."""
    hero_cfg = config["hero"]
    hero = Hero(
        x=0.0,
        y=0.0,
        hp=float(hero_cfg["max_hp"]),
        max_hp=float(hero_cfg["max_hp"]),
        speed=float(hero_cfg["speed"]),
    )
    return State(
        config=config,
        rng=rng if rng is not None else random.Random(),
        hero=hero,
        weapons={"spark_wand": 1},
        next_spawn_tick=ticks_for(config["spawning"]["interval"]),
        next_fire_tick=1,  # the wand shoots as soon as the game starts
        next_ring_tick=ticks_for(config["weapons"]["holy_ring"]["interval"]),
    )


def distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


def hero_value(state, key):
    return float(state.config["hero"][key])


def weapon_level(state, weapon_id):
    return int(state.weapons.get(weapon_id, 0))


def passive_level(state, passive_id):
    return int(state.passives.get(passive_id, 0))


def walk_speed(state):
    """Hero speed with the Swift Boots added."""
    boots = passive_level(state, "swift_boots")
    percent = float(state.config["passives"]["swift_boots"]["speed_percent"])
    return state.hero.speed * (1.0 + percent * boots / 100.0)


def magnet_radius(state):
    """How close a gem must be before it flies to the hero."""
    base = hero_value(state, "magnet_radius")
    level = passive_level(state, "magnet")
    return base + float(state.config["passives"]["magnet"]["radius"]) * level


def spawn_row_for(state, moment):
    """The last spawn row that has started by this time."""
    chosen = None
    for row in state.config["spawn_rows"]:
        if row["from"] <= moment and (chosen is None or row["from"] >= chosen["from"]):
            chosen = row
    return chosen


def nearest_enemy(state, x, y):
    best, best_d = None, None
    for enemy in state.enemies:
        gap = distance(x, y, enemy.x, enemy.y)
        if best_d is None or gap < best_d:
            best, best_d = enemy, gap
    return best


def set_target(state, x, y, active=True):
    """Point the hero at a place in the world (game coordinates)."""
    state.target_x = x
    state.target_y = y
    state.has_target = active


def event(state, name, x=0.0, y=0.0, amount=0.0):
    """Say what just happened, so the screen can answer with a sound or a picture.

    The rules never draw anything: they only leave a short list of notes here,
    and main.py takes them away once per frame.
    """
    state.events.append((name, x, y, amount))


# ---------------------------------------------------------------- XP and cards


def xp_needed(state):
    """XP needed for the next level: 5 at level 1, then 3 more each level."""
    curve = state.config["level_up"]
    return float(curve["first_xp"]) + float(curve["xp_per_level"]) * (state.level - 1)


def card(name, level, text, kind, item_id):
    return {"name": name, "level": level, "text": text, "kind": kind, "id": item_id}


def possible_cards(state):
    """Every card the hero could be offered now."""
    config = state.config
    cards = []
    for weapon_id, weapon in config["weapons"].items():
        level = weapon_level(state, weapon_id)
        if level <= 0:
            if len(state.weapons) < int(config["level_up"]["max_weapons"]):
                cards.append(card(weapon["name"], 1, weapon["text"], "weapon", weapon_id))
        elif level < int(weapon["levels"]):
            cards.append(card(weapon["name"], level + 1, weapon["text"], "weapon", weapon_id))
    for passive_id, passive in config["passives"].items():
        level = passive_level(state, passive_id)
        if level < int(passive["levels"]):
            cards.append(card(passive["name"], level + 1, passive["text"], "passive", passive_id))
    return cards


def offer_choices(state):
    """Pick the cards to show: 3 random ones, or Heal if nothing is left."""
    config = state.config
    count = int(config["level_up"]["cards"])
    options = possible_cards(state)
    picked = state.rng.sample(options, min(count, len(options))) if options else []
    while len(picked) < count:
        picked.append(card("Heal", 0, "Recover %d HP" % config["level_up"]["heal_hp"],
                           "heal", "heal"))
    state.choices = picked


def apply_card(state, chosen):
    """Give the hero what one card promises."""
    config = state.config
    if chosen["kind"] == "weapon":
        state.weapons[chosen["id"]] = chosen["level"]
    elif chosen["kind"] == "passive":
        state.passives[chosen["id"]] = chosen["level"]
        if chosen["id"] == "big_heart":
            heart = config["passives"]["big_heart"]
            state.hero.max_hp += float(heart["max_hp"])
            state.hero.hp = min(state.hero.max_hp,
                                state.hero.hp + float(heart["heal"]))
    else:
        state.hero.hp = min(state.hero.max_hp,
                            state.hero.hp + float(config["level_up"]["heal_hp"]))


def choose(state, index):
    """The player tapped card number `index`: apply it and start the game again."""
    if state.status != "levelup" or not 0 <= index < len(state.choices):
        return
    apply_card(state, state.choices[index])
    state.xp -= xp_needed(state)
    state.level += 1
    state.choices = []
    state.status = "playing"
    if state.xp >= xp_needed(state):
        _start_level_up(state)  # enough XP for another level right away


def _start_level_up(state):
    state.status = "levelup"
    event(state, "levelup")
    offer_choices(state)


def _add_xp(state, amount):
    state.xp += amount
    if state.xp >= xp_needed(state):
        _start_level_up(state)


def _kill_enemy(state, enemy):
    state.enemies.remove(enemy)
    state.kills += 1
    enemy_cfg = state.config["enemies"][enemy.kind]
    event(state, "enemy_died", enemy.x, enemy.y, float(enemy_cfg["radius"]))
    xp = float(enemy_cfg["xp"])
    if xp > 0:
        state.gems.append(Gem(enemy.x, enemy.y, xp))


# ------------------------------------------------------------------- weapons


def spark_stats(state):
    """Damage / interval / number of sparks for the Spark Wand level the hero has."""
    wand = state.config["weapons"]["spark_wand"]
    level = max(1, weapon_level(state, "spark_wand"))
    return {
        "damage": float(wand["damage"]) + float(wand["damage_per_level"]) * (level - 1),
        "interval": max(0.1, float(wand["interval"])
                        - float(wand["interval_minus_per_level"]) * (level - 1)),
        "count": int(wand["count"]) + sum(
            1 for extra in wand["extra_spark_levels"] if level >= extra),
        "speed": float(wand["speed"]),
        "radius": float(wand["radius"]),
        "life": float(wand["life"]),
        "fan": float(wand["fan_degrees"]),
    }


def blade_stats(state):
    """Where the Spin Blades are and how hard they hit."""
    blades = state.config["weapons"]["spin_blades"]
    level = max(1, weapon_level(state, "spin_blades"))
    count = int(blades["count"]) + sum(
        1 for extra in blades["extra_blade_levels"] if level >= extra)
    angle = state.blade_angle
    between = 2.0 * math.pi / count
    positions = [(state.hero.x + math.cos(angle + index * between) * float(blades["orbit_radius"]),
                  state.hero.y + math.sin(angle + index * between) * float(blades["orbit_radius"]))
                 for index in range(count)]
    return {
        "count": count,
        "positions": positions,
        "damage": float(blades["damage"]) + float(blades["damage_per_level"]) * (level - 1),
        "radius": float(blades["blade_radius"]),
        "orbit_radius": float(blades["orbit_radius"]),
        "cooldown_ticks": ticks_for(blades["hit_cooldown"]),
        "turn_ticks": ticks_for(blades["turn_seconds"]),
    }


def ring_stats(state):
    """The Holy Ring around the hero."""
    ring = state.config["weapons"]["holy_ring"]
    level = max(1, weapon_level(state, "holy_ring"))
    return {
        "damage": float(ring["damage"]) + float(ring["damage_per_level"]) * (level - 1),
        "radius": float(ring["radius"]) + float(ring["radius_per_level"]) * (level - 1),
        "interval_ticks": ticks_for(ring["interval"]),
    }


def _move_hero(state):
    if not state.has_target:
        return
    hero = state.hero
    gap = distance(hero.x, hero.y, state.target_x, state.target_y)
    if gap <= hero_value(state, "follow_min_px"):
        return
    ratio = min(1.0, walk_speed(state) * TICK / gap)
    hero.x += (state.target_x - hero.x) * ratio
    hero.y += (state.target_y - hero.y) * ratio


def _spawn_one(state, kind):
    """Put one enemy of this kind on the ring just outside the screen."""
    radius = float(state.config["spawning"]["circle_radius"])
    angle = state.rng.uniform(0.0, 2.0 * math.pi)
    enemy_cfg = state.config["enemies"][kind]
    enemy = Enemy(
        kind=kind,
        x=state.hero.x + math.cos(angle) * radius,
        y=state.hero.y + math.sin(angle) * radius,
        hp=float(enemy_cfg["hp"]),
    )
    state.enemies.append(enemy)
    return enemy


def _spawn_enemies(state, row):
    spawn_cfg = state.config["spawning"]
    if row.get("boss") and not state.boss_spawned:
        state.boss_spawned = True
        _spawn_one(state, row["boss"])
    made = 0
    while (
        len(state.enemies) < row["min_alive"]
        and made < spawn_cfg["max_per_second"]
        and len(state.enemies) < spawn_cfg["max_alive"]
    ):
        kind = row["types"][state.rng.randrange(len(row["types"]))]
        _spawn_one(state, kind)
        made += 1


def _move_enemies(state):
    hero = state.hero
    for enemy in state.enemies:
        speed = float(state.config["enemies"][enemy.kind]["speed"])
        gap = distance(enemy.x, enemy.y, hero.x, hero.y)
        if gap <= 0.0:
            continue
        ratio = min(1.0, speed * TICK / gap)
        enemy.x += (hero.x - enemy.x) * ratio
        enemy.y += (hero.y - enemy.y) * ratio


def _remove_far_enemies(state):
    """Normal enemies that fall too far behind are removed; new ones will come."""
    limit = float(state.config["spawning"]["despawn_radius"])
    hero = state.hero
    state.enemies = [e for e in state.enemies
                     if e.is_boss(state.config)
                     or distance(e.x, e.y, hero.x, hero.y) <= limit]


def _leash_boss(state):
    """The boss is never removed: if it drifts too far it goes back on the ring."""
    spawn_cfg = state.config["spawning"]
    for enemy in state.enemies:
        if not enemy.is_boss(state.config):
            continue
        if distance(enemy.x, enemy.y, state.hero.x, state.hero.y) <= float(
                spawn_cfg["boss_leash_radius"]):
            continue
        angle = state.rng.uniform(0.0, 2.0 * math.pi)
        radius = float(spawn_cfg["circle_radius"])
        enemy.x = state.hero.x + math.cos(angle) * radius
        enemy.y = state.hero.y + math.sin(angle) * radius


def is_over(state):
    """True when the game has ended, by victory or by death."""
    return state.status in ("won", "dead")


def _contact_damage(state):
    hero = state.hero
    hero_radius = hero_value(state, "hit_radius")
    cooldown_ticks = ticks_for(hero_value(state, "touch_cooldown"))
    for enemy in state.enemies:
        enemy_cfg = state.config["enemies"][enemy.kind]
        if distance(enemy.x, enemy.y, hero.x, hero.y) > hero_radius + float(enemy_cfg["radius"]):
            continue
        if state.ticks - enemy.last_hit_tick < cooldown_ticks:
            continue
        enemy.last_hit_tick = state.ticks
        hero.hp -= float(enemy_cfg["damage"])
        event(state, "hurt", hero.x, hero.y, float(enemy_cfg["damage"]))
        if hero.hp <= 0.0:
            hero.hp = 0.0
            state.status = "dead"
            event(state, "end")
            return


def _damage_enemy(state, enemy, damage):
    """Take HP off one enemy and clean up if it dies."""
    event(state, "hit", enemy.x, enemy.y, damage)
    enemy.hp -= damage
    if enemy.hp <= 0.0:
        _kill_enemy(state, enemy)


def _fire_sparks(state):
    if weapon_level(state, "spark_wand") <= 0 or not state.enemies:
        return
    stats = spark_stats(state)
    target = nearest_enemy(state, state.hero.x, state.hero.y)
    aim = math.atan2(target.y - state.hero.y, target.x - state.hero.x)
    fan = math.radians(stats["fan"])
    for index in range(stats["count"]):
        angle = aim if stats["count"] == 1 else aim - fan / 2.0 + fan * index / (stats["count"] - 1)
        state.sparks.append(Spark(
            x=state.hero.x,
            y=state.hero.y,
            vx=math.cos(angle) * stats["speed"],
            vy=math.sin(angle) * stats["speed"],
            damage=stats["damage"],
            life=stats["life"],
            radius=stats["radius"],
        ))
    state.next_fire_tick = state.ticks + ticks_for(stats["interval"])


def _move_sparks(state):
    live = []
    for spark in state.sparks:
        spark.x += spark.vx * TICK
        spark.y += spark.vy * TICK
        spark.life -= TICK
        hit = None
        for enemy in state.enemies:
            radius = float(state.config["enemies"][enemy.kind]["radius"])
            if distance(spark.x, spark.y, enemy.x, enemy.y) <= radius + spark.radius:
                hit = enemy
                break
        if hit is not None:
            _damage_enemy(state, hit, spark.damage)
            continue
        if spark.life > 0.0:
            live.append(spark)
    state.sparks = live


def _spin_blades(state):
    if weapon_level(state, "spin_blades") <= 0:
        return
    stats = blade_stats(state)
    state.blade_angle += 2.0 * math.pi / stats["turn_ticks"]
    for index, (blade_x, blade_y) in enumerate(stats["positions"]):
        for enemy in list(state.enemies):
            radius = float(state.config["enemies"][enemy.kind]["radius"])
            if distance(blade_x, blade_y, enemy.x, enemy.y) > radius + stats["radius"]:
                continue
            last = enemy.blade_hits.get(index, -10 ** 9)
            if state.ticks - last < stats["cooldown_ticks"]:
                continue
            enemy.blade_hits[index] = state.ticks
            _damage_enemy(state, enemy, stats["damage"])


def _holy_ring(state):
    if weapon_level(state, "holy_ring") <= 0:
        return
    if state.ticks < state.next_ring_tick:
        return
    stats = ring_stats(state)
    state.next_ring_tick = state.ticks + stats["interval_ticks"]
    for enemy in list(state.enemies):
        radius = float(state.config["enemies"][enemy.kind]["radius"])
        if distance(enemy.x, enemy.y, state.hero.x, state.hero.y) <= stats["radius"] + radius:
            _damage_enemy(state, enemy, stats["damage"])


def _move_gems(state):
    hero = state.hero
    radius = magnet_radius(state)
    speed = float(state.config["level_up"]["gem_speed"])
    pickup = hero_value(state, "hit_radius")
    left = []
    for gem in state.gems:
        gap = distance(gem.x, gem.y, hero.x, hero.y)
        if gap <= pickup:
            event(state, "gem", gem.x, gem.y, gem.xp)
            _add_xp(state, gem.xp)
            continue
        if gap <= radius and gap > 0.0:
            ratio = min(1.0, speed * TICK / gap)
            gem.x += (hero.x - gem.x) * ratio
            gem.y += (hero.y - gem.y) * ratio
        left.append(gem)
    state.gems = left


def step(state):
    """Advance the game by exactly TICK seconds. Only runs while the game plays."""
    if state.status != "playing":
        return
    state.ticks += 1
    state.time += TICK

    if state.ticks >= ticks_for(state.config["victory_time"]):
        state.status = "won"  # you survived until the clock ran out
        event(state, "end")
        return

    _move_hero(state)

    if state.ticks >= state.next_spawn_tick:
        state.next_spawn_tick += ticks_for(state.config["spawning"]["interval"])
        row = spawn_row_for(state, state.time)
        if row is not None:
            _spawn_enemies(state, row)

    _move_enemies(state)
    _remove_far_enemies(state)
    _leash_boss(state)
    _contact_damage(state)
    if state.status != "playing":
        return

    if state.ticks >= state.next_fire_tick:
        _fire_sparks(state)
    _move_sparks(state)
    _spin_blades(state)
    _holy_ring(state)
    _move_gems(state)
