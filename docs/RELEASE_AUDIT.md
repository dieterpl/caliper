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

## Limits

Fresh history does not erase other clones, backups or GitHub's internal retention.
Use a fresh clone instead of pushing from a previous clone. GitHub-side removal
of retained sensitive data may require
[GitHub Support](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
See [SECURITY.md](../SECURITY.md) for deployment guidance.
