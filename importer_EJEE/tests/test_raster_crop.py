import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raster_crop import pixel_box


def test_exact_box_does_not_regrow_toward_neighbour():
    assert pixel_box((2000, 3000), 622, 14, 360, 260) == [1244, 42, 1964, 822]
    assert pixel_box((2000, 3000), 622, 14, 360, 250) == [1244, 42, 1964, 792]


def test_crop_is_source_pixel_identical():
    image = Image.new("RGB", (2000, 3000), "white")
    image.putpixel((1300, 100), (40, 80, 120))
    image.putpixel((1300, 810), (0, 0, 0))
    wide = image.crop(pixel_box(image.size, 622, 14, 360, 260))
    small = image.crop(pixel_box(image.size, 622, 14, 360, 250))
    assert wide.getpixel((56, 58)) == (40, 80, 120)
    assert small.getpixel((56, 58)) == (40, 80, 120)
    assert wide.height == 780 and small.height == 750


@pytest.mark.parametrize("args", [
    (-1, 0, 10, 10), (0, 0, 0, 10), (999, 0, 2, 1),
    (0, 999, 1, 2), (0, 0, 1.5, 2), (True, 0, 1, 2),
])
def test_unsafe_boxes_are_rejected(args):
    with pytest.raises(ValueError):
        pixel_box((100, 100), *args)
