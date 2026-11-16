"""Code-drawn interface artwork: rounded surfaces, soft shadows, icons and check boxes.

Everything is rasterised here into small anti-aliased PNGs, so the app ships no
image files, fonts or downloads. Each image is flattened onto the color it will
sit on (`backdrop`): Tk draws opaque images quickly on every platform, while
translucent ones are slow to composite. Pixel data is cached per process; each
Tk interpreter only wraps the cached bytes in a PhotoImage.
"""
import base64
import math
import struct
import tkinter as tk
import zlib

_PNG_CACHE = {}


def rgb(color):
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def png(width, height, rgba):
    """Encode straight-alpha RGBA bytes as a PNG that Tk 8.6+ reads natively."""
    stride = width * 4
    raw = b''.join(b'\x00' + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def _over(pixel, color, alpha):
    """Composite a straight-alpha color over a straight-alpha pixel."""
    if alpha <= 0:
        return pixel
    r, g, b, a = pixel
    out = alpha + a * (1 - alpha)
    return ((color[0] * alpha + r * a * (1 - alpha)) / out,
            (color[1] * alpha + g * a * (1 - alpha)) / out,
            (color[2] * alpha + b * a * (1 - alpha)) / out, out)


def _pixel(pixel, backdrop):
    """Four output bytes; with a backdrop the pixel is composited onto it and made opaque."""
    r, g, b, a = pixel
    if backdrop is None:
        return bytes((round(r), round(g), round(b), round(a * 255)))
    return bytes((round(r * a + backdrop[0] * (1 - a)), round(g * a + backdrop[1] * (1 - a)),
                  round(b * a + backdrop[2] * (1 - a)), 255))


def _box_distance(x, y, left, top, right, bottom, radius):
    """Signed distance from a point to a rounded rectangle (negative inside)."""
    ax = abs(x - (left + right) / 2) - ((right - left) / 2 - radius)
    ay = abs(y - (top + bottom) / 2) - ((bottom - top) / 2 - radius)
    return min(max(ax, ay), 0) + math.hypot(max(ax, 0), max(ay, 0)) - radius


def rounded_png(width, height, radius, fill=None, border=None, border_width=1,
                margin=(0, 0, 0, 0), shadow=None, backdrop=None):
    """A rounded rectangle, optionally outlined and with a soft drop shadow.

    `margin` is transparent space left/top/right/bottom for the shadow to fall
    into. `shadow` is (color, strength, blur, offset_y). Large sizes are built
    by stretching a small computed core, so cost does not grow with the area.
    """
    key = ('rounded', width, height, radius, fill, border, border_width, margin, shadow, backdrop)
    if key in _PNG_CACHE:
        return _PNG_CACHE[key]
    edge = math.ceil(radius + max(margin) + border_width + 1)
    core_w, core_h = min(width, 2 * edge + 1), min(height, 2 * edge + 1)
    left, top = margin[0], margin[1]
    right, bottom = core_w - margin[2], core_h - margin[3]
    radius = min(radius, (right - left) / 2, (bottom - top) / 2)
    fill_rgb = rgb(fill) if fill else None
    border_rgb = rgb(border) if border else None
    behind = rgb(backdrop) if backdrop else None
    rows = []
    for y in range(core_h):
        row = bytearray()
        for x in range(core_w):
            px, py = x + 0.5, y + 0.5
            pixel = (0, 0, 0, 0)
            if shadow:
                color, strength, blur, offset = shadow
                distance = _box_distance(px, py - offset, left, top, right, bottom, radius)
                pixel = _over(pixel, rgb(color), strength * max(0.0, min(1.0, 1 - distance / blur)) ** 2)
            distance = _box_distance(px, py, left, top, right, bottom, radius)
            outer = max(0.0, min(1.0, 0.5 - distance))
            if border_rgb:
                pixel = _over(pixel, border_rgb, outer)
                inner = max(0.0, min(1.0, 0.5 - distance - border_width))
            else:
                inner = outer
            if fill_rgb:
                pixel = _over(pixel, fill_rgb, inner)
            elif border_rgb and inner > 0:
                # Outline only: clear the inside again.
                pixel = (pixel[0], pixel[1], pixel[2], pixel[3] * (1 - inner))
            row += _pixel(pixel, behind)
        rows.append(bytes(row))
    if core_w < width:
        middle = edge * 4
        rows = [row[:middle] + row[middle:middle + 4] * (width - core_w + 1) + row[middle + 4:] for row in rows]
    if core_h < height:
        rows = rows[:edge] + [rows[edge]] * (height - core_h + 1) + rows[edge + 1:]
    data = _PNG_CACHE[key] = png(width, height, b''.join(rows))
    return data


def _segment_distance(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    t = 0 if not length else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def drawing_png(size, layers, grid=24.0, corner=None, backdrop=None):
    """Rasterise stroked lines, rings and filled discs drawn on a `grid` unit square.

    Each layer is (kind, coordinates, color, stroke): kind is 'line' (x1, y1, x2, y2),
    'ring' (cx, cy, r) or 'disc' (cx, cy, r); stroke is in grid units.
    """
    key = ('drawing', size, tuple(layers), grid, corner, backdrop)
    if key in _PNG_CACHE:
        return _PNG_CACHE[key]
    samples = (1 / 6, 0.5, 5 / 6)
    scale = grid / size
    prepared = []
    for kind, points, color, stroke in layers:
        reach = stroke / 2 + scale
        if kind == 'line':
            box = (min(points[0], points[2]) - reach, min(points[1], points[3]) - reach,
                   max(points[0], points[2]) + reach, max(points[1], points[3]) + reach)
        else:
            box = (points[0] - points[2] - reach, points[1] - points[2] - reach,
                   points[0] + points[2] + reach, points[1] + points[2] + reach)
        prepared.append((kind, points, rgb(color), stroke / 2, box))
    behind = rgb(backdrop) if backdrop else None
    data = bytearray()
    for y in range(size):
        for x in range(size):
            pixel = (0, 0, 0, 0)
            cx, cy = (x + 0.5) * scale, (y + 0.5) * scale
            for kind, points, color, half, box in prepared:
                # Most pixels are far from most strokes; skip them cheaply.
                if not (box[0] <= cx <= box[2] and box[1] <= cy <= box[3]):
                    continue
                covered = 0
                for oy in samples:
                    for ox in samples:
                        gx, gy = (x + ox) * scale, (y + oy) * scale
                        if kind == 'line':
                            hit = _segment_distance(gx, gy, *points) <= half
                        else:
                            distance = math.hypot(gx - points[0], gy - points[1])
                            hit = distance <= points[2] if kind == 'disc' else abs(distance - points[2]) <= half
                        covered += hit
                pixel = _over(pixel, color, covered / 9)
            if corner is not None:
                # Clip the drawing to a rounded square of this corner radius.
                clip = max(0.0, min(1.0, 0.5 - _box_distance(x + 0.5, y + 0.5, 0, 0, size, size, corner)))
                pixel = (pixel[0], pixel[1], pixel[2], pixel[3] * clip)
            data += _pixel(pixel, behind)
    result = _PNG_CACHE[key] = png(size, size, data)
    return result


def _strokes(lines, color, stroke=1.9):
    return tuple(('line', line, color, stroke) for line in lines)


ICON_LINES = {
    # Arrow dropping into a tray: finished and running exports.
    'exports': ((12, 4, 12, 15), (7.5, 10.5, 12, 15), (16.5, 10.5, 12, 15),
                (4.5, 15, 4.5, 19.5), (4.5, 19.5, 19.5, 19.5), (19.5, 19.5, 19.5, 15)),
    'new': ((12, 5, 12, 19), (5, 12, 19, 12)),
    # Three sliders.
    'settings': ((4, 7, 20, 7), (4, 12, 20, 12), (4, 17, 20, 17)),
    'check': ((7, 12.5, 10.5, 16), (10.5, 16, 17, 8.5)),
}
ICON_DOTS = {'settings': ((9, 7, 2.6), (15.5, 12, 2.6), (8, 17, 2.6))}


def icon_png(name, size, color, backdrop):
    layers = _strokes(ICON_LINES[name], color)
    layers += tuple(('disc', dot, color, 0) for dot in ICON_DOTS.get(name, ()))
    return drawing_png(size, layers, backdrop=backdrop)


def stage_png(state, size, colors, backdrop):
    """Small status marks for the stage track: done, active, waiting, warning, problem."""
    if state == 'done':
        layers = (('disc', (12, 12, 10), colors['accent'], 0),) + _strokes(ICON_LINES['check'], colors['accent_text'], 2.4)
    elif state == 'active':
        layers = (('ring', (12, 12, 8.6), colors['accent'], 2.8), ('disc', (12, 12, 3.6), colors['accent'], 0))
    elif state in ('warning', 'problem'):
        tone = colors['warning' if state == 'warning' else 'negative']
        layers = (('disc', (12, 12, 10), tone, 0), ('line', (12, 6.5, 12, 13), colors['surface'], 2.6),
                  ('disc', (12, 17, 1.5), colors['surface'], 0))
    else:
        layers = (('ring', (12, 12, 8.6), colors['disabled'], 2.2),)
    return drawing_png(size, layers, backdrop=backdrop)


def empty_png(size, colors):
    """A package with an arrow leaving it, for the empty queue."""
    box, arrow = colors['muted'], colors['accent']
    layers = _strokes(((5, 9, 12, 5.5), (12, 5.5, 19, 9), (19, 9, 19, 12), (5, 9, 5, 17), (5, 17, 12, 20.5),
                       (12, 20.5, 14, 19.5), (5, 9, 12, 12.5), (12, 12.5, 19, 9), (12, 12.5, 12, 20.5)), box, 1.1)
    layers += _strokes(((14.5, 16, 21.5, 16), (18.8, 13.3, 21.5, 16), (18.8, 18.7, 21.5, 16)), arrow, 1.5)
    return drawing_png(size, layers, backdrop=colors['surface'])


def check_png(size, selected, colors, backdrop, disabled=False):
    corner = max(2, size * 0.24)
    if not selected:
        return rounded_png(size, size, corner, fill=colors['sunken'] if disabled else colors['field'],
                           border=colors['border' if disabled else 'muted'], border_width=1.2, backdrop=backdrop)
    fill = colors['disabled'] if disabled else colors['accent']
    layers = (('disc', (12, 12, 30), fill, 0),) + _strokes(ICON_LINES['check'], colors['accent_text'], 2.6)
    return drawing_png(size, layers, corner=corner, backdrop=backdrop)


class Assets:
    """PhotoImages for one Tk interpreter, updated in place when the theme changes."""

    def __init__(self, root):
        self.root = root
        self.images = {}

    def set(self, name, data):
        image = self.images.get(name)
        if image is None:
            image = self.images[name] = tk.PhotoImage(master=self.root, data=base64.b64encode(data))
        elif getattr(image, '_ova_data', None) is not data:
            image.configure(data=base64.b64encode(data))
        image._ova_data = data
        return image

    def get(self, name):
        return self.images[name]
