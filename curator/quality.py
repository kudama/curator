"""Explain technical quality and efficiency findings without modifying media."""


def display_geometry(media):
    """Displayed dimensions, including anamorphic pixels and rotation metadata."""
    from fractions import Fraction
    import math
    width, height = float(media['width']), float(media['height'])
    video = next((s for s in media.get('streams', []) if s.get('codec_type') == 'video'
                  and not s.get('disposition', {}).get('attached_pic')), {})
    def ratio(value):
        try:
            number = float(Fraction(str(value).replace(':', '/')))
            return number if math.isfinite(number) and number > 0 else None
        except (ValueError, ZeroDivisionError):
            return None
    sar = ratio(video.get('sample_aspect_ratio'))
    dar = ratio(video.get('display_aspect_ratio'))
    width *= sar if sar else dar * height / width if dar else 1
    rotation = next((r['rotation'] for r in video.get('side_data_list', []) if 'rotation' in r),
                    video.get('tags', {}).get('rotate', 0))
    try:
        if abs(float(rotation)) % 180 == 90:
            width, height = height, width
    except (TypeError, ValueError):
        pass
    return width, height


def assess(media: dict, policy: dict | None = None) -> list[dict]:
    """Return findings with kind, reason and evidence.

    Media fields: width, height, duration_seconds, size_bytes, codec, bitrate,
    preserve_quality (bool). Policy optional: max_mbps_1080=18, max_mbps_4k=55.
    Preserve aspect ratio: 1920x800 cinematic is 1080-class; 1280x720 is not.
    Portrait 1080x1920 is also 1080-class. Use long/short edge together.
    Missing or invalid dimensions need inspection, never an invented target.
    Duration/size/bitrate context is needed to suggest optimization.
    A codec name alone is not an optimization reason.
    preserve_quality suppresses optimization, not below-1080 findings.
    Do not promise visual improvement or savings from technical data alone.
    """
    # Local qwen3-coder proposal, corrected by Forge for invalid inputs and aspect ratio.
    import math
    def positive(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    policy = policy or {}
    width, height = media.get('width'), media.get('height')
    if not positive(width) or not positive(height):
        return [dict(kind='inspect', reason='Dimensions missing or invalid', evidence={})]
    width, height = display_geometry(media)
    long_edge, short_edge = max(width, height), min(width, height)
    findings = []
    if long_edge < 1920 or short_edge < 720:
        findings.append(dict(kind='upscale', reason='Source is below the 1080-class target',
                             evidence=dict(width=width, height=height, target_long_edge=1920,
                                           preserve_aspect_ratio=True)))
    else:
        findings.append(dict(kind='upscale', reason='Optional Topaz upscale and re-encode',
                             evidence=dict(width=width, height=height, optional=True,
                                           preserve_aspect_ratio=True)))
    duration, bitrate, size = (media.get(x) for x in ('duration_seconds', 'bitrate', 'size_bytes'))
    if positive(duration) and not media.get('preserve_quality'):
        if not positive(bitrate) and positive(size):
            bitrate = size * 8 / duration
        limit = policy.get('max_mbps_4k' if long_edge >= 3840 else 'max_mbps_1080',
                           55 if long_edge >= 3840 else 18)
        if positive(bitrate) and positive(limit) and bitrate > limit * 1_000_000:
            findings.append(dict(kind='optimize', reason='Bitrate exceeds the configured review threshold',
                                 evidence=dict(mbps=round(bitrate / 1_000_000, 2), threshold_mbps=limit,
                                               codec=media.get('codec'), estimated_savings=None)))
    if any(x['kind'] == 'upscale' and not x.get('evidence', {}).get('optional') for x in findings) and any(x['kind'] == 'optimize' for x in findings):
        findings = [x for x in findings if x['kind'] != 'optimize']
        findings[0]['reason'] += '; encode efficiently in the same processing plan'
    return findings
