"""Lossless raster figure export shared by model previews and final publishing."""
import math
import numpy as np
from PIL import Image, ImageOps


def _border_pixels(rgb):
    return np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])


def background_colour(image):
    """Dominant page colour, read from the outer border of the full source."""
    rgb = np.asarray(image.convert('RGB'))
    return tuple(int(v) for v in np.median(_border_pixels(rgb), axis=0))


def background_is_dark(image):
    """True for black-board style pages (light writing on a dark canvas)."""
    return sum(background_colour(image)) / 3 < 96


def _drop_thin_rules(ink, rules, axis, coverage):
    """Remove only the pixels of thin page-spanning faint rules from ink.

    axis=0 -> horizontal rules (rows), axis=1 -> vertical rules (columns).
    """
    length = rules.shape[1] if axis == 0 else rules.shape[0]
    counts = rules.sum(axis=1 - axis)
    lines = [i for i in range(len(counts)) if counts[i] >= length * coverage]
    groups = []
    for i in lines:
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    for group in groups:
        if len(group) <= 3:
            for i in group:
                if axis == 0:
                    ink[i] &= ~rules[i]
                else:
                    ink[:, i] &= ~rules[:, i]


def content_ink(image):
    """Mark real figure/text ink, ignoring page furniture, keeping original pixels.

    Light pages: ignore only faint, thin page-spanning neutral rules (the EJEE
    question/answer column divider is a full-height vertical one; notebook rules
    are horizontal). Dark axes, colored arrows and short gray labels remain
    content. Detect on the full source so a short line in a tight figure cannot
    look page-wide.

    Dark pages (black-board solutions): anything clearly brighter than the
    dominant dark background is ink. Treating the black canvas itself as ink
    made every crop edge look cut, so those crops could never be accepted.
    """
    rgb = np.asarray(image.convert('RGB'))
    if background_is_dark(image):
        bg = np.median(_border_pixels(rgb), axis=0)
        ink = np.abs(rgb.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > 40
        return Image.fromarray((ink * 255).astype(np.uint8), 'L')
    rgb16 = rgb.astype(np.int16)
    low, high = rgb16.min(axis=2), rgb16.max(axis=2)
    lum = np.asarray(image.convert('L'))
    ink = lum < 245
    rules = ((high - low) <= 12) & (low >= 190) & (low < 245)
    _drop_thin_rules(ink, rules, 0, .8)
    _drop_thin_rules(ink, rules, 1, .7)
    return Image.fromarray((ink * 255).astype(np.uint8), 'L')


def reviewed_source(image, review):
    """Retain manually reviewed source rectangles on their original canvas.

    Used for diagrams whose dimension arrows extend underneath adjacent prose.
    No scaling, redrawing, or inferred pixels; source identity is checked by caller.
    """
    regions = review.get('source_keep_regions')
    if not regions:
        return image
    result = Image.new('RGB', image.size, background_colour(image))
    for box in regions:
        if len(box) != 4 or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Invalid reviewed source region')
        result.paste(image.crop(box).convert('RGB'), (box[0], box[1]))
    return result


def render_reviewed_crop(image, review):
    figure, info = crop_figure(reviewed_source(image, review), review['source_pixel_box'], pixel_box=True)
    if info['edge_warnings'] and info['edge_warnings'] == review.get('confirmed_edge_warnings'):
        info['confirmed_edge_warnings'] = info['edge_warnings']
    angle = review.get('rotation', 0)
    if angle:
        figure = figure.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True,
                               fillcolor=background_colour(image))
        info.update(size=list(figure.size), rotation=angle)
    return figure, info


def has_unconfirmed_edges(report):
    return bool(report['edge_warnings'] and report['edge_warnings'] != report.get('confirmed_edge_warnings'))


def crop_figure(image, box, *, pixel_box=False):
    """Trim only blank pixels, add display clearance, and report cut ink.

    Never erase disconnected marks: they may be dimension labels. Foreign text
    requires source/preview review, rather than an unsafe largest-component crop.
    """
    im=image.convert('RGB')
    if pixel_box:
        px=list(box)
    else:
        x,y,w,h=box
        px=[max(0,math.floor((x-1)*im.width/1000)),max(0,math.floor((y-1)*im.height/1000)),
            min(im.width,math.ceil((x+w+1)*im.width/1000)),min(im.height,math.ceil((y+h+1)*im.height/1000))]
    if len(px)!=4 or not (0<=px[0]<px[2]<=im.width and 0<=px[1]<px[3]<=im.height):
        raise ValueError('Invalid source-pixel figure bounds')
    region=im.crop(px)
    ink=content_ink(im).crop(px)
    bounds=ink.getbbox()
    if not bounds:raise ValueError('Figure crop contains no visible content')
    left,top,right,bottom=bounds
    touching=[]
    for edge,cut in [('left',left<2),('top',top<2),('right',right>region.width-2),('bottom',bottom>region.height-2)]:
        if cut:touching.append(edge)
    content_box=[px[0]+left,px[1]+top,px[0]+right,px[1]+bottom]
    content=im.crop(content_box)
    padding=max(8,min(32,math.ceil(max(content.size)*.015)))
    output=ImageOps.expand(content,border=padding,fill=background_colour(im))
    return output,{'requested_source_pixel_box':px,'source_pixel_box':content_box,
                   'white_padding_px':padding,'edge_warnings':touching,'size':list(output.size),
                   'method':'lossless source pixels; blank margins trimmed; white display clearance added'}


def clear_crop_edges(image, box):
    """Expand cut edges to the nearest blank strip, within 10% of the page.

    Never shrink a requested diagram or manufacture pixels. If nearby content
    cannot be separated, leave that edge for visual review.
    """
    width, height = image.size
    x, y, w, h = box
    px = [max(0, math.floor((x-1)*width/1000)), max(0, math.floor((y-1)*height/1000)),
          min(width, math.ceil((x+w+1)*width/1000)), min(height, math.ceil((y+h+1)*height/1000))]
    if not (0 <= px[0] < px[2] <= width and 0 <= px[1] < px[3] <= height):
        raise ValueError('Invalid source-pixel figure bounds')
    mask = content_ink(image)
    original = px.copy()
    edges = [(0, -1, width), (2, 1, width), (1, -1, height), (3, 1, height)]
    # Vertical expansion can expose ink on an already checked horizontal edge.
    for _ in range(2):
        for edge, direction, limit in edges:
            start = px[edge]
            remaining = max(4, math.ceil(limit * .10)) - abs(start - original[edge])
            for step in range(remaining + 1):
                candidate = start + direction * step
                if edge in (0, 2):
                    strip = (candidate, px[1], candidate+2, px[3]) if edge == 0 else (candidate-2, px[1], candidate, px[3])
                else:
                    strip = (px[0], candidate, px[2], candidate+2) if edge == 1 else (px[0], candidate-2, px[2], candidate)
                if min(strip) < 0 or strip[2] > width or strip[3] > height:
                    break
                if mask.crop(strip).getbbox() is None:
                    px[edge] = candidate
                    break
    return [px[0]*1000/width, px[1]*1000/height,
            (px[2]-px[0])*1000/width, (px[3]-px[1])*1000/height]


def nearby_clear_cuts(image, review):
    """Suggest blank cuts on either side of a flagged edge for visual review."""
    width, height = image.size
    left, top, right, bottom = review['requested_source_pixel_box']
    mask = content_ink(image)
    edges = {
        'left': (left, width, mask.crop((0, top, width, bottom)).getprojection()[0]),
        'right': (right, width, mask.crop((0, top, width, bottom)).getprojection()[0]),
        'top': (top, height, mask.crop((left, 0, right, height)).getprojection()[1]),
        'bottom': (bottom, height, mask.crop((left, 0, right, height)).getprojection()[1]),
    }
    cuts = {}
    for edge in review['edge_warnings']:
        start, size, projection = edges[edge]
        radius = math.ceil(size * .30)
        candidates = []
        for direction in (-1, 1):
            for distance in range(1, radius + 1):
                pos = start + direction * distance
                if pos < 3 or pos > size - 3:
                    break
                if not any(projection[pos-3:pos+3]):
                    candidates.append(round(pos * 1000 / size))
                    break
        if candidates:
            cuts[edge] = candidates
    return cuts


def ink_components(image, *, grid=600, reach=.012):
    """Group ink into blobs by proximity (letters->words->paragraphs, strokes->diagram).

    Works on a coarse grid so it stays fast on 2400px pages. Returns
    [{'box': [l,t,r,b] in source px, 'ink': ink-cell count}] with tight boxes.
    """
    from PIL import ImageFilter
    mask = np.asarray(content_ink(image)) > 0
    height, width = mask.shape
    block = max(1, round(max(width, height) / grid))
    rows, cols = -(-height // block), -(-width // block)
    padded = np.zeros((rows * block, cols * block), bool)
    padded[:height, :width] = mask
    cells = padded.reshape(rows, block, cols, block).any(axis=(1, 3))
    radius = max(1, round(reach * width / block))
    dilated = np.asarray(Image.fromarray((cells * 255).astype(np.uint8)).filter(
        ImageFilter.MaxFilter(2 * radius + 1))) > 0
    labels = np.zeros(cells.shape, np.int32)
    count = 0
    for start in zip(*np.nonzero(dilated)):
        if labels[start]:
            continue
        count += 1
        labels[start] = count
        stack = [start]
        while stack:
            y, x = stack.pop()
            for ny in range(max(0, y - 1), min(rows, y + 2)):
                for nx in range(max(0, x - 1), min(cols, x + 2)):
                    if dilated[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = count
                        stack.append((ny, nx))
    result = []
    for label in range(1, count + 1):
        member = (labels == label) & cells
        if not member.any():
            continue
        ys, xs = np.nonzero(member)
        l, t, r, b = xs.min() * block, ys.min() * block, min(width, (xs.max() + 1) * block), min(height, (ys.max() + 1) * block)
        tight = mask[t:b, l:r]
        ty, tx = np.nonzero(tight)
        result.append({'box': [l + int(tx.min()), t + int(ty.min()), l + int(tx.max()) + 1, t + int(ty.max()) + 1],
                       'ink': int(member.sum())})
    return result


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def snap_to_ink_blobs(image, box_px, components=None):
    """Refine an approximate model box to whole ink blobs; None if that is unsafe.

    Blobs mostly inside the box belong to the figure. A blob only partly inside
    is a clipped part of the diagram when it is about figure-sized, and foreign
    prose (a paragraph the box merely brushes) when it is much larger. Refusing
    when foreign prose overlaps the result keeps this from swallowing text.
    """
    blobs = components if components is not None else ink_components(image)
    box_area = max(1, _area(box_px))
    keep, foreign = [], []
    for blob in blobs:
        inter = _overlap(blob['box'], box_px)
        if not inter:
            continue
        area = max(1, _area(blob['box']))
        inside = inter / area
        if inside >= .6 or (inside >= .25 and area <= 2.2 * box_area and inter >= .12 * box_area):
            keep.append(blob['box'])
        elif inter / box_area >= .002:
            foreign.append(blob['box'])
    if not keep:
        return None
    merged = [min(b[0] for b in keep), min(b[1] for b in keep), max(b[2] for b in keep), max(b[3] for b in keep)]
    if any(_overlap(f, merged) for f in foreign):
        return None
    # Blobs are separated by more than the grouping reach, so a small blank margin
    # keeps the exported rectangle off the ink without touching a neighbour.
    margin = max(6, round(.004 * image.width))
    return [max(0, merged[0] - margin), max(0, merged[1] - margin),
            min(image.width, merged[2] + margin), min(image.height, merged[3] + margin)]


def snap_within_reach(snapped, rough, slack=.2):
    """True when snapping stayed near the model's box (<= slack of its size per side).

    Ink blobs can bridge a diagram and neighbouring text (e.g. an options row), so an
    unbounded snap silently swallows the text and every retry returns the same box.
    """
    dx = slack * (rough[2] - rough[0]); dy = slack * (rough[3] - rough[1])
    return (snapped[0] >= rough[0] - dx and snapped[1] >= rough[1] - dy
            and snapped[2] <= rough[2] + dx and snapped[3] <= rough[3] + dy)


def figure_candidates(image, limit=6):
    """Diagram-like ink blobs as normalized [x, y, width, height] (0-1000), largest first."""
    width, height = image.size
    page = width * height
    blobs = [b for b in ink_components(image) if _area(b['box']) >= .004 * page]
    blobs.sort(key=lambda b: -_area(b['box']))
    return [[round(b['box'][0] * 1000 / width), round(b['box'][1] * 1000 / height),
             round((b['box'][2] - b['box'][0]) * 1000 / width), round((b['box'][3] - b['box'][1]) * 1000 / height)]
            for b in blobs[:limit]]
