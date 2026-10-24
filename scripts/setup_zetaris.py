"""One-time setup: create the papers table in our paper store and register it in Zetaris.

    docker compose up -d                 # start the paper store (litagent-db)
    python scripts/setup_zetaris.py      # safe to run again

Needs ZETARIS_* and PAPERS_DB_* in .env (see .env.example). Ends with a round trip: writes two test
papers to the store, reads them back through Zetaris SQL, checks they match, then deletes them.
To undo: run `DROP DATASOURCE litagent_db` in Zetaris's SQL Editor, then, from THIS repo's root only,
`docker compose down` (add `-v` to also delete the stored papers). Never run `down -v` in the Zetaris
bundle folder: there it deletes Zetaris's metastore, keys and data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from litagent.integrations.zetaris import (  # noqa: E402
    DATASOURCE, TABLE, PaperDB, ZetarisRestClient, row_to_paper, select_papers_sql,
)
from litagent.schemas import Paper  # noqa: E402
from litagent.trace import mask  # noqa: E402

CHECK_RUN_ID = "setup-check"


def main() -> int:
    try:
        db, client = PaperDB(), ZetarisRestClient()
        jdbc_url = os.environ["PAPERS_DB_JDBC_URL"]

        db.create_table()
        print(f"1. Table '{TABLE}' exists in the paper store")

        names = [row[0].lower() for row in client.run_sql("SHOW DATASOURCES")]
        if DATASOURCE in names:
            print(f"2. Data source '{DATASOURCE}' already registered in Zetaris")
        else:
            u = urlparse(os.environ["PAPERS_DB_URL"])
            client.run_sql(
                f'CREATE DATASOURCE {DATASOURCE} DESCRIBE BY "Literature review agent paper store" OPTIONS ('
                f'jdbcdriver "org.postgresql.Driver", jdbcurl "{jdbc_url}", '
                f'username "{unquote(u.username or "")}", password "{unquote(u.password or "")}", fetchsize "1000")'
            )
            print(f"2. Registered data source '{DATASOURCE}' in Zetaris ({jdbc_url})")

        tables = [row[0].lower() for row in client.run_sql(f"SHOW DATASOURCE TABLES {DATASOURCE}")]
        if TABLE in tables:
            print(f"3. Table '{TABLE}' already registered in '{DATASOURCE}'")
        else:
            client.run_sql(f'REGISTER DATASOURCE TABLE "{TABLE}" FROM {DATASOURCE}')
            print(f"3. Registered table '{TABLE}' in '{DATASOURCE}'")

        papers = [
            Paper(id="CHECK1", title="Setup check: it's working", abstract="A 'quoted' abstract.", year=2026,
                  authors=["A. O'Neil"], citation_count=3, is_review=True, is_open_access=True, source="setup"),
            Paper(id="CHECK2", title="Setup check with empty fields", source="setup"),
        ]
        db.replace_run(CHECK_RUN_ID, papers)
        try:
            back = [row_to_paper(r) for r in client.run_sql(select_papers_sql(CHECK_RUN_ID))]
        finally:
            db.delete_run(CHECK_RUN_ID)
        if back != papers:
            print(f"4. Round trip FAILED: wrote {len(papers)} papers, read back {back}", file=sys.stderr)
            return 1
        print(f"4. Round trip OK: wrote {len(papers)} papers, read them back through Zetaris "
              f"({DATASOURCE}.{TABLE}), deleted them")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {mask(str(e))[:500]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
