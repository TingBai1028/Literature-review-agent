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


def test_a_verdict_alone_is_a_valid_review_and_attached_quotes_must_be_exact(client):
    c,root,cfg,_,_=client
    item=c.get('/cluster/root/review').json()['output']['items'][0]
    path=path_for(cfg,'cluster-map','root');before=path.read_bytes()
    url=f"/cluster/root/review/{item['id']}"
    body={'expected_version_token':root.version_token,'verdict':'supported'}
    # No reviewer, reason or quotes needed: judging should be quick.
    response=c.post(url,json=body)
    assert response.status_code==200,response.json()
    result=response.json()['output']
    assert result['annotation']['provenance']=='human' and result['annotation']['source']=='user_submission'
    assert result['annotation']['reviewer']=='' and result['annotation']['rationale']==''
    assert result['summary']['reviewed']==1 and result['summary']['semantic_accuracy'] is None
    assert path.read_bytes()==before
    # A quote that is attached must still be exact text of that paper; the version must match.
    assert c.post(url,json={**body,'evidence':[{'paper_id':'M','quote':'invented quote outside supplied source'}]}).status_code==422
    assert c.post(url,json={**body,'expected_version_token':'0'*32}).status_code==409
    one=[{'paper_id':item['papers'][0]['id'],'quote':item['papers'][0]['source_text'][:12]}]
    assert c.post(url,json={**body,'verdict':'unsupported','rationale':'Wrong task.','evidence':one}).status_code==200
    stored=json.loads(path_for(cfg,'finding-review','root').read_text())
    assert len(stored['history'])==1 and stored['records'][item['id']]['rationale']=='Wrong task.'


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


def test_submitting_a_judgement_rewrites_that_finding_as_a_new_version(client, model):
    from litagent.schemas import GapDrafts
    c,root,cfg,_,_=client
    # Graph 1 first, so the review list holds a connection as well as the gap candidate.
    analyzed=c.post('/cluster/root/analyze',json={'expected_version_token':root.version_token,'request_id':'a'*32,
                                                   'stages':['connections']}).json()['output']
    run,token=analyzed['run_id'],analyzed['version_token']
    items=c.get(f'/cluster/{run}/review').json()['output']['items']
    gap=next(i for i in items if i['kind']=='gap')
    other=next(i for i in items if i['kind']=='connection')
    model['calls'].clear()
    # Another finding's judgement must survive the new version.
    assert c.post(f"/cluster/{run}/review/{other['id']}",json={'expected_version_token':token,'verdict':'uncertain'}).status_code==200
    body={'expected_version_token':token,'verdict':'unsupported','rationale':'The two papers study different tasks.'}
    assert c.post(f"/cluster/{run}/review/{gap['id']}",json=body).status_code==200
    out=c.post(f"/cluster/{run}/review/{gap['id']}/regenerate",json={'expected_version_token':token,'run_id':'child-1'})
    assert out.status_code==200,out.json()
    result=out.json()['output']
    assert result['map']['run_id']=='child-1' and result['map']['parent_run_id']==run
    assert result['changed'] in {'rewritten','removed','none'}
    # The writer received the reviewer's verdict and reason as its fix.
    [(_,sent)]=[(s,d) for s,d in model['calls'] if s is GapDrafts]
    fix=sent['candidates'][0]['fix']
    assert 'not supported by the sources' in fix and 'The two papers study different tasks.' in fix
    trace=[json.loads(l) for l in path_for(cfg,'trace','child-1','jsonl').read_text().splitlines()]
    assert any(e['agent_name']=='human' and e['action']=='review submitted' for e in trace)
    child=c.get('/cluster/child-1/review').json()['output']['items']
    assert next(i for i in child if i['id']==other['id'])['annotation']['verdict']=='uncertain'
    assert next((i for i in child if i['id']==gap['id']),{'annotation':None})['annotation'] is None
    assert c.get('/cluster/root/versions').json()['output']['active_head']['run_id']=='child-1'


def test_a_plain_supported_judgement_keeps_the_finding_without_a_new_version(client, model):
    c,root,cfg,_,_=client
    item=c.get('/cluster/root/review').json()['output']['items'][0]
    assert c.post(f"/cluster/root/review/{item['id']}",json={'expected_version_token':root.version_token,'verdict':'supported'}).status_code==200
    out=c.post(f"/cluster/root/review/{item['id']}/regenerate",json={'expected_version_token':root.version_token}).json()['output']
    assert out['changed']=='kept' and out['map']['run_id']=='root' and not model['calls']


def test_rewriting_is_refused_in_sample_mode(client, model):
    from dataclasses import replace
    from litagent.cluster_state import VersionError
    from litagent.review_feedback import regenerate
    c,root,cfg,_,_=client
    item=c.get('/cluster/root/review').json()['output']['items'][0]
    c.post(f"/cluster/root/review/{item['id']}",json={'expected_version_token':root.version_token,'verdict':'unsupported'})
    with pytest.raises(VersionError, match="sample mode"):
        regenerate('root', item['id'], root.version_token, replace(cfg, sample_mode=True))
    assert not model['calls']
