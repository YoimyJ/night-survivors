"""Night Survivors - make the picture files in assets/ from the art in raw_art/.

Run this on your own computer:  python make_assets.py
main.py never imports Pillow, it only loads the finished files.

The 16 x 16 source pictures are enlarged 3 times with nearest-neighbour, so the
pixels stay hard squares and nothing is blurred.
"""

from pathlib import Path

from PIL import Image

SCALE = 3
SRC = Path("raw_art")
OUT = Path("assets")

# The two gem colours: blue is worth 1 XP, pink is worth 2 XP.
GEM_COLOURS = {"gem_blue": (70, 150, 255), "gem_pink": (255, 90, 200)}


def upscale(image, scale=SCALE):
    """Bigger copy with hard pixels (no smoothing)."""
    size = (image.width * scale, image.height * scale)
    return image.resize(size, Image.NEAREST)


def tint(image, colour):
    """Recolour a picture to one bright colour, keeping its shading and alpha."""
    source = image.convert("RGBA")
    result = Image.new("RGBA", source.size)
    src_pixels = source.load()
    dst_pixels = result.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, alpha = src_pixels[x, y]
            if alpha == 0:
                dst_pixels[x, y] = (0, 0, 0, 0)
                continue
            light = (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0
            # keep the dark outline, blow the bright parts up into a glow
            factor = 0.45 + 0.85 * light
            pixel = []
            for channel in range(3):
                value = colour[channel] * factor
                value += (255.0 - value) * 0.18 * light  # glassy highlight
                pixel.append(max(0, min(255, int(value))))
            dst_pixels[x, y] = (pixel[0], pixel[1], pixel[2], alpha)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    made = []
    for path in sorted(SRC.glob("*.png")):
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            upscale(rgba).save(OUT / path.name)
            made.append(path.name)

    with Image.open(SRC / "gem.png") as image:
        gem = image.convert("RGBA")
        for name, colour in GEM_COLOURS.items():
            upscale(tint(gem, colour)).save(OUT / (name + ".png"))
            made.append(name + ".png")

    print("wrote %d files to %s/: %s" % (len(made), OUT, ", ".join(made)))


if __name__ == "__main__":
    main()
