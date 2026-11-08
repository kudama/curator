"""Source-grounded episode ordering; missing pairings remain visible."""


def interleave(assets, main_show, companion_show, companion_season_offset=0):
    if not main_show.strip() or not companion_show.strip() or main_show == companion_show:
        raise ValueError('Choose two different show titles')
    shows = {main_show: {}, companion_show: {}}
    warnings = []
    for asset in assets:
        item = asset['item']
        show = item.get('grandparentTitle')
        if show not in shows:
            continue
        season, episode = item.get('parentIndex'), item.get('index')
        if type(season) is not int or type(episode) is not int or season <= 0:
            warnings.append('Special or unnumbered item needs explicit placement: ' + asset['title'])
            continue
        if show == companion_show:
            season -= companion_season_offset
        key = season, episode
        prior = shows[show].get(key)
        if prior and prior['rating_key'] != asset['rating_key']:
            raise ValueError('Ambiguous episode numbering; resolve duplicates before ordering')
        shows[show][key] = asset
    if not shows[main_show] or not shows[companion_show]:
        raise ValueError('Scan libraries containing both requested shows first')
    ordered = []
    for position in sorted(set(shows[main_show]) | set(shows[companion_show])):
        for show in (main_show, companion_show):
            asset = shows[show].get(position)
            if asset:
                if not ordered or ordered[-1]['rating_key'] != asset['rating_key']:
                    ordered.append(asset)
            else:
                warnings.append(f'Missing {show}, season {position[0]}, episode {position[1]}')
    return ordered, warnings
