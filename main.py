"""Night Survivors - window, drawing, sound and input.

The rules live in rules.py. This file only turns the game state into pixels
and sends the player's mouse or finger to the rules.
"""

import asyncio
import math
import os
import random

import pygame

import rules

TICK_MS = 1000.0 / 60.0
ASSET_DIR = "assets"  # finished pictures made by make_assets.py
SOUND_DIR = "sounds"  # finished sounds made by make_sounds.py


def fmt_time(seconds):
    whole = int(seconds)
    return "%d:%02d" % (whole // 60, whole % 60)


class Audio:
    """Loads the finished files from sounds/ and plays them.

    Sound is a nice-to-have: when the machine has no audio the game still
    plays, it is only quiet.
    """

    def __init__(self, config):
        self.sounds = {}
        self.next_play = {}
        self.gaps = {"hit": float(config["sounds"]["hit_gap"])}
        try:
            pygame.mixer.init()
        except pygame.error as problem:
            print("sound is off: %s" % problem)
            return
        wanted = config["sounds"]["files"]
        volume = float(config["sounds"]["volume"])
        for name, file_name in wanted.items():
            path = SOUND_DIR + "/" + file_name
            if not os.path.exists(path):
                raise SystemExit("Missing sound %s - run: python make_sounds.py" % path)
            try:
                sound = pygame.mixer.Sound(path)
            except pygame.error as problem:
                # a browser may not be able to decode this file: the game plays without it
                print("no sound for %s: %s" % (name, problem))
                continue
            sound.set_volume(volume)
            self.sounds[name] = sound

    def play(self, name):
        """Play one short sound. `hit` happens often, so it cannot repeat at once."""
        sound = self.sounds.get(name)
        if sound is None:
            return
        now = pygame.time.get_ticks() / 1000.0
        if now < self.next_play.get(name, 0.0):
            return
        self.next_play[name] = now + self.gaps.get(name, 0.0)
        sound.play()


class Effects:
    """The feel of a hit: damage numbers, a flash when an enemy dies, a shake when the hero is hurt.

    None of this changes the game: it only lives for a few frames on the screen.
    """

    def __init__(self, config):
        feel = config["feel"]
        self.number_seconds = float(feel["number_seconds"])
        self.number_rise = float(feel["number_rise_px"])
        self.number_max = int(feel["number_max"])
        self.flash_seconds = float(feel["flash_seconds"])
        self.flash_px = float(feel["flash_px"])
        self.shake_seconds = float(feel["shake_seconds"])
        self.shake_px = float(feel["shake_px"])
        self.numbers = []  # [world x, world y, text, seconds left]
        self.flashes = []  # [world x, world y, size px, seconds left]
        self.shake_left = 0.0
        self.shake_x = 0.0
        self.shake_y = 0.0

    def add(self, name, x, y, amount):
        """Take one note left by the rules."""
        if name == "hit":
            self.numbers.append([x, y, "%d" % int(round(amount)), self.number_seconds])
            if len(self.numbers) > self.number_max:
                del self.numbers[0]
        elif name == "enemy_died":
            self.flashes.append([x, y, amount * 2.0 + self.flash_px, self.flash_seconds])
        elif name == "hurt":
            self.shake_left = self.shake_seconds

    def update(self, seconds):
        """Let everything get a bit older and pick the next shake step."""
        for live in (self.numbers, self.flashes):
            keep = []
            for item in live:
                item[3] -= seconds
                if item[3] > 0.0:
                    keep.append(item)
            live[:] = keep
        if self.shake_left > 0.0:
            self.shake_left = max(0.0, self.shake_left - seconds)
            fraction = self.shake_left / self.shake_seconds
            self.shake_x = random.uniform(-1.0, 1.0) * self.shake_px * fraction
            self.shake_y = random.uniform(-1.0, 1.0) * self.shake_px * fraction
        else:
            self.shake_x = self.shake_y = 0.0

    def reset(self):
        self.numbers = []
        self.flashes = []
        self.shake_left = self.shake_x = self.shake_y = 0.0


class View:
    """Everything that draws: window, fonts, camera."""

    def __init__(self, config):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption("Night Survivors")
        self.width = int(config["window"]["width"])
        self.height = int(config["window"]["height"])
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.font = pygame.font.Font(None, 26)
        self.small_font = pygame.font.Font(None, 20)
        self.big_font = pygame.font.Font(None, 54)
        self.tile = float(config["floor_tile_px"])
        self.victory_time = float(config["victory_time"])
        self.colors = {name: tuple(rgb) for name, rgb in config["colors"].items()}
        self.hero_picture = self.load_picture(config["hero"]["picture"],
                                              config["hero"]["picture_px"])
        self.floor_picture = self.load_picture(config["floor_picture"],
                                               config["floor_tile_px"])
        self.enemy_pictures = {}
        for kind, enemy in config["enemies"].items():
            self.enemy_pictures[kind] = self.load_picture(enemy["picture"],
                                                          enemy["picture_px"])
        level_up = config["level_up"]
        self.gem_pictures = {int(xp): self.load_picture(name, level_up["gem_picture_px"])
                             for xp, name in level_up["gem_pictures"].items()}
        self.default_gem = self.gem_pictures[min(self.gem_pictures)]
        blades = config["weapons"]["spin_blades"]
        self.blade_picture = self.load_picture(blades["picture"], blades["picture_px"])

    def load_picture(self, name, px):
        """Load one finished picture from assets/ and size it for the screen."""
        path = ASSET_DIR + "/" + name
        if not os.path.exists(path):
            raise SystemExit("Missing picture %s - run: python make_assets.py" % path)
        picture = pygame.image.load(path).convert_alpha()
        px = int(round(px))
        return pygame.transform.scale(picture, (px, px))

    def draw_picture(self, picture, x, y):
        """Put one picture in the middle of this screen point."""
        self.screen.blit(picture, (int(x - picture.get_width() / 2),
                                   int(y - picture.get_height() / 2)))

    def camera(self, state):
        """Top-left corner of the visible world."""
        return (state.hero.x - self.width / 2.0, state.hero.y - self.height / 2.0)

    def draw_floor(self, cam_x, cam_y):
        """The same tile, repeated forever: the map has no edges."""
        tile = self.tile
        floor = self.floor_picture
        first_x = int(math.floor(cam_x / tile))
        first_y = int(math.floor(cam_y / tile))
        for row in range(int(self.height / tile) + 2):
            for col in range(int(self.width / tile) + 2):
                gx = (first_x + col) * tile - cam_x
                gy = (first_y + row) * tile - cam_y
                self.screen.blit(floor, (int(gx), int(gy)))

    def draw_bar(self, rect, fraction, back, front):
        pygame.draw.rect(self.screen, back, rect)
        filled = pygame.Rect(rect.x, rect.y, int(rect.width * max(0.0, min(1.0, fraction))),
                             rect.height)
        pygame.draw.rect(self.screen, front, filled)
        pygame.draw.rect(self.screen, self.colors["text"], rect, 1)

    def loadout_parts(self, state):
        """For example ['Spark 2', 'Blades 1', 'Boots 1']."""
        config = state.config
        parts = []
        for item_id, item in config["weapons"].items():
            level = state.weapons.get(item_id, 0)
            if level:
                parts.append("%s %d" % (item["short"], level))
        for item_id, item in config["passives"].items():
            level = state.passives.get(item_id, 0)
            if level:
                parts.append("%s %d" % (item["short"], level))
        return parts

    def wrap_parts(self, parts, width):
        """Join labels into lines that fit the screen."""
        lines, line = [], ""
        for part in parts:
            trial = line + "  " + part if line else part
            if line and self.small_font.size(trial)[0] > width:
                lines.append(line)
                line = part
            else:
                line = trial
        if line:
            lines.append(line)
        return lines

    def draw_hud(self, state):
        hero = state.hero
        self.draw_bar(pygame.Rect(12, 12, 150, 14), hero.hp / hero.max_hp,
                      self.colors["hp_back"], self.colors["hp"])
        needed = rules.xp_needed(state)
        self.draw_bar(pygame.Rect(12, 30, 150, 10), state.xp / needed,
                      self.colors["xp_back"], self.colors["xp"])
        level = self.font.render("Lv %d" % state.level, True, self.colors["text"])
        self.screen.blit(level, (170, 12))

        right = "%s / %s" % (fmt_time(state.time), fmt_time(self.victory_time))
        self.screen.blit(self.font.render(right, True, self.colors["text"]),
                         (self.width - self.font.size(right)[0] - 12, 12))

        parts = self.loadout_parts(state) + ["Kills %d" % state.kills]
        lines = self.wrap_parts(parts, self.width - 24)
        top = self.height - 18 - 16 * (len(lines) - 1)
        for index, line in enumerate(lines):
            self.screen.blit(self.small_font.render(line, True, self.colors["text"]),
                             (12, top + index * 16))

    def draw_effects(self, effects, cam_x, cam_y):
        """The death flashes and the floating damage numbers, on top of the world."""
        for x, y, size, left in effects.flashes:
            at = 1.0 - left / effects.flash_seconds
            radius = int(size / 2.0 + effects.flash_px * at)
            pygame.draw.circle(self.screen, self.colors["flash"],
                               (int(x - cam_x), int(y - cam_y)), radius, 2)
        for x, y, text, left in effects.numbers:
            at = 1.0 - left / effects.number_seconds
            image = self.small_font.render(text, True, self.colors["number"])
            image.set_alpha(int(255.0 * (1.0 - at)))
            self.screen.blit(image, (int(x - cam_x - image.get_width() / 2.0),
                                     int(y - cam_y - 10.0 - effects.number_rise * at)))

    def draw_game(self, state, effects):
        cam_x, cam_y = self.camera(state)
        cam_x += effects.shake_x  # the whole world jolts when the hero is hurt
        cam_y += effects.shake_y
        self.draw_floor(cam_x, cam_y)

        for gem in state.gems:
            picture = self.gem_pictures.get(int(gem.xp), self.default_gem)
            self.draw_picture(picture, gem.x - cam_x, gem.y - cam_y)

        if rules.weapon_level(state, "holy_ring") > 0:
            stats = rules.ring_stats(state)
            pygame.draw.circle(self.screen, self.colors["ring"],
                               (int(state.hero.x - cam_x), int(state.hero.y - cam_y)),
                               int(stats["radius"]), 3)

        for enemy in state.enemies:
            self.draw_picture(self.enemy_pictures[enemy.kind],
                              enemy.x - cam_x, enemy.y - cam_y)

        for spark in state.sparks:
            pygame.draw.circle(self.screen, self.colors["spark"],
                               (int(spark.x - cam_x), int(spark.y - cam_y)), int(spark.radius))

        self.draw_picture(self.hero_picture, state.hero.x - cam_x, state.hero.y - cam_y)

        if rules.weapon_level(state, "spin_blades") > 0:
            for blade_x, blade_y in rules.blade_stats(state)["positions"]:
                self.draw_picture(self.blade_picture, blade_x - cam_x, blade_y - cam_y)

        self.draw_effects(effects, cam_x, cam_y)
        self.draw_hud(state)

    def card_rects(self, count):
        """Where the level-up cards are drawn, so a tap can be matched to one."""
        height, gap = 110, 18
        top = int(self.height / 2 - (count * height + (count - 1) * gap) / 2)
        return [pygame.Rect(20, top + index * (height + gap), self.width - 40, height)
                for index in range(count)]

    def card_at(self, state, pos):
        if state.status != "levelup":
            return None
        for index, rect in enumerate(self.card_rects(len(state.choices))):
            if rect.collidepoint(pos):
                return index
        return None

    def draw_level_up(self, state):
        cover = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        cover.fill(self.colors["overlay"] + (180,))
        self.screen.blit(cover, (0, 0))
        title = "LEVEL UP - choose one"
        self.screen.blit(self.font.render(title, True, self.colors["text"]),
                         ((self.width - self.font.size(title)[0]) // 2,
                          self.card_rects(3)[0].top - 40))
        for rect, chosen in zip(self.card_rects(len(state.choices)), state.choices):
            pygame.draw.rect(self.screen, self.colors["card"], rect, border_radius=10)
            pygame.draw.rect(self.screen, self.colors["card_edge"], rect, 2, border_radius=10)
            name = chosen["name"]
            if chosen["kind"] == "heal":
                name += "  (+%d HP)" % int(state.config["level_up"]["heal_hp"])
            else:
                name += "  Lv %d" % chosen["level"]
            self.screen.blit(self.font.render(name, True, self.colors["text"]),
                             (rect.x + 18, rect.y + 22))
            self.screen.blit(self.font.render(chosen["text"], True, self.colors["text"]),
                             (rect.x + 18, rect.y + 58))

    def draw_end(self, state):
        cover = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        cover.fill(self.colors["overlay"] + (200,))
        self.screen.blit(cover, (0, 0))
        title = "VICTORY" if state.status == "won" else "GAME OVER"
        lines = [title,
                 "Time %s   Kills %d   Lv %d" % (fmt_time(state.time), state.kills, state.level),
                 "Click or tap to play again"]
        y = self.height // 2 - 60
        for index, text in enumerate(lines):
            font = self.big_font if index == 0 else self.font
            image = font.render(text, True, self.colors["text"])
            self.screen.blit(image, ((self.width - image.get_width()) // 2, y))
            y += 44

    def draw_paused(self):
        image = self.font.render("PAUSED - press P", True, self.colors["text"])
        self.screen.blit(image, ((self.width - image.get_width()) // 2, self.height // 2))


async def main(smoke=False):
    """One async frame loop: fixed rules, drawing once per frame."""
    config = rules.load_config()
    view = View(config)
    audio = Audio(config)
    effects = Effects(config)
    state = rules.new_game(config)

    clock = pygame.time.Clock()
    accumulator = 0.0
    running = True
    paused = False
    mouse_pos = (0, 0)
    mouse_seen = False
    finger_pos = None
    frames = 0

    def take_every_card():
        """Accept a card if the game is frozen on the level-up screen."""
        while state.status == "levelup":
            rules.choose(state, 0)

    def start_again():
        """A clean game, with nothing left on the screen from the last one."""
        nonlocal state
        state = rules.new_game(config)
        effects.reset()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                paused = not paused
            elif event.type == pygame.MOUSEMOTION:
                mouse_pos = event.pos
                mouse_seen = True
                finger_pos = None
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pos = event.pos
                mouse_seen = True
                finger_pos = None
                index = view.card_at(state, event.pos)
                if index is not None:
                    rules.choose(state, index)
                elif rules.is_over(state):
                    start_again()
            elif event.type == pygame.FINGERMOTION:
                finger_pos = (event.x * view.width, event.y * view.height)
            elif event.type == pygame.FINGERDOWN:
                finger_pos = (event.x * view.width, event.y * view.height)
                index = view.card_at(state, finger_pos)
                if index is not None:
                    rules.choose(state, index)
                elif rules.is_over(state):
                    start_again()
            elif event.type == pygame.FINGERUP:
                finger_pos = None

        if smoke:
            # Drive the input code once from the test run, no real mouse needed.
            frames += 1
            if frames == 3:
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEMOTION, {"pos": (300, 200), "rel": (0, 0), "buttons": (0, 0, 0)}))
            if frames == 10:
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERDOWN, {"finger_id": 0, "x": 0.8, "y": 0.3, "dx": 0.0, "dy": 0.0}))
            if frames == 30:
                pygame.event.post(pygame.event.Event(
                    pygame.FINGERUP, {"finger_id": 0, "x": 0.8, "y": 0.3, "dx": 0.0, "dy": 0.0}))
            if frames == 100:
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_p}))
            if frames == 120:
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_p}))
            if frames == 140:
                # six gems inside the magnet radius: they fly in and give 6 XP
                for index in range(6):
                    state.gems.append(rules.Gem(state.hero.x + 40 + index,
                                                state.hero.y + 20, 1))
            if frames == 170:
                print("smoke: after the gems status=%s level=%d xp=%.0f choices=%s"
                      % (state.status, state.level, state.xp,
                         [c["name"] for c in state.choices]))
                pygame.image.save(view.screen, "smoke_cards.png")
            if frames == 180:
                rect = view.card_rects(len(state.choices))[1]
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN,
                    {"pos": rect.center, "button": 1}))
            if frames == 200:
                print("smoke: after the card status=%s level=%d xp=%.0f weapons=%s passives=%s"
                      % (state.status, state.level, state.xp, state.weapons, state.passives))
                state.weapons.update({"spin_blades": 4, "holy_ring": 2})
                state.passives.update({"swift_boots": 2, "big_heart": 1, "magnet": 1})
                state.xp = 0.0
                # park the gems out of magnet reach so they stay on screen
                for index, gem in enumerate(state.gems):
                    gem.x = state.hero.x + 140.0 + index * 26.0
                    gem.y = state.hero.y + 150.0
            if frames == 240:
                pygame.image.save(view.screen, "smoke_growth.png")
                print("smoke: growth shot, blades=%d ring=%d gems=%d enemies=%d"
                      % (len(rules.blade_stats(state)["positions"]),
                         rules.weapon_level(state, "holy_ring"), len(state.gems),
                         len(state.enemies)))
            if frames == 250:
                take_every_card()
                # the whole roster on screen at once, boss included
                hero = state.hero
                tanky = 1e9  # keep them alive long enough to be drawn
                state.enemies.append(rules.Enemy("slime", hero.x + 90.0, hero.y - 60.0, hp=tanky))
                state.enemies.append(rules.Enemy("ghost", hero.x - 80.0, hero.y - 90.0, hp=tanky))
                boss = rules.Enemy("demon", hero.x + 40.0, hero.y + 110.0, hp=tanky)
                state.enemies.append(boss)
            if frames == 262:
                take_every_card()
                pygame.image.save(view.screen, "smoke_waves.png")
                kinds = sorted({enemy.kind for enemy in state.enemies})
                print("smoke: waves shot, kinds=%s boss alive=%d"
                      % (kinds, sum(1 for e in state.enemies
                                    if e.is_boss(state.config))))
                # push the boss right out of the world and let the rules pull it back
                boss.x = state.hero.x + 800.0
                boss.y = state.hero.y
            if frames == 266:
                take_every_card()
                # a bat that stays on the hero and cannot die: the screen should shake
                state.enemies.append(
                    rules.Enemy("bat", state.hero.x + 2.0, state.hero.y, hp=1e9))
            if frames == 269:
                take_every_card()
                print("smoke: boss after being thrown far: distance=%.0f (ring %.0f, leash %.0f)"
                      % (rules.distance(boss.x, boss.y, state.hero.x, state.hero.y),
                         state.config["spawning"]["circle_radius"],
                         state.config["spawning"]["boss_leash_radius"]))
            if frames == 283:
                # one bat placed and killed on purpose, so there is a death flash to see
                weak = rules.Enemy("bat", state.hero.x + 120.0, state.hero.y, hp=1.0)
                state.enemies.append(weak)
                state.sparks.append(rules.Spark(weak.x, weak.y, 0.0, 0.0, 8.0, 1.0))
            if frames == 284:
                # a fresh touch, so the shake is at its strongest below
                state.enemies.append(
                    rules.Enemy("bat", state.hero.x - 3.0, state.hero.y, hp=1e9))
            if frames == 285:
                take_every_card()
                pygame.image.save(view.screen, "smoke_feel.png")
                print("smoke: feel shot, kills=%d numbers=%d flashes=%d shake=%.2fs "
                      "camera jolt=(%.1f, %.1f)"
                      % (state.kills, len(effects.numbers), len(effects.flashes),
                         effects.shake_left, effects.shake_x, effects.shake_y))
            if frames == 290:
                take_every_card()
                state.hero.hp = 1.0
            if frames == 310:
                print("smoke: after the hit status=%s hp=%.0f" % (state.status, state.hero.hp))
                pygame.image.save(view.screen, "smoke_end.png")
            if frames == 320:
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": (100, 100), "button": 1}))
            if frames == 340:
                # jump the clock to the last tick so the victory path runs
                state.ticks = rules.ticks_for(state.config["victory_time"]) - 1
                state.time = float(state.config["victory_time"]) - rules.TICK
            if frames == 360:
                print("smoke: after the clock status=%s time=%.2f" % (state.status, state.time))
                pygame.image.save(view.screen, "smoke_win.png")
            if frames == 370:
                pygame.event.post(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": (100, 100), "button": 1}))
            if frames >= 400:
                print("smoke: time=%.2fs hero=(%.0f, %.0f) hp=%.0f enemies=%d gems=%d "
                      "kills=%d level=%d status=%s paused=%s"
                      % (state.time, state.hero.x, state.hero.y, state.hero.hp,
                         len(state.enemies), len(state.gems), state.kills, state.level,
                         state.status, paused))
                print("smoke: sounds loaded: %s" % (sorted(audio.sounds) or "none"))
                running = False
        else:
            mouse_pos = pygame.mouse.get_pos()

        # The pointer is read every frame, so the hero keeps walking even when
        # the mouse does not move at all.
        pointer = finger_pos
        if pointer is None and mouse_seen:
            pointer = mouse_pos
        if pointer is not None and not paused and state.status == "playing":
            cam_x, cam_y = view.camera(state)
            rules.set_target(state, pointer[0] + cam_x, pointer[1] + cam_y, True)

        frame = clock.tick(int(TICK_MS)) / 1000.0
        if not paused and state.status == "playing":
            accumulator += frame
            if accumulator > 0.25:
                accumulator = 0.25  # a long stop should not spawn a burst of steps
            while accumulator >= rules.TICK:
                accumulator -= rules.TICK
                rules.step(state)

        # The rules leave notes about what just happened; the sounds and the
        # short pictures are the answer to those notes.
        notes = state.events[:]
        del state.events[:]
        for name, x, y, amount in notes:
            effects.add(name, x, y, amount)
            audio.play(name)
        effects.update(frame)

        view.draw_game(state, effects)
        if state.status == "levelup":
            view.draw_level_up(state)
        elif rules.is_over(state):
            view.draw_end(state)
        elif paused:
            view.draw_paused()
        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


if __name__ == "__main__":
    # NS_SMOKE=1 runs a short headless self-check with fake mouse and finger events.
    asyncio.run(main(smoke=os.environ.get("NS_SMOKE") == "1"))
