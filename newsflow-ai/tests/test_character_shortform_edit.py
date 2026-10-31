from pathlib import Path
import pytest
import json
from contextlib import nullcontext
import character_shortform_edit as variant
from character_shortform_edit import write_shortform,caption_line
from newsflow.character.schema import CharacterError

def test_shortform_safe_area_large_bold_white_yellow_and_two_lines(tmp_path):
    p=tmp_path/'social.ass';write_shortform(p,[(0,2,['커피 한 잔','부탁했을 뿐인데'])],2)
    s=p.read_text(encoding='utf-8-sig')
    assert 'Noto Sans KR,112' in s and ',7,2,2,100,180,390,1' in s
    assert r'{\c&H00FFFFFF&}커피 한 잔\N{\c&H0000E7FF&}부탁했을 뿐인데' in s
    assert r'\t(0,100,\fscx100\fscy100)' in s

def test_text_cannot_inject_ass_commands_or_new_events():
    s=caption_line([r'{\pos(0,0)}'])
    assert r'\pos' not in s and '｛' in s and '＼' in s

@pytest.mark.parametrize('events',[
 [(2,1,['역순'])],[(0,3,['초과'])],[(0,1,['a']),(.5,2,['겹침'])],[(0,1,['가'*15])],[(0,1,['a','b','c'])]])
def test_invalid_ranges_or_overflow_are_rejected(tmp_path,events):
    with pytest.raises(CharacterError):write_shortform(tmp_path/'x.ass',events,2)

@pytest.fixture
def completed_revision(tmp_path,monkeypatch):
    folder=tmp_path/'profile/character'/('a'*32)
    folder.mkdir(parents=True);work=tmp_path/'work';work.mkdir()
    (folder/'final.mp4').write_bytes(b'old verified completed media')
    (work/'final-social.mp4').write_bytes(b'new verified completed media')
    job={'id':folder.name,'state':'completed','script':{'preserve':'same'},'scenes':[{'receipt':'unchanged'}],
         'output':{'sha256':variant.digest(folder/'final.mp4'),'file':'final.mp4','sfx_added':True}}
    (folder/'jobs.json').write_text(json.dumps(job));(folder/'review.json').write_text(json.dumps({'output':job['output'],'human_review':'old review'}))
    (work/'social.ass').write_text('local captions')
    result={'sourceSha256':job['output']['sha256'],'file':'final.mp4','sha256':variant.digest(work/'final-social.mp4'),
      'media':{'duration':30},'captions_added':True,'caption_style':'shortform'}
    (work/'VARIANT_RESULT.json').write_text(json.dumps(result))
    class Service:
        fail=False
        def __init__(self,*a,**kw):pass
        def lock(self):return nullcontext()
        def read(self,*a):return json.loads((folder/'jobs.json').read_bytes())
        def save(self,value):
            if self.fail:raise OSError('synthetic local commit failure')
            (folder/'jobs.json').write_text(json.dumps(value))
    import newsflow.character.service
    monkeypatch.setattr(newsflow.character.service,'CharacterService',Service)
    monkeypatch.setattr(variant,'private_directory',lambda p:p.mkdir(exist_ok=True))
    return folder,work,job,Service

def test_completed_revision_preserves_previous_media_receipts_and_script(completed_revision):
    folder,work,before,service=completed_revision
    result=variant.publish(folder,work);after=json.loads((folder/'jobs.json').read_bytes())
    assert result['previousFinalPreserved'] and after['script']==before['script'] and after['scenes']==before['scenes']
    assert after['output']['human_quality']=='NOT VERIFIED'
    assert variant.digest(folder/'local-edits/shortform-captions-20261031/previous-final.mp4')==before['output']['sha256']

def test_changed_completed_media_is_not_overwritten(completed_revision):
    folder,work,before,service=completed_revision
    (folder/'final.mp4').write_bytes(b'concurrent changed final')
    with pytest.raises(AssertionError):variant.publish(folder,work)
    assert (folder/'final.mp4').read_bytes()==b'concurrent changed final'
    assert not (folder/'local-edits').exists()

def test_local_commit_failure_restores_old_media_and_metadata(completed_revision):
    folder,work,before,service=completed_revision
    job_bytes=(folder/'jobs.json').read_bytes();review_bytes=(folder/'review.json').read_bytes();service.fail=True
    with pytest.raises(OSError):variant.publish(folder,work)
    assert variant.digest(folder/'final.mp4')==before['output']['sha256']
    assert (folder/'jobs.json').read_bytes()==job_bytes and (folder/'review.json').read_bytes()==review_bytes
