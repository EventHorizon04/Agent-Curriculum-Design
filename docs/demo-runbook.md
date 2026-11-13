# Demo Runbook

Procedure for exposing the curriculum design agent to a small invited group.
Design rationale: `docs/superpowers/specs/2026-08-12-demo-deployment-design.md`.

## What this setup is and is not

Everyone who gets through Cloudflare Access shares one dataset. There are no user
accounts. Any authorised person can read and delete any program. That is
acceptable for an invited demo and unacceptable for anything wider.

**Every write route requires `X-API-Key` when `API_KEY` is set.** Set it in
`.env` and hand the key to the designer out of band: the UI opens a "กรอก API key"
dialog on the first 401, keeps the key in that browser tab only
(`sessionStorage`) and retries the request. GET routes stay open, except `GET …/evidence/classify-stream`, which runs the
classifier. If `API_KEY`
is left unset, writes are open to anyone past Access (`start-demo.ps1` warns).
Cloudflare Access is still the outer barrier, so three conditions must hold:

1. Port 8000 is never exposed directly — the tunnel is the only way in.
2. `cloudflared` points at `http://127.0.0.1:8000` (not `localhost`, which
   resolves to `::1` first — the API binds `127.0.0.1` only).
3. The Access policy is an explicit email allowlist, not "anyone with the link".

## Before the demo

1. **Back up the database.** Everyone can delete any program.

   ```bash
   docker exec ca-postgres pg_dump -U curriculum curriculum_agent > backup-YYYY-MM-DD.sql
   ```

2. **Confirm `.env` has:** `POSTGRES_PASSWORD`, `POSTGRES_DSN`,
   `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `OPENROUTER_API_KEY`. Set
   `API_KEY` and give its value to the designer. `start-demo.ps1` checks
   `OPENROUTER_API_KEY` is set and warns when `API_KEY` is not, but it cannot check `POSTGRES_PASSWORD` /
   `POSTGRES_DSN` against each other — see step 3 if you are rotating the
   Postgres password rather than starting from a fresh volume.

3. **Rotating `POSTGRES_PASSWORD` against an existing database — do this,
   not just editing `.env`.** `POSTGRES_PASSWORD` in `docker-compose.yml` is
   only read by Postgres the first time it initialises its data directory.
   Against the existing `postgres-data` volume, which holds real program
   data, changing the value in `.env` alone rotates nothing — it only stops
   the app from being able to connect. **Do not delete the `postgres-data`
   volume to force a rotation; that deletes every program in it.** Instead:

   1. Set both `POSTGRES_PASSWORD` and the password embedded in
      `POSTGRES_DSN` in `.env` to the *current* password, so the file matches
      reality before you touch anything.
   2. Rotate the password on the running container:

      ```bash
      docker exec -it ca-postgres psql -U curriculum -d curriculum_agent \
        -c "ALTER USER curriculum WITH PASSWORD 'the-new-password';"
      ```

   3. Update `.env`: set `POSTGRES_PASSWORD` to the new password, and update
      the password embedded in `POSTGRES_DSN` to match — `POSTGRES_DSN`
      defaults to `curriculum_dev` (`src/curriculum_agent/config.py`) and is
      not derived from `POSTGRES_PASSWORD`, so a `.env` that sets only one of
      them starts a stack whose app cannot connect to its own database.
   4. Restart the API so it picks up the new `POSTGRES_DSN`.

4. **Start the stack:**

   ```powershell
   .\scripts\start-demo.ps1
   ```

5. **Confirm the bind is loopback:**

   ```powershell
   netstat -ano | Select-String ":8000"
   ```

   It must read `127.0.0.1:8000`. If it reads `0.0.0.0:8000`, stop — the machine
   is reachable without Access.

## Tunnel and Access

1. Install `cloudflared` and log in:

   ```bash
   cloudflared tunnel login
   ```

2. Start the tunnel:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

   It prints a `*.trycloudflare.com` hostname. **That hostname is public until
   Access is applied.** Treat the next step as part of starting the tunnel, not
   as something to do later.

3. In the Cloudflare Zero Trust dashboard, add a self-hosted Access application
   for that hostname with a policy of **Allow / Emails / the invited addresses**.

4. Verify from a browser signed in to an address that is *not* on the list. You
   must be stopped. If you reach the app, the policy is wrong — take the tunnel
   down before doing anything else.

## During the demo

Watch for these two, which the setup cannot prevent:

- **Slow progress on stakeholder needs.** The classify call goes out over the
  tunnel as an SSE stream that sends per-item events; if progress arrives in
  one burst at the end instead of incrementally, the anti-buffering headers
  are not reaching the client through cloudflared. The run still completes
  correctly either way.
- **Someone deleting another person's program.** There is no ownership check.
  Restore from the backup if it happens.

## After the demo

1. Stop the tunnel (Ctrl-C) — this is what actually revokes access.
2. Stop the app:

   ```powershell
   .\scripts\stop-dev.ps1
   ```

   `stop-dev.ps1` runs `stop-backend.ps1` then `stop-services.ps1`, in that
   order — the API has to let go of the database first. Add `-KeepServices` to
   stop only the API.

   The backend stop finds the process tree by command line *and by parentage*:
   `uv run python -m curriculum_agent.api` is three processes, and under reload
   a fourth — a `multiprocessing` worker whose command line names neither this
   project nor uvicorn. Stopping by name alone left that worker holding port
   8000 while /health went on answering 200. If the port is still held
   afterwards, the script asks /health once more: an answer means an orphaned
   worker of ours and it is stopped, anything else is a process outside this
   project and is reported, never killed.

   Add `-KeepServices` to stop only the API and leave postgres/minio up, which
   is what you want when restarting after a code change.

3. **If you need to confirm by hand:**

   ```powershell
   Get-NetTCPConnection -LocalPort 8000 -State Listen
   ```

4. Remove the Access application if the hostname will not be reused.
5. Keep the backup file until the exported results have been checked.

## Demo package for a customer (แพ็ก demo ให้ลูกค้า)

A self-contained zip the customer runs on their own Windows PC with Docker
Desktop. No tunnel, no Cloudflare: the app listens on `127.0.0.1:8765` only.
It is unrelated to the tunnelled `start-demo.ps1` setup above.

### Build

1. Create dedicated, spending-limited API keys for this demo (an OpenRouter key
   and an OpenTyphoon key, with a low credit cap) and put them in `.env.demo`
   at the repo root. The file is gitignored; never reuse the keys from `.env`.
2. Make sure Docker Desktop is running and the dev `ca-postgres` container is up
   (its data is what ships as the seed).
3. Run `.\scripts\build-demo-package.ps1`. A cold image build takes several
   minutes and prints nothing until it ends. It prints the zip path, size, the
   number of programs in the seed, and the image tag
   `curriculum-demo-app:<YYYYMMDD-HHMM>`.

Output: `dist\demo-package\curriculum-demo-<version>.zip` (about 1 GB).

### What the zip contains

`curriculum-demo-<version>\` holding `images.tar` (the app image and
`postgres:16.15-alpine`), `docker-compose.yml`, `.env` (the demo keys and the
compose project name), `seed\01-seed.sql.gz` (a dump of the dev database),
`start`/`stop`/`reset` in `.cmd` and `.ps1` form, and `README-TH.txt` for the
customer. The customer unzips anywhere (Thai and space-containing paths work),
double-clicks `start.cmd`, and the browser opens `http://127.0.0.1:8765/`.
`start` loads `images.tar` only when the app image is missing, so later starts
are fast and data survives `stop`. `reset` asks for `y`, then wipes the data
volume and restores the seed.

### Verified

Build 20261020-2236 (987 MB), clean install: fresh start loads the images and
shows the seeded programs; one `plo_review` run succeeded against the real API
(provider exercised: OpenRouter); stop/start keeps the data and skips
`docker load`; a busy port 8765 gives a Thai message and exit 1 without starting
containers; Docker not running gives a Thai message and exit 1 within a second;
reset removes the review and restores the seed; the port listens on `127.0.0.1`
only.

Build 20261020-2302 (987 MB, after the final-review fixes): extracted with
Expand-Archive into a Thai, space-containing path and started; `GET /` served
the built UI shell (`<div id="root">`) and `/programs/` listed the same 3
programs; one `need_combination` run on `program-2-run-1` succeeded with 11
written Needs (provider exercised: OpenTyphoon, the second shipped key);
`start.cmd` with `start.ps1` missing printed the "extract the zip first"
message and exited 1.

### Handing over

Tell the customer to right-click the zip and choose Extract All first, then run
`start.cmd` from the extracted folder. Running it from inside the zip fails
(`start.cmd` then prints an English reminder). The build deletes its unzipped
staging folder when the zip is done, so only the zip remains. Each build also
leaves an image behind: delete old zips and old app images with
`docker image rm curriculum-demo-app:<old-version>`.

### After the demo

Revoke both demo keys at their providers. The keys sit in plain text in the
`.env` inside every zip handed out, so treat each zip as a secret until then.
Delete old zips from `dist\demo-package\`.

## Known gaps

Recorded so they are not mistaken for oversights. Closing them is separate work.

- GET routes (except `GET …/evidence/classify-stream`, which runs the classifier) carry no `require_api_key`, so all data is readable by anyone past Access. Write routes all carry it.
- Any authorised user can delete any program.
