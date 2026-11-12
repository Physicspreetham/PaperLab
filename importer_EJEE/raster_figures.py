"""Lossless raster figure export shared by model previews and final publishing."""
import math
from PIL import Image, ImageOps


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
    ink=region.convert('L').point(lambda p:255 if p<245 else 0)
    bounds=ink.getbbox()
    if not bounds:raise ValueError('Figure crop contains no visible content')
    left,top,right,bottom=bounds
    touching=[]
    for edge,cut in [('left',left<2),('top',top<2),('right',right>region.width-2),('bottom',bottom>region.height-2)]:
        if cut:touching.append(edge)
    content_box=[px[0]+left,px[1]+top,px[0]+right,px[1]+bottom]
    content=im.crop(content_box)
    padding=max(8,min(32,math.ceil(max(content.size)*.015)))
    output=ImageOps.expand(content,border=padding,fill='white')
    return output,{'requested_source_pixel_box':px,'source_pixel_box':content_box,
                   'white_padding_px':padding,'edge_warnings':touching,'size':list(output.size),
                   'method':'lossless source pixels; blank margins trimmed; white display clearance added'}
