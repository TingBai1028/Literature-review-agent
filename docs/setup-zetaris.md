# Set up Zetaris locally (Apple Silicon Mac)

Zetaris is our shared paper data layer: the Retriever saves papers to it and the later agents read them back (`litagent/integrations/zetaris.py`). This guide gets a local Zetaris running in Docker and connects the repo to it. It follows the official [Zetaris getting-started guides](https://github.com/zetaris/getting-started) and was tested on a MacBook Air M2 with 16 GB.

Steps 1 to 4 are a one-time install. On Apple Silicon the first image pull and startup are slow, so allow an hour or more.

You don't need Zetaris for sample mode: `SAMPLE_MODE=true` keeps papers in memory.

## Requirements

- Apple Silicon Mac (M1 or later). Zetaris's images are amd64, so they run under emulation.
- At least 8 GB of memory and 4 CPUs for Docker, and 15 GB of free disk.
- A Zetaris Cloud account (free registration).

## 1. Install and configure Docker Desktop

1. Download Docker Desktop for Mac (Apple Silicon) from https://docs.docker.com/desktop/ and install it.
2. Open Docker Desktop. In Settings → General, turn on "Use Rosetta for x86_64/amd64 emulation on Apple Silicon".
3. In Settings → Resources, set Memory to 8 GB and CPUs to 4. Click Apply & restart.
4. Check it works in Terminal:

   ```bash
   docker version
   docker compose version
   ```

## 2. Download the Zetaris bundle

1. Register at https://cloud.enterprise.zetaris.com/register.
2. Open the Run locally page: https://cloud.enterprise.zetaris.com/dashboard/download
3. Download `zetaris-platform.zip`. Keep the page open; it shows the registry credentials you need in step 3.

If the download isn't available for your account, ask in the Help Zetaris channel on HackOS.

## 3. Unpack, sign in to the registry, and run preflight

```bash
mkdir -p ~/zetaris
mv ~/Downloads/zetaris-platform.zip ~/zetaris/
cd ~/zetaris
unzip zetaris-platform.zip
cd zetaris-platform
docker login zetarishackathon.azurecr.io     # registry credentials from the download page
./preflight.sh                               # fix every failure before continuing
```

## 4. Configure and start Zetaris

This `.env` is the bundle's own file in `~/zetaris/zetaris-platform`, not the repo's `.env`.

1. Open it with `open -e .env`. Set the values below and keep every other value as supplied:

   ```dotenv
   ZETARIS_ADMIN_EMAIL=you@example.com
   ZETARIS_ADMIN_PASSWORD=ChangeMe1!       # 8+ chars: upper, lower, digit, and one of $ @ ! % * ? &
   ZETARIS_ADMIN_ORG=litagent
   ZSPARK_DRIVER_MEM=2g
   ZSPARK_DRIVER_CORES=2
   ZSPARK_MASTER_URL=local[2]
   ZETARIS_API_MAX_HEAP=1g
   UI_PORT=3000
   ALLOWED_ORIGINS=http://localhost:3000
   GUI_URL=http://localhost:3000
   ZETARIS_SEED_TPCH=true
   ```

   Leave `COMPOSE_PROFILES` empty. Pick the password and organisation name before the first start: changing them in `.env` later does not reset the account.

2. Validate, pull and start:

   ```bash
   chmod 600 .env
   docker compose config --quiet    # validates the file; prints nothing if OK
   docker compose pull              # slowest step on Apple Silicon
   docker compose up -d
   docker compose ps --all
   ```

3. Wait until `postgres`, `driver`, `api`, `ui` and `ai-datasteward` are running and `init` and `bootstrap` show `Exited (0)`. Then:

   ```bash
   ./verify.sh                      # should pass all 9 checks
   ```

   If the `ui` checks fail just after bootstrap finishes, wait a minute and run it again.

## 5. Log in and get your connection values

1. Open http://localhost:3000 and sign in with the admin email and password from step 4.
2. In the SQL Editor, run `SELECT 1 AS one;`. Expect one row with the value 1.
3. Management → Organisation: copy the numeric **ID** field (the number, not the name).
4. Management → API Tokens: click **+** at the top right and copy the key. It is shown only once.

## 6. Connect the repo

1. In the repo's `.env` (copy `.env.example` if you don't have one), set:

   ```dotenv
   ZETARIS_REST_URL=http://localhost:8888/api/v1.0
   ZETARIS_ORG_ID=<numeric ID from step 5>
   ZETARIS_API_KEY=<API key from step 5>
   ```

   If you run our app inside Docker, use `http://host.docker.internal:8888/api/v1.0` instead.

2. Check the connection from the repo root:

   ```bash
   python -c "from dotenv import load_dotenv; load_dotenv(); from litagent.integrations.zetaris import ZetarisRestClient; print(ZetarisRestClient().run_sql('SELECT 1 AS one'))"
   ```

| Result | Meaning |
|---|---|
| Rows printed | Connected |
| `Zetaris HTTP 401` | Bad or expired key: create a new one under Management → API Tokens |
| `Cannot reach Zetaris` | Containers aren't up: run `docker compose ps --all` in `~/zetaris/zetaris-platform` |
| `Set ZETARIS_API_KEY` | The repo's `.env` is missing the key, or you aren't running from the repo root |

Never commit either `.env` file.

## Daily use

Run these from `~/zetaris/zetaris-platform`:

```bash
docker compose stop      # stop and free memory; data is kept
docker compose start     # start again
docker compose ps --all  # check status
```

Never run `docker compose down -v`: it deletes the metastore, keys and all data.

## More help

- Official install guide: https://github.com/zetaris/getting-started/blob/main/docs/install/updated_zetaris_installation_guide.md
- Troubleshooting: https://github.com/zetaris/getting-started/blob/main/docs/guides/troubleshooting.md
- Machine too slow or short on memory? Zetaris can also run on AWS: https://github.com/zetaris/getting-started/blob/main/docs/install/choose-install.md
- Help Zetaris channel on HackOS
