# Isolated v2 development and testing

The operator authorized a separate DEV/TEST instance for reviewing working v2
changes. This is a test deployment, not v2 release acceptance or production promotion.
Use a separate checkout and dedicated sandbox. Never copy a production database,
provider key, queue, catalogue or media directory into it.

## Profile and startup

Python 3.11+ is required. From the test checkout:

```sh
python3 scripts/seed-development.py --development-root "$HOME/Curator-DEV"
python3 -m curator.web --development-root "$HOME/Curator-DEV" \
  --state "$HOME/Curator-DEV/state" --port 8791
```

The seed uses installed FFmpeg to create three short synthetic videos, local artwork,
a sample home library and metadata recommendations. All queues start paused. It refuses
an existing catalogue or output file. Do not use `--replace` to reseed data.

The optional development profile:

- Shows a DEV / TEST banner, page title and service status environment.
- Uses a separate session cookie per dev port; production sessions retain their name.
- Rejects unmarked existing state and sandboxes overlapping the default production state.
- Blocks Plex, Mage REST/pricing/downloads, Mage key storage and vision analysis.
- Rejects external media mappings and archive roots, including resolved symlink escapes.
- Serves explicitly seeded synthetic artwork from within the sandbox.

This is a guard against accidental configuration reuse, not an OS security boundary
against a malicious local user. Do not put production data in the sandbox. Provider
workflows intentionally fail with an explicit disabled message; this instance supports
local/UI testing, not live Plex publication or paid generation. Testing those integrations
later requires a separate deliberate configuration and disposable service data.

## Foundry managed instance

Use an explicit private bind and a distinct label. Example from the test checkout:

```sh
python3 scripts/install-foundry-launchagent.py \
  --label com.curator.foundry.dev --development-root "$HOME/Curator-DEV" \
  --state "$HOME/Curator-DEV/state" --port 8791 \
  --host 10.0.0.10 --expected-host foundry --expected-host foundry.example.test
```

Substitute the verified host address and browser names. The installer prints bootstrap
commands for this user's GUI session. The DEV LaunchAgent starts after login, independently
of a production system LaunchDaemon. It does not start before login. It refuses the
production label in development mode. Never boot out or restart the production service
as part of test deployment.

Update only the test checkout to the exact reviewed/tested feature or v2 commit; confirm
its worktree is clean, restart only the dev label, then verify `/api/service/status`, the
banner, synthetic catalogue and provider/path guards. Preserve dev state across updates.
Record the deployed SHA on the issue. A feature branch can be deployed here for review;
that does not substitute for independent review before merging it into v2.

Rollback consists of stopping only the dev label and returning the dev checkout to the
last tested commit. Retain its sandbox. Remove the test instance only by explicit request.
