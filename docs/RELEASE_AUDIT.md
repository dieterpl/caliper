# Repository privacy review

Reviewed 2026-09-30. The initial snapshot was prepared from the audited application
files with fresh Git history. Automated scans and manual inspection found no
credentials, real chat transcripts, personal filesystem paths, private network
addresses or host hardware details in the publishable files. No audit can
guarantee detection of every possible secret.

## Published content

- Application code, tests, examples, current documentation and required license
  notices are retained. Screenshots show CAD geometry and application UI; their
  PNG files contain no text or EXIF metadata.
- Public upstream links, the repository owner's GitHub username and no-reply
  commit attribution remain intentional.
- Runtime workspaces, credentials, provider state, virtual environments and build
  output are ignored local data and are excluded from the published snapshot.
- Restricted rollback copies outside this project contain previous history.
  They must not be published or merged into the fresh repository.

## Repeat the checks

Fetch all branches before scanning. CI runs the privacy check and Gitleaks;
regression tests cover deleted files, off-branch messages, credential directories
and private address ranges. Inspect new screenshots manually as well.

```bash
git fetch origin --prune --tags
python3 scripts/check-release.py --history
gitleaks git . --log-opts=--all --redact
```

## Final source-release review

Reviewed again on 2026-09-30 against main and all fetched remote branches:

- Privacy checks and redacted Gitleaks scans passed across all eight reachable
  commits, the release file snapshot and the compiled frontend. The five
  additional branches are Dependabot updates. GitHub had no release assets or
  Actions artifacts at review time.
- All 17 unique documentation images in reachable history were inspected;
  their PNG chunks contain image data only, without text or EXIF metadata.
- All 53 Python tests passed in Python 3.11. Frontend type checking and the
  production build passed. npm audit and pip-audit of the locked Python
  dependencies reported no known vulnerabilities.
- A Docker build from a clean release snapshot succeeded without a local
  Butai binary. A disposable container started, created a workspace without
  an agent, and exported its CAD model and STEP/STL bundle. Licence and export
  downloads passed; traversal and private-file requests were refused.
  Desktop/mobile browser smoke checks passed without launching paid agents.
- The image includes the root LICENSE and NOTICE. New workspaces retain the
  template licence and scoped attribution. The frontend serves dependency
  notices, Apache/MPL licence texts and the exact bundled Butai helper source;
  these endpoints were checked against their source files.
- The Butai installer now refuses a missing checksum download. Both a real
  checksum-verified download and a simulated checksum failure were checked.

This review covers publication of the source repository. Installed runtime
components retain their own terms; see [NOTICE](../NOTICE) before distributing
prebuilt images. Repository visibility was not changed by this review.

## Limits

Fresh history does not erase other clones, backups or GitHub's internal retention.
Use a fresh clone instead of pushing from a previous clone. GitHub-side removal
of retained sensitive data may require
[GitHub Support](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
See [SECURITY.md](../SECURITY.md) for deployment guidance.
