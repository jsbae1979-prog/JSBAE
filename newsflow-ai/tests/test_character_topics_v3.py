"""Character-scoped topic persistence using synthetic names and no provider calls."""
import pytest
from newsflow.character.topics import TopicStore, validate_generated
from newsflow.character.schema import CharacterError

FIRST='char_'+'a'*32
SECOND='char_'+'b'*32

def generated(count=5):
    return [{'topic':f'갑작스러운 비 {i}에 잎을 펼친다','category':f'정원{i%5}', 'joke_type':f'반전{i//2}'} for i in range(count)]

def test_generated_topics_count_status_restart_and_character_isolation(tmp_path):
    service=TopicStore(tmp_path)
    result=service.save_generated(FIRST,generated(),5)
    assert len(result)==5 and all(row['status']=='new' for row in result)
    service.update_status(FIRST,result[0]['id'],'scripted',expected_revision=1)
    service.update_status(FIRST,result[1]['id'],'skipped')
    assert TopicStore(tmp_path).list(FIRST)[0]['status']=='scripted'
    assert service.list(SECOND)==[]
    with pytest.raises(CharacterError):service.save_generated(FIRST,generated(),5)
    assert len(service.list(FIRST))==5
    assert len(service.save_generated(SECOND,generated(),5))==5

@pytest.mark.parametrize('count',[0,51,True,1.0])
def test_generated_count_bounds(tmp_path,count):
    with pytest.raises(CharacterError):TopicStore(tmp_path).save_generated(FIRST,generated(),count)

def test_generated_diversity_and_duplicates_rejected():
    duplicate=generated();duplicate[1]['topic']=duplicate[0]['topic']
    with pytest.raises(CharacterError):validate_generated(duplicate,5)
    same_category=[{**r,'category':'같음'} for r in generated()]
    with pytest.raises(CharacterError):validate_generated(same_category,5)
    same_joke=[{**r,'joke_type':'같음'} for r in generated()]
    with pytest.raises(CharacterError):validate_generated(same_joke,5)
    assert len(validate_generated(generated(1),1))==1

def test_manual_topic_dedup_keeps_used_status_and_revision(tmp_path):
    service=TopicStore(tmp_path);first=service.add(FIRST,'비가 온다')
    used=service.update_status(FIRST,first['id'],'produced')
    assert service.add(FIRST,'비가   온다')==used
    with pytest.raises(CharacterError):service.update_status(FIRST,first['id'],'unknown')
    with pytest.raises(CharacterError):service.update_status(FIRST,first['id'],'new',expected_revision=1)
    assert service.list(FIRST)==[used]

def test_csv_import_validates_all_before_write_and_deduplicates(tmp_path):
    service=TopicStore(tmp_path)
    result=service.import_csv(FIRST,'\ufeff번호,카테고리,주제\r\n1,정원,비가 온다\r\n2,정원,비가 온다\r\n3,집,바람이 분다\r\n')
    assert len(result['created'])==2 and result['skipped']==1
    before=service.list(FIRST)
    with pytest.raises(CharacterError):service.import_csv(FIRST,'topic,category\n정상,집\n'+('가'*61)+',집\n')
    assert service.list(FIRST)==before

def test_topic_store_path_traversal_and_secrets_rejected(tmp_path):
    service=TopicStore(tmp_path)
    with pytest.raises(CharacterError):service.add('../outside','test')
    with pytest.raises(CharacterError):service.add(FIRST,'Bearer private')
    assert service.list(FIRST)==[]
