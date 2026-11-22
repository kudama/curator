"""Optional, read-only scene hints from two small windows, never a full-film scan."""

import math
import re
import subprocess
import threading

from .errors import UserError

WINDOW_MS = 3000
_scan_slot = threading.BoundedSemaphore(1)


def nearby_cut(ffmpeg, source, target_ms, duration_ms, stream):
    start = max(0, target_ms - WINDOW_MS)
    end = min(duration_ms, target_ms + WINDOW_MS)
    # Input seeking and -t bound decoded footage. Sampling limits filter work;
    # returned hints are approximate and must be reviewed, not called exact cuts.
    command = [
        ffmpeg,
        '-nostdin',
        '-hide_banner',
        '-loglevel',
        'info',
        '-ss',
        str(start / 1000),
        '-t',
        str((end - start) / 1000),
        '-i',
        str(source),
        '-map',
        '0:' + str(stream),
        '-an',
        '-sn',
        '-dn',
        '-vf',
        "fps=12,scale=320:180:force_original_aspect_ratio=decrease,select='gt(scene,0.30)',showinfo",
        '-f',
        'null',
        '-',
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise UserError('Scene search is unavailable; keep the manual interval or try again') from None
    if result.returncode or len(result.stderr) > 2 * 1024 * 1024:
        raise UserError('Scene search could not read this source; manual selection is still available')
    cuts = []
    for stamp in re.findall(rb'pts_time:([\d.eE+-]+)', result.stderr):
        value = float(stamp)
        if not math.isfinite(value):
            continue
        cut = round(start + value * 1000)
        if 0 < cut < duration_ms and abs(cut - target_ms) <= WINDOW_MS:
            cuts.append(cut)
    return min(cuts, key=lambda cut: (abs(cut - target_ms), cut)) if cuts else None


def suggest_boundaries(ffmpeg, source, start_ms, end_ms, duration_ms, stream):
    if not _scan_slot.acquire(blocking=False):
        raise UserError('Another scene search is running; keep the manual interval or try shortly')
    try:
        start = nearby_cut(ffmpeg, source, start_ms, duration_ms, stream)
        end = nearby_cut(ffmpeg, source, end_ms, duration_ms, stream)
        return dict(
            start_ms=start if start is not None else start_ms,
            end_ms=end if end is not None else end_ms,
            found=dict(start=start is not None, end=end is not None),
        )
    finally:
        _scan_slot.release()
