"""Offline visual review/performance harness. Fixtures never enter live state.

Run from hearth/: python -m hearth.tests.visual_check --out run/graphics-review
Writes PNGs, performance.json and a silent motion preview with synthetic people.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw

from hearth.draw import _GLOW_STOPS, _glow_at, render
from hearth.tests.test_draw import scene


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    ap.add_argument('--ffmpeg', default=os.path.expanduser('~/.local/bin/ffmpeg-static'))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    live = Path.home() / '.local/share/hearth/run'
    kick = Path.home() / '.local/share/kick-live'
    for forbidden in (live.resolve(), kick.resolve()):
        if out == forbidden or forbidden in out.parents or out in forbidden.parents:
            raise SystemExit('Refusing output overlapping a live runtime')
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Choose a new empty output directory; existing previews are not overwritten')
    out.mkdir(parents=True, exist_ok=True)
    for h in _GLOW_STOPS:
        _glow_at(h)
    perf = []
    for n in (0, 1, 8, 32):
        world = scene(.4, n)
        for i in range(3):
            render(world, 1000.+i/30., i)
        times = []
        for i in range(60):
            start = time.perf_counter()
            render(world, 1000.+i/30., i)
            times.append((time.perf_counter()-start)*1000.)
        row = {'people': n, 'mean_ms': round(float(np.mean(times)), 2),
               'p95_ms': round(float(np.percentile(times, 95)), 2),
               'max_ms': round(max(times), 2)}
        perf.append(row)
        print(row, flush=True)
        render(world, 1000., 0).save(out / ('people-%02d.png' % n))
    (out / 'performance.json').write_text(json.dumps(perf, indent=2)+'\n')
    tiles = []
    for heat, name in ((0., 'ash'), (.12, 'embers'), (.4, 'campfire'), (.7, 'bonfire'), (1.15, 'wildfire')):
        im = render(scene(heat, 8), 1000., 0)
        im.save(out / (name+'.png'))
        tiles.append((name, im.resize((512, 288), Image.Resampling.LANCZOS)))
    sheet = Image.new('RGB', (1024, 3*316), (12, 20, 28))
    sd = ImageDraw.Draw(sheet)
    for i, (name, tile) in enumerate(tiles):
        x, y = i%2*512, i//2*316
        sheet.paste(tile, (x, y+28))
        sd.text((x+12, y+8), name+' / offline fixture scene', fill=(219, 222, 214))
    sheet.save(out / 'contact-sheet.jpg', quality=94)
    # A single rawvideo input avoids touching FIFOs, chat files or live audio.
    env = {k:v for k,v in os.environ.items() if k not in
           ('STREAM_KEY', 'SRT_PASSPHRASE', 'KICK_CLIENT_SECRET', 'KICK_TOKEN')}
    cmd = [args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
           '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1280x720', '-r', '30', '-i', 'pipe:0',
           '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out/'hearth-graphics.mp4')]
    world = scene(.1, 8)
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, env=env) as encoder:
        try:
            for i in range(360):
                # Continuous 12-second warm-up/cool-down; no synthetic chat is sent.
                u = i/359.
                world.heat = world.shown_heat = float(.02 + 1.1*np.sin(np.pi*u)**2)
                encoder.stdin.write(render(world, 1000.+i/30., i).tobytes())
            encoder.stdin.close()
            if encoder.wait(timeout=30):
                raise RuntimeError('Preview encoder failed')
        except BaseException:
            encoder.kill()
            encoder.wait()
            raise
    (out/'README.txt').write_text('Offline graphics preview. All characters are synthetic test fixtures.\n'
                                'No live chat or runtime state was read or changed. Video is intentionally silent;\n'
                                'the existing live audio implementation is unchanged.\n')
    print('Preview:', out/'hearth-graphics.mp4', flush=True)
    if any(row['p95_ms'] > 33.33 for row in perf):
        raise SystemExit('One or more measured render p95 values exceeded the 30 fps budget')


if __name__ == '__main__':
    main()
