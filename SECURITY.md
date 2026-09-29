# Security

Caliper is a workbench for trusted users and trusted CAD projects. Access to its
UI/API grants command execution in the container, access to every workspace,
and access to the agent credentials mounted there. Importing or building a CAD
project executes Python. The container is not a sandbox for hostile models, and
the shared password does not isolate users from one another.

## Deployment

- The default Compose port binding is `127.0.0.1`. Keep it for local use.
- LAN access requires both `BIND_ADDR=0.0.0.0` and a strong `WEB_TOKEN`.
  Configure HTTPS at a trusted reverse proxy, or use an SSH tunnel. Forward
  the original Host header so browser-origin checks work. The Python listener
  itself provides HTTP only; the login cookie is not marked Secure to support
  localhost HTTP. Do not expose that listener directly to the internet.
- Use a dedicated agent account/login directory if you do not want the
  workbench to access your normal agent credentials. Mount only needed data.
- Back up `workspaces/` and the state volume privately. They contain designs,
  history, session output and logins. Never attach them to a GitHub release.
- The standalone backend binds to localhost; `SERVER_BIND=0.0.0.0` is used
  inside Docker, with Compose controlling the published host interface.

## Reporting

Use the repository's GitHub **Security → Report a vulnerability** option when
private reporting is enabled. If it is unavailable, open an issue asking for a
private reporting channel without including exploit details, credentials or
private files. Do not post secrets in public issues or pull requests.

## Release checks

Run the checks in `.github/workflows/ci.yml`. npm and Python dependencies are
locked; Python installs verify hashes. Regenerate `requirements.lock` with
`uv pip compile requirements.txt --python-version 3.11 --universal
--generate-hashes --no-annotate --no-header -o requirements.lock`, then rerun
tests and dependency audits. Review screenshots as well as source files.

Keep GitHub secret scanning and push protection enabled where available.
A clean current tree does not remove private data from previous commits,
branches, tags, pull requests or existing clones. See
[the release audit](docs/RELEASE_AUDIT.md) before publishing historical refs.
