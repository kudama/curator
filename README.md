> **Moved to Thoth:** New development belongs in [thoth/agents/curator](https://github.com/kudama/thoth/tree/main/agents/curator). This repository is retained as an archived historical reference. The original commits and files are preserved in Thoth history.

# Curator

A proposed local media intelligence and management service above Plex, Sonarr/Radarr, and Synology.

Status: design and planning. This repository stores the discussed feature set and proposed workflows/specifications. No application, connectors, or automatic media operations are implemented.

## Planned capabilities

- Library health: corrupt/incomplete files, duplicates, orphaned files, missing subtitles, bad Plex matches, naming and codec/container inconsistencies.
- Storage intelligence: utilization by library/resolution/codec, historical growth, capacity forecasts, oversized files, and estimated reclaimable space.
- Smart transcoding and codec modernization: estimate useful HEVC/AV1 savings, preserve intentional high-quality remuxes, validate output, replace safely, and retain rollback.
- Playback intelligence: Direct Play/Direct Stream/transcode, client compatibility, buffering/failures, and explanations for transcoding.
- Usage and upgrade context: use authorized watch history to inform recommendations; show the quality/storage tradeoff of proposed Sonarr/Radarr upgrades.
- Metadata curation: bad matches, missing artwork, collections/tags, duplicate editions, and reviewed corrections.
- Home movies: separate privacy and preservation rules; retain originals, identify duplicates, organize dates, and propose local tagging/search and previews.
- Operations: dashboard, job history, service versions, approved upgrades, and backup/recovery checks for databases/configuration.

Operating model: **Discover → Recommend → Approve → Execute → Verify → Roll back.** Watch history informs recommendations; it does not authorize deletion.

## Documents

- [Proposed specification](docs/specification.md)
- [Theoretical workflows](docs/workflows.md)
- [Decisions and sources](docs/decisions.md)

Credentials, media, watch history, catalogs, exports, databases, and machine-specific configuration belong outside Git. Jarvis can consume Curator's authorized summaries through a future bounded interface.
