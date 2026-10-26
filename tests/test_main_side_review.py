"""Read-only map catalog and genuine user-submitted review records."""

import json

import pytest
from fastapi.testclient import TestClient

from litagent import api
from litagent.cluster_state import load_version, path_for, save_version, set_head
from litagent.finding_review import prepare_review
from tests.test_findings import gap_settings, model  # shared offline model fixture
from tests.test_cluster_regeneration import snapshot


@pytest.fixture
def client(model,tmp_path):
    root,cfg,papers,arrays=snapshot(tmp_path,settings=gap_settings(tmp_path))
    api.app.dependency_overrides[api.get_settings]=lambda:cfg
    try:
        with TestClient(api.app) as browser:
            yield browser,root,cfg,papers,arrays
    finally:
        api.app.dependency_overrides.clear()


def test_review_pack_starts_pending_and_does_not_run_models_or_create_labels(client,model):
    c,root,cfg,_,_=client
    out=c.get('/cluster/root/review').json()['output']
    assert out['summary']['total']>0 and out['summary']['reviewed']==0 and out['summary']['semantic_accuracy'] is None
    assert out['summary']['support_rate'] is None and all(i['annotation'] is None and 'model_assessment' not in i for i in out['items'])
    assert not path_for(cfg,'finding-review','root').exists() and not model['calls']
    revealed=c.get('/cluster/root/review?reveal=true').json()['output']
    assert all('model_assessment' in i for i in revealed['items'])


def test_review_requires_own_quotes_reviewer_reason_and_matching_version(client):
    c,root,cfg,_,_=client
    item=c.get('/cluster/root/review').json()['output']['items'][0]
    path=path_for(cfg,'cluster-map','root');before=path.read_bytes()
    body={'expected_version_token':root.version_token,'verdict':'supported','reviewer':'X','rationale':'Both original sources explicitly support the stated scientific comparison.',
          'evidence':[{'paper_id':p['id'],'quote':p['source_text'][:100]} for p in item['papers']]}
    url=f"/cluster/root/review/{item['id']}"
    assert c.post(url,json={**body,'evidence':body['evidence'][:1]}).status_code==422
    assert c.post(url,json={**body,'reviewer':''}).status_code==422
    assert c.post(url,json={**body,'reviewer':'   '}).status_code==422
    assert c.post(url,json={**body,'expected_version_token':'0'*32}).status_code==409
    assert c.post(url,json={**body,'evidence':[{'paper_id':'M','quote':'invented quote outside supplied source'}]}).status_code==422
    response=c.post(url,json=body)
    assert response.status_code==200,response.json()
    result=response.json()['output']
    assert result['annotation']['provenance']=='human' and result['annotation']['source']=='user_submission'
    assert result['summary']['reviewed']==1 and result['summary']['semantic_accuracy'] is None
    assert path.read_bytes()==before
    assert c.get('/cluster/root/review').json()['output']['items'][0]['annotation']['reviewer']=='X'
    assert c.post(url,json={**body,'verdict':'uncertain','evidence':[]}).status_code==200
    stored=json.loads(path_for(cfg,'finding-review','root').read_text())
    assert len(stored['history'])==1


def test_catalog_sources_and_targeted_alternatives_are_read_only(client):
    c,root,cfg,papers,arrays=client
    data=c.get('/maps').json()['output']['maps']
    assert data[0]['run_id']=='root' and data[0]['active']
    assert c.get('/ui/config').json()['output']['sample_mode'] is False
    metadata=c.get('/cluster/root/papers').json()['output']['papers']
    assert len(metadata)==len(papers) and all('full_text' not in p for p in metadata)
    assert 'full_text' in c.get('/cluster/root/papers?include_full_text=true').json()['output']['papers'][0]
    assert c.get('/cluster/root/papers/A').json()['output']['id']=='A'
    assert c.get('/cluster/root/papers/unknown').status_code==404
    targeted=c.get('/cluster/root/regenerate/candidates?paper_id=A').json()['output']
    assert targeted['candidates'] and all(x['paper_id']=='A' for x in targeted['candidates'])
    assert c.get('/cluster/root/regenerate/candidates?paper_id=unknown').status_code==404
    assert not path_for(cfg,'finding-review','root').exists()


def test_corrupt_manifest_is_not_presented_as_a_working_map(client):
    c,_,cfg,_,_=client
    p=path_for(cfg,'cluster-state','root');data=json.loads(p.read_text());data['checksum']='corrupt';p.write_text(json.dumps(data))
    out=c.get('/maps').json()['output']
    assert out['maps']==[] and out['warnings']
    assert c.get('/cluster/root/review').status_code==409


def test_neighbors_give_each_paper_its_most_similar_papers_once(client):
    c,root,cfg,papers,arrays=client
    pairs=c.get('/cluster/root/neighbors?k=1').json()['output']['pairs']
    assert all(p['source']<p['target'] for p in pairs) and len({(p['source'],p['target']) for p in pairs})==len(pairs)
    ids=[p.id for p in papers]
    for i,pid in enumerate(ids):
        best=max((j for j in range(len(ids)) if j!=i),key=lambda j:arrays.similarity[i,j])
        assert any({p['source'],p['target']}=={pid,ids[best]} for p in pairs)
    assert c.get('/cluster/root/neighbors?k=0').status_code==422
