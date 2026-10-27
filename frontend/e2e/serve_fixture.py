"""Ephemeral sample API for browser regression tests; never writes real reviewer labels."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import uvicorn
from litagent import api
from litagent.cluster_preview import run_cluster_map
from litagent.config import Effort, Settings
from litagent.schemas import Paper

# Six papers are too few for the default role sizes (main 5-10, foundation 3+, side 3+); these keep all three roles
# and a legal side-to-side move on the stored sample similarity.
settings = Settings(sample_mode=True, logs_dir=os.environ['LITAGENT_QA_LOGS'], gap_similarity_max=1.0,
                    main_cluster_min_size=2, main_cluster_max_size=3, foundation_min_size=1, side_min_size=1,
                    side_similarity_threshold=0.58)
papers = [Paper.model_validate(p) for p in json.loads((ROOT/'data/sample/low_resource_languages_llm.json').read_text())[:6]]
run_cluster_map(papers, '样例测试：如何适配低资源语言？', Effort.NORMAL, settings, 'qa-root')
if os.environ.get('LITAGENT_QA_PAUSE_FEEDBACK') == '1':
    from litagent.agents import grader
    from litagent.integrations.llm import LLMError
    from litagent.trace import current_trace

    original_grade = grader.grade

    def pause_feedback_check(stage, *args, **kwargs):
        trace = current_trace()
        if stage == 'clusters' and trace and any(e['action'] == 'graph feedback' for e in trace.events):
            raise LLMError('Checking service: openrouter_key_missing')
        return original_grade(stage, *args, **kwargs)

    grader.grade = pause_feedback_check
api.app.dependency_overrides[api.get_settings] = lambda: settings
uvicorn.run(api.app, host='127.0.0.1', port=int(os.environ['LITAGENT_QA_PORT']), log_level='warning')
