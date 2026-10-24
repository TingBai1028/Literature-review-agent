"""Zetaris paper store with Postgres and Zetaris mocked. Live check: scripts/setup_zetaris.py."""

import pytest

from litagent import orchestrator
from litagent.config import Effort, Settings
from litagent.human_review import AutoApproveReviewer
from litagent.integrations import zetaris
from litagent.integrations.zetaris import ZetarisError, ZetarisStore, row_to_paper, select_papers_sql
from litagent.schemas import Paper
from litagent.trace import Trace

PAPERS = [Paper(id="W1", title="First", source="openalex"), Paper(id="W2", title="Second", source="openalex")]
# Rows as the live Zetaris returned them in the setup check: every value text, NULL as None
ROW_FULL = ["W1", "It's a test", "An 'abstract'.", "2024", '["Ann O\'Neil", "Bo"]', "12", "true", "true",
            None, "https://doi.org/10.1/x", "openalex", None]
ROW_EMPTY = ["W2", "Second", None, None, "[]", None, None, "false", None, None, "openalex", None]


class FakeDB:
    def __init__(self, fail=False):
        self.fail = fail
        self.writes = []

    def replace_run(self, run_id, papers):
        if self.fail:
            raise ConnectionError("connection refused")
        self.writes.append((run_id, [p.id for p in papers]))


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.sql = rows or [], fail, []

    def run_sql(self, sql, limit=1000):
        self.sql.append(sql)
        if self.fail:
            raise ZetarisError("Zetaris query timed out after 45 s")
        return self.rows


def real_store(db=None, client=None, run_id="run-1") -> ZetarisStore:
    store = ZetarisStore(sample_mode=True, run_id=run_id)  # avoid real connections, then switch to real mode
    store.sample_mode, store.db, store.client = False, db or FakeDB(), client or FakeClient()
    return store


def test_row_to_paper_converts_text_values():
    p = row_to_paper(ROW_FULL)
    assert (p.year, p.citation_count, p.is_review, p.is_open_access) == (2024, 12, True, True)
    assert p.authors == ["Ann O'Neil", "Bo"] and p.abstract == "An 'abstract'." and p.pdf_url is None


def test_row_to_paper_handles_empty_values():
    p = row_to_paper(ROW_EMPTY)
    assert (p.abstract, p.year, p.citation_count, p.is_review, p.is_open_access) == (None, None, None, None, False)
    assert p.authors == []


def test_select_sql_uses_two_part_name_and_escapes_ids():
    sql = select_papers_sql("run-1", ["W1", "it's"])
    assert "FROM litagent_db.papers WHERE run_id = 'run-1'" in sql  # three-part names fail in Zetaris
    assert "id IN ('W1', 'it''s')" in sql
    assert sql.endswith("ORDER BY rank")


@pytest.mark.parametrize("bad", ["x'; DROP TABLE papers; --", "", "a b"])
def test_unsafe_run_ids_are_rejected(bad):
    with pytest.raises(ZetarisError):
        select_papers_sql(bad)


def test_save_writes_run_and_get_reads_through_zetaris(tmp_path):
    db, client = FakeDB(), FakeClient(rows=[ROW_FULL, ROW_EMPTY])
    store = real_store(db, client)
    with Trace(str(tmp_path)) as trace:
        store.save_papers(PAPERS)
        papers = store.get_papers()
    assert db.writes == [("run-1", ["W1", "W2"])]
    assert [p.id for p in papers] == ["W1", "W2"] and papers[0].year == 2024
    assert "litagent_db.papers" in client.sql[0]
    assert store.fallback_reason is None
    query = [e for e in trace.events if e["action"] == "sql query"][0]
    assert query["decision"] == "2 rows -> 2 papers"


def test_zetaris_read_failure_falls_back_to_memory(tmp_path):
    store = real_store(client=FakeClient(fail=True))
    with Trace(str(tmp_path)) as trace:
        store.save_papers(PAPERS)
        papers = store.get_papers()
    assert papers == PAPERS
    assert "timed out" in store.fallback_reason
    assert any(e["action"] == "fallback" for e in trace.events)


def test_store_write_failure_falls_back_and_skips_zetaris():
    client = FakeClient(rows=[ROW_FULL])
    store = real_store(db=FakeDB(fail=True), client=client)
    store.save_papers(PAPERS)
    assert store.get_papers() == PAPERS
    assert "write failed" in store.fallback_reason and client.sql == []


def test_resaving_replaces_the_previous_attempt():
    store = ZetarisStore(sample_mode=True)
    store.save_papers(PAPERS)
    store.save_papers([PAPERS[1]])
    assert store.get_papers() == [PAPERS[1]]


def test_orchestrator_warns_when_zetaris_fell_back(tmp_path, monkeypatch):
    class FlakyStore(ZetarisStore):
        def get_papers(self, paper_ids=None):
            self.fallback_reason = "Zetaris read failed: timed out"
            return super().get_papers(paper_ids)

    monkeypatch.setattr(orchestrator, "ZetarisStore", FlakyStore)
    settings = Settings()
    settings.sample_mode = True
    settings.logs_dir = str(tmp_path)
    result = orchestrator.run_pipeline("graph neural networks for drug discovery", Effort.NORMAL, AutoApproveReviewer(), settings)
    assert result.status == "done"
    assert any("Zetaris unavailable" in w for w in result.warnings)


def test_missing_paper_store_url_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("PAPERS_DB_URL", raising=False)
    with pytest.raises(ZetarisError, match="PAPERS_DB_URL"):
        zetaris.PaperDB()
