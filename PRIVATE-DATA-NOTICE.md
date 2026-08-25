# PRIVATE DATA AND MODEL PACKAGE - DO NOT PUBLISH

This FinCompass package contains local research data, model artifacts, adaptive model state, and provenance material. Treat the complete ZIP and the protected paths below as **private local assets**.

## Non-negotiable rule

**Never upload, commit, attach, publish, mirror, or synchronize the protected assets to a public or shared service.** This includes GitHub, GitLab, Bitbucket, public cloud buckets, package registries, public Docker registries, issue trackers, public release assets, shared links, public notebooks, paste sites, or public CI artifacts.

Protected paths include:

- `data/` except the empty `data/.gitkeep` placeholder;
- `datasets/market-seed/`;
- `models/`;
- `adaptive_models/`;
- any future `private_assets/` directory;
- database/model/archive payloads such as `*.db`, `*.sqlite`, `*.sqlite3`, `*.joblib`, `*.npz`, `*.tar.gz` when they contain local research assets.

## How the safeguards work

FinCompass uses defense in depth to reduce accidental disclosure:

1. `.gitignore` excludes protected data/model paths from ordinary staging.
2. The local restricted-file pre-commit hook rejects protected paths if they are staged anyway.
3. The GitHub Restricted Folder Guard rejects a push/PR when protected paths are tracked.
4. `tools/package_source.py` creates a **public-safe source ZIP** and excludes protected data/model assets even though they are present in this private package.
5. The complete private backup requires the separate `tools/package_private_backup.py` command and an explicit private-local-only acknowledgement.
6. The application has no data-upload or model-upload feature, no analytics, and no telemetry. Market-data refresh is pull-only: data are downloaded to the local research store and training reads from that local store.

## If you use an existing Git repository

`.gitignore` does not untrack files that were already committed in the past. Before any push, verify that no protected path is tracked. The included CI guard is intentionally designed to fail if protected paths are present in repository history at the pushed revision.

Do not disable, bypass, or weaken the restricted-file guard to make a push pass.

## Public sharing procedure

If you need a source package for public review, use only:

`python tools/package_source.py --output FinCompass-public-source.zip`

Then inspect the generated ZIP. It will contain `PUBLIC_RELEASE_MANIFEST.sha256` and will not contain the protected data/model paths listed above.

**Do not publish this complete private ZIP.**

## Private backup procedure

Keep the full ZIP on local encrypted storage or another private location under your control. To create another complete private backup from the source tree, use:

`python tools/package_private_backup.py --output FinCompass-private-backup.zip --confirm-private-local-only`

Never place that backup in a public repository, public release, or public/shared cloud link.

## Important limitation

No software safeguard can prevent a person with filesystem access from deliberately copying a private file and publishing it manually. These controls are designed to block normal accidental commit/package/public-release paths and to make any intentional bypass conspicuous.
