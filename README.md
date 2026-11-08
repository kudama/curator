# Curator

Your library, considered.

Curator is a local Mac workspace for reviewing and improving Plex libraries, with particular attention to home movies. Browse files, edit metadata and artwork, organize folders, process video, compare results, and explicitly publish the changes you choose.

**Early preview.** macOS is the intended platform. Provider behavior and mounted-storage compatibility still need broader testing. Curator runs independently; no agent platform, cloud account, Docker, Node build, or Python package installation is required.

Curator started as a tool for my own Plex library and home-movie workflow, so its current features and assumptions reflect that specific use case. I'm sharing it in the hope that it's useful to others, and I welcome [feature requests, ideas, and bug reports](https://github.com/kudama/curator/issues) for other workflows.

## What it does

- Compact library workbench with search, folder/task grouping, and a persistent review panel.
- Unified metadata, cast/profile pictures, cover, background, logo, and square-art editing.
- Searchable Collections, Tags / genres, and Labels from the selected Plex library; draft new names inline. Smart collections are read-only.
- Folder metadata previews, fill/merge/replace modes, shared artwork/cast, and reusable folder defaults.
- Multiple Plex storage roots with independent mappings to Mac-mounted folders.
- HandBrake encoding and optional Topaz upscaling, progress and approximate encode ETA, cancellation, and durable task history.
- Separate Processing, Review, and Publishing stages; output comparison before replacement.
- Multipart video joins with reviewed ordering, chapter markers, and metadata choices; reviewed file renaming.
- Local home-movie analysis through optional Ollama, manual artwork prompts/import, playlist ordering, and Kometa definition export.

## Get started

Install [Python 3.11 or newer for macOS](https://www.python.org/downloads/macos/). Download this repository using **Code → Download ZIP**, extract it, and open Terminal in the extracted folder. Confirm your interpreter, then start Curator:

```sh
python3 --version
python3 -m curator.web --open
```

You can also double-click `Curator.command`. If macOS blocks the launcher, use the Terminal command above.

Curator opens at http://127.0.0.1:8790. It is a local application, not a remotely hosted web service.

1. In **Settings**, enter your Plex server root URL (for example, `http://plex-server:32400`) and token. Use a server you administer. Plex documents [how to find your token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/). Use the direct server URL; redirects are refused to protect the token.
2. Refresh libraries and select one. In **Library settings**, map every Plex media location to its corresponding mounted Mac folder.
3. Choose the commercial or home-movie profile. Scan the library to analyze files.
4. Review proposals in the workbench. Save metadata explicitly, or approve selected processing tasks and run them from **Processing**.
5. Compare processed output, then **Accept & publish**. Copying, verification, and Plex refresh appear under **Publishing**.

For example, a Plex root `/srv/media/Home Movies` might map to `/Volumes/Media/Home Movies`. These are examples, not required paths. Library browsing and metadata editing do not require all video tools; probing and processing require configured executables.

## Optional tools

| Tool | Used for | Setup |
| --- | --- | --- |
| FFmpeg and ffprobe | Video inspection, sampling, joining, validation | Install from [FFmpeg](https://ffmpeg.org/download.html). Curator checks the Topaz bundle, your PATH, and common Homebrew paths. Explicit paths in Settings take precedence. |
| HandBrakeCLI | Encoding and preset discovery | Get the CLI from [HandBrake](https://handbrake.fr/downloads2.php); install/configure the `HandBrakeCLI` executable. Select an installed preset before queueing. |
| Topaz Video | Optional upscaling | Install and license separately; configure its executable and reviewed model/filter settings. |
| Ollama | Optional local home-movie analysis | Runs at `127.0.0.1:11434`; the default vision model is `qwen3-vl:8b-instruct`. |
| Mage / external image editor | Optional artwork creation | Curator prepares prompts/reference frames; create images manually and import them. |
| Kometa | Exported collection definitions | Curator exports definitions; managed Kometa execution is not included. |

No third-party executables, models, or media are bundled. Their licenses and terms apply separately.

## Originals, recovery, and local data

Processed videos are separate outputs until accepted. Publication rechecks source/output identity and hashes, stages the replacement, and preserves the original alongside it as `film-old.mkv` for a source named `film.mkv`. Existing backup names block replacement. Join publication retains its source parts. There is no automatic original cleanup.

Private state defaults to `~/Library/Application Support/Curator`: settings, Plex token, SQLite catalog, task receipts, and generated assets. The token is stored locally, not encrypted by Curator. Keep this folder private and outside Git. Media remains on your mapped storage. Explicitly saved folder artwork preferences may also create sidecars beside media.

Stop with Ctrl+C. Restart only after active work finishes. Interrupted processing/publication becomes blocked for inspection instead of replaying automatically. To use a separate test state directory:

```sh
python3 -m curator.web --state /tmp/curator-demo --port 8791 --open
```

## Current limits

This preview has automated fixture coverage and limited operator acceptance, not compatibility certification for every Plex agent, client, codec, or NAS. Cast/artwork rendering varies across Plex clients. Licensed Topaz model acceptance, representative encoding quality, local-vision semantic quality, and broader mounted-storage recovery need further verification. Automated HD visual-quality scoring, richer metadata matching, managed Kometa execution, and extras creation remain unfinished. Windows support and remote/network hosting are not provided.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q curator
node --check curator/static/app.js
node --check curator/static/workbench.js
node --check curator/static/collections.js
```

Node is only used for optional developer syntax checks. Tests use synthetic data and temporary state; optional integration tests skip when the required local tools are missing.

See [troubleshooting and recovery](docs/troubleshooting.md), [architecture](docs/architecture.md), [validation](docs/validation.md), [release review](docs/release-readiness.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [third-party notices](THIRD_PARTY_NOTICES.md). Report reproducible bugs in [GitHub Issues](https://github.com/kudama/curator/issues), using synthetic media and sanitized details.

MIT licensed. Curator is independent of Plex, HandBrake, Topaz, Ollama, Mage, and Kometa.
