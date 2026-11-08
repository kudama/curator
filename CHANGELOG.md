# Changelog

## Third-party readiness fixes (2026-11-08)

- Refuse Plex API redirects so tokens stay with the configured server.
- Use exclusive processed-video installation and restoration to preserve files created during publication.
- Discover standard FFmpeg/ffprobe installations without Topaz; retain explicit-path precedence.
- Explain Python/startup requirements and support common Mac Python locations in the launcher.
- Add setup/recovery guidance and a readiness review with remaining acceptance.
- 265 tests pass with synthetic-video integration, including a clean stdlib-only source copy.

## Initial public preview (prepared 2026-11-08)

Standalone Curator application snapshot with the library workbench, dedicated Publishing stage, collapsible work groups, library-scoped metadata pickers, and existing reviewed processing/publication workflows. Includes MIT license, setup and contribution documentation, privacy boundaries, and automated checks. Published at commit `8ff0da8`; GitHub Actions acceptance is recorded separately from publication.
