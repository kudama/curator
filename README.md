# Curator

Your library, considered.

Curator is a local Mac workspace for reviewing and improving Plex libraries, with particular attention to home movies. Browse files, edit metadata and artwork, organize folders, process video, compare results, and explicitly publish the changes you choose.

**Early preview.** macOS is the intended platform. Provider behavior and mounted-storage compatibility still need broader testing. Curator runs independently; no agent platform, cloud account, Docker, Node build, or Python package installation is required.

Curator started as a tool for my own Plex library and home-movie workflow, so its current features and assumptions reflect that specific use case. I'm sharing it in the hope that it's useful to others, and I welcome [feature requests, ideas, and bug reports](https://github.com/kudama/curator/issues) for other workflows.

## What it does

- Compact library workbench with search, folder/task grouping, and a persistent review panel.
- Separate Metadata Manager and Artwork Manager views retain pending edits when switching, with durable artwork review tasks and explicit crop/pad previews; People has a dedicated portrait editor without cropping; shared folder backgrounds use filename arrows and exact member selection. Style guides have their own editor, and logos can be composed with installed host fonts.
- Shared editable visual styles, manual prompt preparation/import, and reviewed folder cover/background/logo/square artwork.
- Searchable Collections, Tags / genres, and Labels from the selected Plex library; draft new names inline. Smart collections are read-only.
- Folder metadata previews, fill/merge/replace modes, shared artwork/cast, and reusable folder defaults.
- Multiple Plex storage roots with independent mappings to Mac-mounted folders.
- Shared queues across libraries, per-type concurrency, safe pause, and a four-job copy/delete limit.
- HandBrake encoding and optional Topaz upscaling, remembered defaults, unattended-run readiness, progress/estimates, recovery guidance, and durable summaries.
- Separate Processing, Review, and Publishing stages; automatic comparisons, continuous review with saved position, and selected-result accept/reject actions.
- Multipart video joins with reviewed ordering, chapter markers, and metadata choices; reviewed file renaming.
- Local home-movie analysis through optional Ollama, manual artwork prompts/import, playlist ordering, and Kometa definition export.

## Appearance

Use the **Theme** selector in the upper-right corner to choose **Classic** or **Cyberpunk**. The choice applies immediately and is remembered in that browser for the current Curator address. It does not change library data or pending edits.

## Get started

Install [Python 3.11 or newer for macOS](https://www.python.org/downloads/macos/). Download this repository using **Code → Download ZIP**, extract it, and open Terminal in the extracted folder. Confirm your interpreter, then start Curator:

```sh
python3 --version
python3 -m curator.web --open
```

You can also double-click `Curator.command`. If macOS blocks the launcher, use the Terminal command above.

Curator opens at http://127.0.0.1:8790. The default is a local application. Optional trusted private-network hosting is described in the Foundry deployment guide.

1. In **Settings**, enter your Plex server root URL (for example, `http://plex-server:32400`) and token. Use a server you administer. Plex documents [how to find your token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/). Use the direct server URL; redirects are refused to protect the token.
2. Refresh libraries and select one. In **Library settings**, map every Plex media location to its corresponding mounted Mac folder.
3. Choose the commercial or home-movie profile. Scan the library to analyze files.
4. Review proposals in the workbench. Save metadata explicitly, or approve selected processing tasks. In **Queue**, choose **Run all libraries**, review readiness and start the run.
5. Open **Ready for review**. Comparisons load automatically; **Accept & publish** queues publication and continuous review advances to the next result. Copying, verification, and Plex refresh remain visible in Queue. Bulk acceptance warns before publishing selected results without individual inspection; rejection resets eligible jobs to suggestions.

For example, a Plex root `/srv/media/Home Movies` might map to `/Volumes/Media/Home Movies`. These are examples, not required paths. Library browsing and metadata editing do not require all video tools; probing and processing require configured executables.

## Optional tools

| Tool | Used for | Setup |
| --- | --- | --- |
| FFmpeg and ffprobe | Video inspection, sampling, joining, validation | Install from [FFmpeg](https://ffmpeg.org/download.html). Curator checks the Topaz bundle, your PATH, and common Homebrew paths. Explicit paths in Settings take precedence. |
| HandBrakeCLI | Encoding and preset discovery | Get the CLI from [HandBrake](https://handbrake.fr/downloads2.php); install/configure the `HandBrakeCLI` executable. Select an installed preset before queueing. |
| Topaz Video | Optional upscaling | Install and license separately; configure its executable and reviewed model/filter settings. |
| Ollama | Optional local home-movie analysis | Runs at `127.0.0.1:11434`; the default vision model is `qwen3-vl:8b-instruct`. |
| ImageMagick | Optional local portrait fitting and transparent logo composition | Installed on the Curator host; set an optional executable path under Settings → Processing tools. Uses host font files. Local operations share the file-operation queue (max four); no Gems. |
| Mage / external image editor | Optional artwork creation | Curator prepares prompts/reference frames; create images manually and import them. Optional API model/balance discovery and durable generation jobs are available. Settings → Mage manages the key, connection test, live model list, defaults and Gems budgets. Generation prioritizes Mango 2/3/4 under Advanced and supports other advertised image schemas when their controls and pricing are supported. Every paid batch requires a current exact estimate and explicit Generate approval; unavailable pricing blocks submission. Results return for artwork review. |
| Kometa | Exported collection definitions | Curator exports definitions; managed Kometa execution is not included. |

No third-party executables, models, or media are bundled. Their licenses and terms apply separately.

## Originals, recovery, and local data

Processed videos are separate outputs until accepted. Publication rechecks source/output identity and hashes, stages the replacement, and preserves the original alongside it as `film-old.mkv` for a source named `film.mkv`. Existing backup names block replacement. Join publication retains its source parts. There is no automatic original cleanup.

Private state defaults to `~/Library/Application Support/Curator`: settings, Plex token, SQLite catalog, task receipts, and generated assets. The token is stored locally, not encrypted by Curator. An optional Mage key is kept separately in a private `mage-api-key` file (owner-only permissions); it is never returned by the state API. Manage it under Settings → Mage, with explicit Save API key and Remove connection actions. Keychain integration remains a follow-up. When an operation fails, the app shows a short message and records the cause, with its traceback, in `logs/curator.log` inside this folder (owner-only permissions, rotated at about 1 MB, three old files kept). The Plex token, the Mage key and token-style values are redacted before anything is written; media titles and paths can appear, as they do in the catalog. Keep this folder private and outside Git. Media remains on your mapped storage. Explicitly saved folder artwork preferences may also create sidecars beside media.

Stop with Ctrl+C. Restart only after active work finishes. Interrupted processing/publication becomes blocked for inspection instead of replaying automatically. To use a separate test state directory:

```sh
python3 -m curator.web --state /tmp/curator-demo --port 8791 --open
```

## Current limits

This preview has automated fixture coverage and limited operator acceptance, not compatibility certification for every Plex agent, client, codec, or NAS. Cast/artwork rendering varies across Plex clients. Licensed Topaz model acceptance, representative encoding quality, local-vision semantic quality, and broader mounted-storage recovery need further verification. Automated HD visual-quality scoring, richer metadata matching, managed Kometa execution, and extras creation remain unfinished. Windows support and public Internet hosting are not provided. Private-network hosting is opt-in and requires the documented network acceptance checks.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q curator
node --check curator/static/app.js
node --check curator/static/workbench.js
node --check curator/static/collections.js
```

Python formatting and basic lint use [ruff](https://docs.astral.sh/ruff/) (a developer tool only; configured in `pyproject.toml`, version pinned in CI):

```sh
python3 -m pip install ruff==0.17.5
ruff format curator tests
ruff check curator tests
```

Node is only used for optional developer syntax checks. Tests use synthetic data and temporary state; optional integration tests skip when the required local tools are missing.

For optional service use after login on a separate Mac, see [Foundry single-host deployment](docs/foundry-deployment.md). The default local installation is unchanged.

See [troubleshooting and recovery](docs/troubleshooting.md), [architecture](docs/architecture.md), [validation](docs/validation.md), [release review](docs/release-readiness.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [third-party notices](THIRD_PARTY_NOTICES.md). Report reproducible bugs in [GitHub Issues](https://github.com/kudama/curator/issues), using synthetic media and sanitized details.

Workflow details: [shared task queues](docs/task-queues.md), [file operations](docs/file-operation-queue.md), [continuous review](docs/continuous-review.md), and [unattended runs](docs/unattended-runs.md).

MIT licensed. Curator is independent of Plex, HandBrake, Topaz, Ollama, Mage, and Kometa.

## Batch review and retained originals

Use task-group **Select all** and **Review selected** for large upscale/optimization result sets. Comparisons are prepared before separately confirmed, sequential publication. **Clean up originals** previews receipt-backed retained backups and requires selected permanent-deletion confirmation. Output settings support quality or bitrate targets, with size/Mbps warnings in Review. See [workflow and recovery details](docs/batch-review-cleanup.md).
