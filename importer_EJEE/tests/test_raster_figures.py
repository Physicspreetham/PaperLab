from pathlib import Path
import sys

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from raster_figures import crop_figure
from raster_figures import clear_crop_edges
from raster_figures import reviewed_source


def test_reviewed_regions_preserve_source_pixels_and_exclude_adjacent_prose():
    source = Image.new('RGB', (100, 100), 'white')
    draw = ImageDraw.Draw(source)
    draw.rectangle((5, 5, 20, 20), fill='black')  # adjacent prose
    draw.rectangle((50, 10, 80, 60), fill='blue')
    draw.line((10, 80, 80, 80), fill='red')  # extended dimension
    review = {'source_keep_regions': [[40, 0, 100, 70], [0, 70, 100, 100]]}
    result = reviewed_source(source, review)
    assert result.getpixel((10, 10)) == (255, 255, 255)
    assert result.crop((40, 0, 100, 70)).tobytes() == source.crop((40, 0, 100, 70)).tobytes()
    assert result.crop((0, 70, 100, 100)).tobytes() == source.crop((0, 70, 100, 100)).tobytes()
    assert source.getpixel((10, 10)) == (0, 0, 0)
    with pytest.raises(ValueError, match='Invalid reviewed'):
        reviewed_source(source, {'source_keep_regions': [[0, 0, 101, 100]]})


def test_source_crop_expands_to_nearby_clear_pixels_without_shrinking_labels():
    source = Image.new('RGB', (1000, 500), 'white')
    ImageDraw.Draw(source).rectangle((200, 100, 500, 300), outline='blue', width=3)
    box = clear_crop_edges(source, [205, 190, 300, 430])
    _, info = crop_figure(source, box)
    assert info['edge_warnings'] == []
    assert info['source_pixel_box'] == [200, 100, 501, 301]


def test_source_crop_does_not_expand_across_large_unseparated_content():
    source = Image.new('RGB', (1000, 500), 'white')
    draw = ImageDraw.Draw(source)
    for y in range(20, 480, 6):  # dense prose block with no blank gap inside
        draw.line((20, y, 979, y), fill='black', width=6)
    box = clear_crop_edges(source, [200, 200, 300, 300])
    _, info = crop_figure(source, box)
    assert set(info['edge_warnings']) == {'left', 'right', 'top', 'bottom'}
    assert info['requested_source_pixel_box'][2] - info['requested_source_pixel_box'][0] < 310


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


def test_auto_crop_can_reach_blank_gap_beyond_three_percent():
    from importer_EJEE.raster_figures import clear_crop_edges

    source = Image.new('RGB', (200, 200), 'white')
    ImageDraw.Draw(source).rectangle((50, 50, 150, 150), fill='black')
    box = clear_crop_edges(source, [200, 200, 600, 500])
    _, info = crop_figure(source, box)
    assert info['edge_warnings'] == []
    assert info['source_pixel_box'] == [50, 50, 151, 151]


def test_clear_cut_suggestions_include_gap_above_choices():
    from importer_EJEE.raster_figures import nearby_clear_cuts

    source = Image.new('RGB', (200, 200), 'white')
    draw = ImageDraw.Draw(source)
    draw.rectangle((60, 20, 140, 99), outline='black')
    draw.rectangle((60, 120, 140, 160), fill='black')
    _, review = crop_figure(source, [50, 10, 150, 141], pixel_box=True)
    assert review['edge_warnings'] == ['bottom']
    before, after = nearby_clear_cuts(source, review)['bottom']
    assert 100 <= before * 200 / 1000 < 120
    assert after * 200 / 1000 > 160


def test_blank_or_invalid_bounds_cannot_be_published():
    source=Image.new('RGB',(200,200),'white')
    with pytest.raises(ValueError,match='no visible'):crop_figure(source,[0,0,1000,1000])
    with pytest.raises(ValueError,match='bounds'):crop_figure(source,[0,0,201,200],pixel_box=True)


def test_faint_notebook_rules_do_not_flag_edges_or_erase_source_pixels():
    source = Image.new('RGB', (200, 150), 'white')
    draw = ImageDraw.Draw(source)
    draw.line((0, 70, 199, 70), fill=(205, 205, 205))
    draw.rectangle((60, 40, 130, 110), outline='blue', width=3)
    result, info = crop_figure(source, [40, 30, 150, 120], pixel_box=True)
    assert info['edge_warnings'] == []
    pad = info['white_padding_px']
    assert result.crop((pad, pad, result.width-pad, result.height-pad)).tobytes() == source.crop(info['source_pixel_box']).tobytes()


@pytest.mark.parametrize('colour', ['black', 'blue', (205, 205, 205)])
def test_real_axes_and_short_gray_labels_still_flag_clipping(colour):
    source = Image.new('RGB', (200, 150), 'white')
    ImageDraw.Draw(source).line((50, 70, 120, 70), fill=colour)
    _, info = crop_figure(source, [60, 30, 150, 120], pixel_box=True)
    assert 'left' in info['edge_warnings']


def test_dark_full_width_axis_is_never_treated_as_notebook_rule():
    source = Image.new('RGB', (200, 150), 'white')
    ImageDraw.Draw(source).line((0, 70, 199, 70), fill='black')
    _, info = crop_figure(source, [40, 30, 150, 120], pixel_box=True)
    assert {'left', 'right'} <= set(info['edge_warnings'])


def test_full_height_column_divider_does_not_flag_top_or_bottom():
    # EJEE question pages carry a faint 2px vertical divider down the middle.
    source = Image.new('RGB', (400, 200), 'white')
    draw = ImageDraw.Draw(source)
    draw.rectangle((199, 2, 200, 197), fill=(229, 229, 229))
    draw.rectangle((250, 60, 330, 120), outline='black', width=3)
    _, info = crop_figure(source, [190, 40, 350, 140], pixel_box=True)
    assert info['edge_warnings'] == []
    assert info['source_pixel_box'][0] >= 240  # divider excluded from the figure


def test_dark_board_page_crops_by_content_not_by_black_canvas():
    source = Image.new('RGB', (400, 300), 'black')
    draw = ImageDraw.Draw(source)
    draw.rectangle((100, 80, 220, 200), outline=(240, 240, 240), width=3)
    draw.text((130, 120), 'C1', fill=(255, 200, 0))
    out, info = crop_figure(source, [60, 40, 260, 240], pixel_box=True)
    assert info['edge_warnings'] == []
    assert info['source_pixel_box'] == [100, 80, 221, 201]
    assert out.getpixel((0, 0)) == (0, 0, 0)  # clearance matches the board
    _, clipped = crop_figure(source, [60, 40, 160, 240], pixel_box=True)
    assert 'right' in clipped['edge_warnings']


def prose_and_diagram_page():
    source = Image.new('RGB', (1200, 600), 'white')
    draw = ImageDraw.Draw(source)
    for y in range(40, 200, 28):  # paragraph on the left, brushed by sloppy boxes
        draw.line((40, y, 520, y), fill='black', width=8)
    draw.rectangle((700, 100, 950, 380), outline='black', width=4)
    draw.ellipse((760, 160, 880, 300), outline='blue', width=4)
    draw.line((950, 240, 1190, 240), fill='black', width=3)  # lead running to the page edge
    return source


def test_snap_completes_a_clipped_diagram_and_ignores_brushed_prose():
    from importer_EJEE.raster_figures import snap_to_ink_blobs
    source = prose_and_diagram_page()
    box = snap_to_ink_blobs(source, [480, 60, 1000, 300])  # clips the diagram, brushes the paragraph
    assert box is not None and box[0] > 540 and box[2] >= 1190 and box[1] < 100 and box[3] > 380
    _, info = crop_figure(source, box, pixel_box=True)
    assert info['edge_warnings'] == []


def test_snap_refuses_when_foreign_prose_would_be_swallowed():
    from importer_EJEE.raster_figures import snap_to_ink_blobs
    source = Image.new('RGB', (1200, 600), 'white')
    draw = ImageDraw.Draw(source)
    for y in range(40, 560, 28):
        draw.line((40, y, 1100, y), fill='black', width=8)  # one huge paragraph block
    draw.ellipse((300, 200, 400, 300), outline='blue', width=4)
    assert snap_to_ink_blobs(source, [280, 180, 420, 320]) is None


def test_figure_candidates_list_separate_blocks_in_normalized_units():
    from importer_EJEE.raster_figures import figure_candidates
    found = figure_candidates(prose_and_diagram_page())
    assert any(abs(x - 583) < 20 and abs(w - 408) < 30 for x, y, w, h in found)
