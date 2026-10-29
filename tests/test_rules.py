"""Tests for the game rules in rules.py (no drawing, no pygame)."""

import copy
import random
import unittest

import rules

CONFIG = rules.load_config()


def fresh(**changes):
    """A new game with a fixed random seed, with the hero kept safe."""
    config = copy.deepcopy(CONFIG)
    config["hero"].update(changes)
    state = rules.new_game(config, rng=random.Random(7))
    state.hero.hp = 1e9  # tests about spawning should not die
    return state


def deep_change(config, changes):
    """Return a copy of config with hero values replaced."""
    new = copy.deepcopy(config)
    new["hero"].update(changes)
    return new


def run(state, seconds):
    for _ in range(int(round(seconds / rules.TICK))):
        rules.step(state)


def no_new_waves(state):
    """Stop the spawner so a test only sees the enemies it placed itself."""
    state.config["spawn_rows"] = []


def bats_stay_put(state):
    """Give the bats zero speed so a test can hold them at a fixed distance."""
    state.config["enemies"]["bat"]["speed"] = 0.0


def fast_forward(state, moment):
    """Set the clock to this time and let the very next tick do the spawning."""
    state.time = moment
    state.next_spawn_tick = state.ticks + 1


def count_bosses(state):
    return sum(1 for enemy in state.enemies if enemy.is_boss(state.config))


class TestSpawning(unittest.TestCase):
    def test_no_enemies_before_the_first_second(self):
        state = fresh()
        run(state, 0.9)
        self.assertEqual(state.enemies, [])

    def test_first_second_brings_eight_bats(self):
        state = fresh()
        run(state, 1.0)
        self.assertEqual(len(state.enemies), CONFIG["spawning"]["max_per_second"])

    def test_keeps_spawning_until_the_minimum_is_reached(self):
        state = fresh()
        minimum = CONFIG["spawn_rows"][0]["min_alive"]
        self.assertGreater(minimum, CONFIG["spawning"]["max_per_second"])
        run(state, 2.0)  # 8 in the first second, then the rest
        self.assertEqual(len(state.enemies), minimum)

    def test_the_minimum_grows_after_15_seconds(self):
        state = fresh()
        state.weapons = {}  # keep the bats alive
        run(state, 16.0)
        self.assertEqual(len(state.enemies), CONFIG["spawn_rows"][1]["min_alive"])

    def test_never_more_than_eight_per_second(self):
        state = fresh()
        # pretend a huge minimum so one second tries to spawn as many as it can
        state.config["spawn_rows"][0]["min_alive"] = 100
        run(state, 1.0)
        self.assertEqual(len(state.enemies), CONFIG["spawning"]["max_per_second"])

    def test_spawn_on_the_ring_around_the_hero(self):
        state = fresh()
        run(state, 1.0)
        one_step = float(CONFIG["enemies"]["bat"]["speed"]) * rules.TICK
        for enemy in state.enemies:
            gap = rules.distance(enemy.x, enemy.y, state.hero.x, state.hero.y)
            ring = float(CONFIG["spawning"]["circle_radius"])
            self.assertLessEqual(gap, ring + 1e-6)
            self.assertGreaterEqual(gap, ring - one_step)

    def test_never_more_than_the_limit_alive(self):
        state = fresh()
        state.weapons = {}
        for row in state.config["spawn_rows"]:
            row["min_alive"] = 500
        run(state, 30.0)
        self.assertEqual(len(state.enemies), CONFIG["spawning"]["max_alive"])

    def test_far_enemies_are_removed(self):
        state = fresh()
        no_new_waves(state)
        run(state, 1.0)
        self.assertEqual(state.enemies, [])
        state.enemies.append(rules.Enemy("bat", 750.0, 0.0, hp=8.0))
        run(state, rules.TICK)
        self.assertEqual(state.enemies, [])


class TestMovement(unittest.TestCase):
    def test_hero_walks_to_the_target(self):
        state = fresh()
        rules.set_target(state, 60.0, 0.0)
        run(state, 1.0)
        self.assertGreater(state.hero.x, 0.0)
        self.assertLessEqual(state.hero.x, CONFIG["hero"]["speed"])

    def test_hero_walks_even_when_the_pointer_stops_moving(self):
        state = fresh()
        rules.set_target(state, 300.0, 0.0)
        run(state, rules.TICK)
        start = state.hero.x
        run(state, 0.5)
        self.assertGreater(state.hero.x, start)

    def test_hero_stops_close_to_the_pointer(self):
        state = fresh()
        stop = CONFIG["hero"]["follow_min_px"]
        rules.set_target(state, stop - 2, 0.0)
        run(state, 1.0)
        self.assertAlmostEqual(state.hero.x, 0.0, places=6)

    def test_enemies_chase_the_hero(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}  # a live wand would kill the bat we are watching
        state.enemies.append(rules.Enemy("bat", 200.0, 0.0, hp=8.0))
        run(state, 1.0)
        self.assertLess(state.enemies[0].x, 200.0)


class TestDamage(unittest.TestCase):
    def test_touch_hurts_once_per_cooldown(self):
        state = fresh()
        hero_cfg = CONFIG["hero"]
        state.hero.hp = 100.0
        enemy = rules.Enemy("bat", hero_cfg["hit_radius"], 0.0, hp=8.0)
        state.enemies.append(enemy)
        run(state, rules.TICK)
        self.assertEqual(state.hero.hp, 100.0 - CONFIG["enemies"]["bat"]["damage"])
        # the bat cannot hurt again until the cooldown has passed
        run(state, hero_cfg["touch_cooldown"] - 2 * rules.TICK)
        self.assertEqual(state.hero.hp, 100.0 - CONFIG["enemies"]["bat"]["damage"])

    def test_hero_dies_and_the_game_stops(self):
        state = fresh()
        state.hero.hp = 1.0
        state.enemies.append(rules.Enemy("bat", CONFIG["hero"]["hit_radius"], 0.0, hp=8.0))
        run(state, rules.TICK)
        self.assertEqual(state.status, "dead")
        self.assertEqual(state.hero.hp, 0.0)
        count = len(state.enemies)
        run(state, 2.0)
        self.assertEqual(len(state.enemies), count)  # frozen after death

    def test_low_hp_shows_as_zero(self):
        state = fresh()
        state.hero.hp = 1.0
        state.enemies.append(rules.Enemy("bat", CONFIG["hero"]["hit_radius"], 0.0, hp=8.0))
        run(state, rules.TICK)
        self.assertEqual(state.hero.hp, 0.0)


class TestSparkWand(unittest.TestCase):
    def test_wand_shoots_at_the_nearest_enemy(self):
        state = fresh()
        state.enemies.append(rules.Enemy("bat", 100.0, 0.0, hp=8.0))
        state.enemies.append(rules.Enemy("bat", 0.0, 300.0, hp=8.0))
        run(state, rules.TICK)
        self.assertEqual(len(state.sparks), CONFIG["weapons"]["spark_wand"]["count"])
        self.assertGreater(state.sparks[0].vx, 0.0)

    def test_spark_kills_a_bat_and_counts_the_kill(self):
        state = fresh()
        wand = CONFIG["weapons"]["spark_wand"]
        self.assertGreaterEqual(wand["damage"], CONFIG["enemies"]["bat"]["hp"])
        state.enemies.append(rules.Enemy("bat", 40.0, 0.0, hp=CONFIG["enemies"]["bat"]["hp"]))
        for _ in range(int(1.0 / rules.TICK)):
            rules.step(state)
            if state.kills:
                break
        self.assertEqual(state.kills, 1)
        self.assertEqual(len(state.enemies), 0)

    def test_wand_fires_on_its_interval(self):
        state = fresh()
        no_new_waves(state)
        # a bat that stays out of reach, so only the firing is measured
        tank = rules.Enemy("bat", 690.0, 0.0, hp=1e9)
        state.enemies.append(tank)
        interval_ticks = rules.ticks_for(CONFIG["weapons"]["spark_wand"]["interval"])
        fired_on = []
        planned = state.next_fire_tick
        for _ in range(int(2.0 / rules.TICK)):
            rules.step(state)
            if state.next_fire_tick != planned:
                planned = state.next_fire_tick
                fired_on.append(state.ticks)
        self.assertEqual(fired_on, [1, 1 + interval_ticks, 1 + 2 * interval_ticks])
        self.assertEqual(tank.hp, 1e9)

    def test_spark_dies_after_its_life(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        wand = CONFIG["weapons"]["spark_wand"]
        state.sparks.append(rules.Spark(0.0, 0.0, wand["speed"], 0.0, wand["damage"], wand["life"]))
        run(state, wand["life"] + 0.1)
        self.assertEqual(state.sparks, [])


def quiet():
    """A still game: nothing spawns, nothing shoots, the hero cannot die."""
    state = fresh()
    no_new_waves(state)
    state.weapons = {}
    return state


def offer(state, kind, item_id, level):
    """Put one card in front of the hero and let her take it."""
    state.status = "levelup"
    state.choices = [rules.card("Test", level, "", kind, item_id)]
    rules.choose(state, 0)


class TestGems(unittest.TestCase):
    def test_a_dead_enemy_drops_a_gem(self):
        state = quiet()
        state.weapons = {"spark_wand": 1}
        state.enemies.append(rules.Enemy("bat", 40.0, 0.0, hp=8.0))
        for _ in range(int(1.0 / rules.TICK)):
            rules.step(state)
            if state.gems:
                break
        self.assertEqual(state.kills, 1)
        self.assertEqual(len(state.gems), 1)
        self.assertEqual(state.gems[0].xp, CONFIG["enemies"]["bat"]["xp"])
        self.assertGreater(state.gems[0].x, 0.0)  # it drops where the bat died
        self.assertLessEqual(state.gems[0].x, 40.0)

    def test_a_gem_outside_the_magnet_stays_where_it_is(self):
        state = quiet()
        far = rules.magnet_radius(state) + 100
        state.gems.append(rules.Gem(far, 0.0, 1))
        run(state, 1.0)
        self.assertAlmostEqual(state.gems[0].x, far, places=6)

    def test_a_gem_inside_the_magnet_flies_to_the_hero(self):
        state = quiet()
        state.gems.append(rules.Gem(50.0, 0.0, 1))
        run(state, rules.TICK)
        expected = 50.0 - float(CONFIG["level_up"]["gem_speed"]) * rules.TICK
        self.assertAlmostEqual(state.gems[0].x, expected, places=6)

    def test_picking_a_gem_up_adds_xp(self):
        state = quiet()
        state.gems.append(rules.Gem(5.0, 0.0, 2))
        run(state, rules.TICK)
        self.assertEqual(state.gems, [])
        self.assertEqual(state.xp, 2)

    def test_the_magnet_item_widens_the_magnet(self):
        state = quiet()
        offer(state, "passive", "magnet", 1)
        self.assertEqual(rules.magnet_radius(state),
                         CONFIG["hero"]["magnet_radius"]
                         + CONFIG["passives"]["magnet"]["radius"])


class TestXpAndLevelUp(unittest.TestCase):
    def test_xp_curve_is_five_then_three_more_each_level(self):
        state = quiet()
        self.assertEqual(rules.xp_needed(state), CONFIG["level_up"]["first_xp"])
        state.level = 4
        self.assertEqual(rules.xp_needed(state),
                         CONFIG["level_up"]["first_xp"] + 3 * CONFIG["level_up"]["xp_per_level"])

    def test_enough_xp_pauses_the_game_with_three_cards(self):
        state = quiet()
        for index in range(int(CONFIG["level_up"]["first_xp"])):
            state.gems.append(rules.Gem(5.0 + index * 0.1, 0.0, 1))
        run(state, rules.TICK)
        self.assertEqual(state.status, "levelup")
        self.assertEqual(len(state.choices), CONFIG["level_up"]["cards"])

    def test_the_game_is_frozen_while_the_cards_are_shown(self):
        state = quiet()
        state.enemies.append(rules.Enemy("bat", 500.0, 0.0, hp=8.0))
        offer(state, "weapon", "spin_blades", 1)
        state.status = "levelup"
        before = (state.time, state.enemies[0].x, state.ticks)
        run(state, 1.0)
        self.assertEqual((state.time, state.enemies[0].x, state.ticks), before)

    def test_taking_a_weapon_card_levels_it_and_resumes(self):
        state = quiet()
        state.xp = rules.xp_needed(state)
        offer(state, "weapon", "spark_wand", 2)
        self.assertEqual(state.weapons["spark_wand"], 2)
        self.assertEqual(state.status, "playing")
        self.assertEqual(state.level, 2)
        self.assertEqual(state.xp, 0.0)

    def test_enough_xp_for_two_levels_offers_cards_again(self):
        state = quiet()
        state.xp = 20.0
        offer(state, "weapon", "holy_ring", 1)
        self.assertEqual(state.level, 2)
        self.assertEqual(state.status, "levelup")
        self.assertEqual(len(state.choices), CONFIG["level_up"]["cards"])

    def test_a_bad_card_number_does_nothing(self):
        state = quiet()
        state.status = "levelup"
        state.choices = []
        rules.choose(state, 3)
        self.assertEqual(state.status, "levelup")
        self.assertEqual(state.level, 1)


class TestCardsOffered(unittest.TestCase):
    def test_nothing_at_level_five_is_offered(self):
        state = quiet()
        state.weapons["spark_wand"] = CONFIG["weapons"]["spark_wand"]["levels"]
        state.passives["magnet"] = CONFIG["passives"]["magnet"]["levels"]
        ids = [chosen["id"] for chosen in rules.possible_cards(state)]
        self.assertNotIn("spark_wand", ids)
        self.assertNotIn("magnet", ids)

    def test_a_fourth_weapon_is_never_offered(self):
        state = quiet()
        state.weapons = {"spark_wand": 1, "spin_blades": 1, "holy_ring": 1}
        for chosen in rules.possible_cards(state):
            if chosen["kind"] == "weapon":
                self.assertGreater(chosen["level"], 1)

    def test_heal_is_offered_when_nothing_is_left(self):
        state = quiet()
        state.weapons = {key: CONFIG["weapons"][key]["levels"] for key in CONFIG["weapons"]}
        state.passives = {key: CONFIG["passives"][key]["levels"]
                          for key in CONFIG["passives"]}
        rules.offer_choices(state)
        state.status = "levelup"
        self.assertEqual([chosen["kind"] for chosen in state.choices], ["heal"] * 3)
        state.hero.hp = 50.0
        rules.choose(state, 0)
        self.assertEqual(state.hero.hp, 50.0 + CONFIG["level_up"]["heal_hp"])

    def test_heal_does_not_go_over_the_max(self):
        state = quiet()
        state.hero.hp = state.hero.max_hp
        offer(state, "heal", "heal", 0)
        self.assertEqual(state.hero.hp, state.hero.max_hp)


class TestPassiveItems(unittest.TestCase):
    def test_swift_boots_add_walk_speed(self):
        state = quiet()
        offer(state, "passive", "swift_boots", 1)
        percent = CONFIG["passives"]["swift_boots"]["speed_percent"]
        self.assertAlmostEqual(rules.walk_speed(state),
                               CONFIG["hero"]["speed"] * (1 + percent / 100.0))
        rules.set_target(state, 1000.0, 0.0)
        run(state, 1.0)
        self.assertAlmostEqual(state.hero.x, CONFIG["hero"]["speed"] * 1.1, places=1)

    def test_big_heart_adds_max_hp_and_heals(self):
        state = quiet()
        state.hero.hp = 10.0
        offer(state, "passive", "big_heart", 1)
        heart = CONFIG["passives"]["big_heart"]
        self.assertEqual(state.hero.max_hp, CONFIG["hero"]["max_hp"] + heart["max_hp"])
        self.assertEqual(state.hero.hp, 10.0 + heart["heal"])


class TestSpinBlades(unittest.TestCase):
    def test_blade_count_grows_at_levels_two_and_four(self):
        state = quiet()
        blades = CONFIG["weapons"]["spin_blades"]
        state.weapons["spin_blades"] = 1
        self.assertEqual(rules.blade_stats(state)["count"], blades["count"])
        state.weapons["spin_blades"] = 2
        self.assertEqual(rules.blade_stats(state)["count"], blades["count"] + 1)
        state.weapons["spin_blades"] = 4
        self.assertEqual(rules.blade_stats(state)["count"], blades["count"] + 2)

    def test_a_blade_hits_an_enemy_it_passes(self):
        state = quiet()
        bats_stay_put(state)
        state.config["weapons"]["spin_blades"]["turn_seconds"] = 1000.0  # hold them still
        state.weapons["spin_blades"] = 1
        enemy = rules.Enemy("bat", 60.0, 0.0, hp=1e9)
        state.enemies.append(enemy)
        run(state, 1.5)
        hits = (1e9 - enemy.hp) / CONFIG["weapons"]["spin_blades"]["damage"]
        self.assertGreaterEqual(hits, 1)

    def test_one_blade_hits_the_same_enemy_only_every_half_second(self):
        state = quiet()
        bats_stay_put(state)
        blades = CONFIG["weapons"]["spin_blades"]
        state.config["weapons"]["spin_blades"]["turn_seconds"] = 1000.0
        state.weapons["spin_blades"] = 1
        enemy = rules.Enemy("bat", 60.0, 0.0, hp=1e9)
        state.enemies.append(enemy)
        ticks = int(1.5 / rules.TICK)
        run(state, 1.5)  # hits at tick 1, 31, 61
        expected_hits = 1 + (ticks - 1) // rules.ticks_for(blades["hit_cooldown"])
        damage = 1e9 - enemy.hp
        self.assertAlmostEqual(damage, expected_hits * blades["damage"], places=6)

    def test_blades_reach_only_to_the_orbit_radius(self):
        state = quiet()
        bats_stay_put(state)
        state.weapons["spin_blades"] = 1
        near = rules.Enemy("bat", 60.0, 0.0, hp=1e9)
        far = rules.Enemy("bat", 200.0, 0.0, hp=1e9)
        state.enemies.extend([near, far])
        run(state, 3.0)
        self.assertLess(near.hp, 1e9)
        self.assertEqual(far.hp, 1e9)


class TestHolyRing(unittest.TestCase):
    def test_the_ring_hurts_everything_inside_it(self):
        state = quiet()
        ring = CONFIG["weapons"]["holy_ring"]
        bats_stay_put(state)  # keep them at a fixed distance
        state.weapons["holy_ring"] = 1
        inside = rules.Enemy("bat", 30.0, 0.0, hp=1e9)
        also_inside = rules.Enemy("bat", 0.0, 20.0, hp=1e9)
        outside = rules.Enemy("bat", 300.0, 0.0, hp=1e9)
        state.enemies.extend([inside, also_inside, outside])
        run(state, 1.0)  # two pulses in one second
        pulses = int(1.0 // ring["interval"])
        for enemy in (inside, also_inside):
            self.assertAlmostEqual(enemy.hp, 1e9 - pulses * ring["damage"], places=6)
        self.assertEqual(outside.hp, 1e9)

    def test_the_ring_grows_with_levels(self):
        state = quiet()
        ring = CONFIG["weapons"]["holy_ring"]
        state.weapons["holy_ring"] = 3
        self.assertEqual(rules.ring_stats(state)["radius"],
                         ring["radius"] + 2 * ring["radius_per_level"])
        self.assertEqual(rules.ring_stats(state)["damage"],
                         ring["damage"] + 2 * ring["damage_per_level"])


class TestWaveTable(unittest.TestCase):
    def test_the_rows_in_the_file_are_the_rows_of_the_design(self):
        rows = {(row["from"], tuple(row["types"]), row["min_alive"])
                for row in CONFIG["spawn_rows"]}
        self.assertEqual(rows, {
            (0.0, ("bat",), 12),
            (15.0, ("bat",), 20),
            (30.0, ("bat", "slime"), 28),
            (45.0, ("slime", "ghost"), 36),
            (60.0, ("bat", "ghost"), 45),
            (75.0, ("bat", "slime", "ghost"), 55),
            (90.0, ("bat", "slime"), 55),
            (105.0, ("bat",), 75),
        })

    def test_the_row_that_counts_is_the_one_for_this_moment(self):
        state = fresh()
        for moment, types in [(0.0, {"bat"}),
                              (14.9, {"bat"}),
                              (30.0, {"bat", "slime"}),
                              (45.0, {"slime", "ghost"}),
                              (75.0, {"bat", "slime", "ghost"}),
                              (105.0, {"bat"})]:
            row = rules.spawn_row_for(state, moment)
            self.assertEqual(set(row["types"]), types, "at %.1f s" % moment)

    def test_a_new_kind_really_enters_the_game(self):
        state = fresh()
        state.weapons = {}
        no_new_waves(state)
        state.config["spawn_rows"] = [{"from": 0.0, "types": ["slime"], "min_alive": 8}]
        state.next_spawn_tick = 1
        run(state, 1.0)
        self.assertEqual({e.kind for e in state.enemies}, {"slime"})
        self.assertEqual(state.enemies[0].hp, CONFIG["enemies"]["slime"]["hp"])


class TestEnemyNumbers(unittest.TestCase):
    def test_the_ghost_is_faster_than_the_hero(self):
        self.assertGreater(CONFIG["enemies"]["ghost"]["speed"], CONFIG["hero"]["speed"])

    def test_each_enemy_walks_at_its_own_speed(self):
        for kind in ("bat", "slime", "ghost", "demon"):
            state = fresh()
            no_new_waves(state)
            state.weapons = {}
            enemy = rules.Enemy(kind, state.hero.x - 200.0, state.hero.y,
                                 hp=CONFIG["enemies"][kind]["hp"])
            state.enemies.append(enemy)
            run(state, 0.5)
            gap = rules.distance(enemy.x, enemy.y, state.hero.x, state.hero.y)
            self.assertAlmostEqual(gap, 200.0 - CONFIG["enemies"][kind]["speed"] * 0.5, places=1)

    def test_each_enemy_hurts_for_its_own_damage(self):
        for kind in ("bat", "slime", "ghost", "demon"):
            state = fresh()
            no_new_waves(state)
            state.weapons = {}
            state.hero.hp = 1000.0
            state.enemies.append(rules.Enemy(kind, state.hero.x, state.hero.y,
                                             hp=CONFIG["enemies"][kind]["hp"]))
            run(state, rules.TICK)
            self.assertAlmostEqual(state.hero.hp,
                                   1000.0 - CONFIG["enemies"][kind]["damage"], places=6)


class TestBoss(unittest.TestCase):
    def test_the_boss_appears_once_and_not_twice(self):
        state = fresh()
        state.weapons = {}
        fast_forward(state, 90.0)
        run(state, 1.0)
        self.assertEqual(count_bosses(state), 1)
        self.assertTrue(state.boss_spawned)
        fast_forward(state, 100.0)
        run(state, 1.0)
        self.assertEqual(count_bosses(state), 1)

    def test_no_boss_before_1m30(self):
        state = fresh()
        state.weapons = {}
        fast_forward(state, 89.0)
        run(state, 1.0)
        self.assertEqual(count_bosses(state), 0)
        self.assertFalse(state.boss_spawned)

    def test_the_boss_is_never_removed_but_a_normal_enemy_is(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        limit = CONFIG["spawning"]["despawn_radius"]
        state.enemies.append(rules.Enemy("demon", state.hero.x + limit + 50.0,
                                         state.hero.y, hp=800.0))
        state.enemies.append(rules.Enemy("bat", state.hero.x - limit - 50.0,
                                         state.hero.y, hp=8.0))
        run(state, 0.1)
        self.assertEqual({e.kind for e in state.enemies}, {"demon"})

    def test_a_boss_too_far_away_is_put_back_on_the_circle(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        leash = CONFIG["spawning"]["boss_leash_radius"]
        boss = rules.Enemy("demon", state.hero.x + leash + 40.0, state.hero.y, hp=800.0)
        state.enemies.append(boss)
        run(state, rules.TICK)
        gap = rules.distance(boss.x, boss.y, state.hero.x, state.hero.y)
        self.assertAlmostEqual(gap, CONFIG["spawning"]["circle_radius"], places=6)

    def test_the_boss_drops_no_gem_but_a_slime_does(self):
        for kind, expected_xp in (("demon", None), ("slime", 2)):
            state = fresh()
            no_new_waves(state)
            state.weapons = {}
            enemy = rules.Enemy(kind, 300.0, 0.0, hp=CONFIG["enemies"][kind]["hp"])
            state.enemies.append(enemy)
            # one big spark placed right on the enemy kills it on the next step
            state.sparks.append(rules.Spark(300.0, 0.0, 0.0, 0.0, 100000.0, 1.0))
            run(state, rules.TICK)
            self.assertEqual(state.kills, 1)
            self.assertEqual(len(state.gems), 0 if expected_xp is None else 1)
            if expected_xp is not None:
                self.assertEqual(state.gems[0].xp, expected_xp)


class TestVictory(unittest.TestCase):
    def test_the_clock_in_the_file_is_two_minutes(self):
        self.assertEqual(CONFIG["victory_time"], 120.0)

    def test_the_game_is_still_playing_before_the_clock_runs_out(self):
        config = copy.deepcopy(CONFIG)
        config["victory_time"] = 10.0
        state = rules.new_game(config, rng=random.Random(4))
        no_new_waves(state)
        run(state, 9.0)
        self.assertEqual(state.status, "playing")

    def test_surviving_to_the_end_wins(self):
        config = copy.deepcopy(CONFIG)
        config["victory_time"] = 0.5
        state = rules.new_game(config, rng=random.Random(5))
        no_new_waves(state)
        run(state, 0.5)
        self.assertEqual(state.status, "won")
        self.assertTrue(rules.is_over(state))

    def test_winning_stops_the_rules(self):
        config = copy.deepcopy(CONFIG)
        config["victory_time"] = 0.5
        state = rules.new_game(config, rng=random.Random(6))
        no_new_waves(state)
        run(state, 0.5)
        enemies = len(state.enemies)
        run(state, 1.0)
        self.assertEqual(len(state.enemies), enemies)

    def test_dying_first_is_not_a_win(self):
        config = copy.deepcopy(CONFIG)
        config["victory_time"] = 0.5
        state = rules.new_game(config, rng=random.Random(8))
        no_new_waves(state)
        state.hero.hp = 1.0
        state.enemies.append(rules.Enemy("bat", state.hero.x, state.hero.y, hp=8.0))
        run(state, 0.5)
        self.assertEqual(state.status, "dead")


class TestEvents(unittest.TestCase):
    """The rules leave notes about what just happened so the screen can answer."""

    def names(self, state):
        return [note[0] for note in state.events]

    def test_a_fresh_game_has_no_notes_yet(self):
        state = fresh()
        self.assertEqual(state.events, [])

    def test_a_hit_and_the_death_it_causes(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        state.enemies.append(rules.Enemy("bat", 300.0, 0.0, hp=8.0))
        # one strong spark sitting on the bat: it hits and kills on the next step
        state.sparks.append(rules.Spark(300.0, 0.0, 0.0, 0.0, 10.0, 1.0))
        run(state, rules.TICK)
        self.assertEqual(self.names(state), ["hit", "enemy_died"])
        self.assertAlmostEqual(state.events[0][3], 10.0, places=6)
        self.assertAlmostEqual(state.events[1][3], CONFIG["enemies"]["bat"]["radius"],
                               places=6)

    def test_a_gem_picked_up(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        state.gems.append(rules.Gem(state.hero.x, state.hero.y, 2))
        run(state, rules.TICK)
        self.assertEqual(self.names(state), ["gem"])
        self.assertAlmostEqual(state.events[0][3], 2.0, places=6)

    def test_a_level_up(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        for index in range(5):
            state.gems.append(rules.Gem(state.hero.x + index, state.hero.y, 1))
        run(state, rules.TICK)
        self.assertEqual(self.names(state)[-1], "levelup")
        self.assertEqual(state.status, "levelup")

    def test_getting_hurt(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        state.hero.hp = 100.0
        state.enemies.append(rules.Enemy("slime", state.hero.x, state.hero.y, hp=30.0))
        run(state, rules.TICK)
        self.assertEqual(self.names(state), ["hurt"])
        self.assertAlmostEqual(state.events[0][3], CONFIG["enemies"]["slime"]["damage"],
                               places=6)

    def test_the_end_of_the_game(self):
        config = copy.deepcopy(CONFIG)
        config["victory_time"] = 0.5
        state = rules.new_game(config, rng=random.Random(9))
        no_new_waves(state)
        run(state, 0.5)
        self.assertEqual(self.names(state), ["end"])

    def test_dying_is_an_end_too(self):
        state = fresh()
        no_new_waves(state)
        state.weapons = {}
        state.hero.hp = 1.0
        state.enemies.append(rules.Enemy("bat", state.hero.x, state.hero.y, hp=8.0))
        run(state, rules.TICK)
        self.assertEqual(state.status, "dead")
        self.assertIn("end", self.names(state))


class TestNumbersComeFromTheFile(unittest.TestCase):
    def test_changing_a_number_in_the_file_changes_the_game(self):
        config = deep_change(CONFIG, {"speed": 40.0})
        state = rules.new_game(config, rng=random.Random(1))
        rules.set_target(state, 500.0, 0.0)
        run(state, 1.0)
        self.assertAlmostEqual(state.hero.x, 40.0, places=1)

    def test_hero_starts_with_full_hp_and_the_starting_wand(self):
        state = rules.new_game(copy.deepcopy(CONFIG), rng=random.Random(2))
        self.assertEqual(state.hero.hp, CONFIG["hero"]["max_hp"])
        self.assertEqual(state.weapons, {"spark_wand": 1})
        self.assertEqual(state.status, "playing")
        self.assertEqual(state.time, 0.0)

    def test_restart_makes_a_clean_game(self):
        state = fresh()
        state.hero.hp = 0.0
        state.status = "dead"
        state.enemies.append(rules.Enemy("bat", 1.0, 1.0, hp=8.0))
        state.gems.append(rules.Gem(2.0, 2.0, 1))
        state.passives["magnet"] = 2
        state.choices = [rules.card("Heal", 0, "", "heal", "heal")]
        again = rules.new_game(state.config, rng=random.Random(3))
        self.assertEqual(again.status, "playing")
        self.assertEqual(again.enemies, [])
        self.assertEqual(again.gems, [])
        self.assertEqual(again.passives, {})
        self.assertEqual(again.choices, [])
        self.assertEqual(again.hero.hp, again.hero.max_hp)


if __name__ == "__main__":
    unittest.main()
