"""Combine rendered trees into the checked-in catalogue (requires Pillow).

python game/tools/make_tree_catalogue.py --work work/trees
"""
import argparse
import json
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,default=ROOT/'work/trees')
    parser.add_argument('--font',default='DejaVuSans.ttf')
    args=parser.parse_args()
    models=json.loads((ROOT/'assets/models/trees/tree_kit.json').read_text())['models']
    def font(n): return ImageFont.truetype(args.font,n)
    def compose(records,cols,headline,filename):
        rows=(len(records)+cols-1)//cols
        im=Image.new('RGB',(cols*320,128+rows*414),(25,33,31))
        draw=ImageDraw.Draw(im)
        draw.text((28,20),headline,font=font(34),fill=(238,232,210))
        draw.text((30,72),'100-unit figure in every view | shared scale | original OBJ + GLB models',
                  font=font(18),fill=(171,191,174))
        for i,info in enumerate(records):
            x=i%cols*320;y=128+i//cols*414
            im.paste(Image.open(args.work/(info['name']+'.png')).convert('RGB'),(x,y))
            draw.text((x+12,y+365),info['name'][5:].replace('_',' ').title(),font=font(20),fill=(240,228,196))
            draw.text((x+12,y+391),f"{info['height']:g} units  /  {info['triangle_count']:,} tris",
                      font=font(14),fill=(167,189,173))
        folder=ROOT/'docs/images';folder.mkdir(parents=True,exist_ok=True)
        im.save(folder/filename,quality=91,subsampling=0)
    compose(models,8,'MINIWIND  /  WOODLAND COLLECTION  /  48 MODELS','tree_kit_catalogue.jpg')
    names=['tree_oak_autumn','tree_maple_crimson','tree_spruce_blue',
           'tree_willow_gold','tree_birch_bare','tree_palm_bent']
    compose([next(m for m in models if m['name']==name) for name in names],6,
            'MINIWIND  /  AUTUMN, EVERGREEN & BARE TREES','tree_kit_selection.jpg')


if __name__=='__main__': main()
