"""Bounded readers for encoder status output; estimates cover encoding only."""
import math
import re
import time


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def encoder_status(text, kind, duration, elapsed):
    if kind == 'optimize':
        matches = list(re.finditer(r'Encoding:\s*task\s+(\d+)\s+of\s+(\d+),\s*([\d.]+)\s*%([^\r\n]*)', text))
        if not matches:return None
        row = matches[-1];current, total = int(row[1]), int(row[2]);percent = float(row[3])
        if not 1 <= current <= total or not math.isfinite(percent) or not 0 <= percent <= 100:return None
        percent = 100 * (current - 1 + percent / 100) / total
        tail = row[4];eta = re.search(r'ETA\s+(\d+)h(\d+)m(\d+)s', tail)
        remaining = int(eta[1])*3600 + int(eta[2])*60 + int(eta[3]) if eta and total == 1 else None
        if remaining is None and elapsed >= 10 and percent > 0:remaining = elapsed*(100-percent)/percent
        fps = re.search(r'([\d.]+)\s*fps', tail)
        return dict(record=row[0], percent=percent, eta_seconds=remaining, fps=positive(fps[1]) if fps else None,
                    pass_number=current, pass_count=total, eta_source='encoder' if eta and total == 1 else 'average progress')
    matches = list(re.finditer(r'(?:^|[\r\n])([^\r\n]*\btime=(\d+):(\d+):(\d+(?:\.\d+)?)[^\r\n]*)', text))
    if not matches:return None
    row = matches[-1];seconds = int(row[2])*3600 + int(row[3])*60 + float(row[4])
    duration = positive(duration)
    if not duration or not math.isfinite(seconds) or seconds < 0:return None
    seconds = min(seconds,duration);speed = re.search(r'\bspeed=\s*([\d.]+)x',row[1]);rate = positive(speed[1]) if speed else None
    if not rate and elapsed >= 10:rate = positive(seconds/elapsed)
    fps = re.search(r'\bfps=\s*([\d.]+)',row[1])
    return dict(record=row[1], percent=100*seconds/duration, encoded_seconds=seconds,
                eta_seconds=(duration-seconds)/rate if rate else None, fps=positive(fps[1]) if fps else None,
                eta_source='encoder speed' if speed and positive(speed[1]) else 'average progress')


class EncodingProgress:
    def __init__(self, kind, duration):
        self.kind, self.duration = kind, duration
        self.offset = 0
        self.tail = ''
        self.record = None
        self.last_elapsed = None
        self.metrics = {}

    def read(self, path, elapsed):
        try:
            size = path.stat().st_size
            if size < self.offset:self.offset=0;self.tail='';self.record=None;self.metrics={};self.last_elapsed=None
            with path.open('rb') as stream:
                stream.seek(max(self.offset,size-65536))
                chunk=stream.read(65536);self.offset=stream.tell()
            self.tail=(self.tail+chunk.decode('utf-8',errors='replace'))[-65536:]
            row=encoder_status(self.tail,self.kind,self.duration,elapsed)
            if row and row['record'] != self.record:
                self.record=row.pop('record');self.metrics={**row,'eta_updated_at':time.time()};self.last_elapsed=elapsed
        except (OSError, ValueError, OverflowError):
            pass
        metrics=dict(self.metrics)
        if self.last_elapsed is None or elapsed-self.last_elapsed > 15:
            metrics.update(eta_seconds=None,eta_stale=True)
        return metrics
