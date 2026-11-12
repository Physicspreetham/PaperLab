from pathlib import Path
import sys

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from raster_figures import crop_figure


def test_blank_margin_trim_preserves_colours_and_disconnected_labels():
    source=Image.new('RGB',(1000,300),'white');draw=ImageDraw.Draw(source)
    draw.rectangle((40,80,300,180),fill=(30,140,210))
    draw.rectangle((150,40,155,50),fill='black')  # detached T label
    result,info=crop_figure(source,[10,10,900,250],pixel_box=True)
    assert info['edge_warnings']==[]
    assert info['source_pixel_box']==[40,40,301,181]
    pad=info['white_padding_px']
    assert result.crop((pad,pad,result.width-pad,result.height-pad)).tobytes()==source.crop((40,40,301,181)).tobytes()
    assert result.width<300
    assert result.getpixel((0,0))==(255,255,255)


def test_canvas_padding_does_not_hide_clipped_source_ink():
    source=Image.new('RGB',(200,200),'white');ImageDraw.Draw(source).rectangle((50,50,150,150),fill='black')
    _,info=crop_figure(source,[60,60,140,140],pixel_box=True)
    assert set(info['edge_warnings'])=={'left','top','right','bottom'}


def test_reviewed_expansion_clears_source_edges():
    source=Image.new('RGB',(200,200),'white');ImageDraw.Draw(source).rectangle((50,50,150,150),fill='black')
    _,info=crop_figure(source,[40,40,160,160],pixel_box=True)
    assert info['edge_warnings']==[]


def test_blank_or_invalid_bounds_cannot_be_published():
    source=Image.new('RGB',(200,200),'white')
    with pytest.raises(ValueError,match='no visible'):crop_figure(source,[0,0,1000,1000])
    with pytest.raises(ValueError,match='bounds'):crop_figure(source,[0,0,201,200],pixel_box=True)
