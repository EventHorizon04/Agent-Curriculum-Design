# Demo Runbook

Procedure for exposing the curriculum design agent to a small invited group.
Design rationale: `docs/superpowers/specs/2026-08-12-demo-deployment-design.md`.

## What this setup is and is not

Everyone who gets through Cloudflare Access shares one dataset. There are no user
accounts. Any authorised person can read and delete any program. That is
acceptable for an invited demo and unacceptable for anything wider.

**The API has no authentication of its own.** `API_KEY` stays unset because the
frontend does not send `X-API-Key`; setting it would make every write fail with
401. Cloudflare Access is the only barrier, so three conditions must hold:

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
   `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `OPENROUTER_API_KEY`. Leave
   `API_KEY` unset. `start-demo.ps1` checks `OPENROUTER_API_KEY` is set and
   `API_KEY` is not, but it cannot check `POSTGRES_PASSWORD` /
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

## Known gaps

Recorded so they are not mistaken for oversights. Closing them is separate work.

- GET routes carry no `require_api_key`, so all data is readable by anyone past Access.
- Any authorised user can delete any program.
