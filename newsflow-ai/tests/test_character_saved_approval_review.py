"""Only an already recorded exact unknown-journal review is reusable."""
from test_api_settings import sessions
from test_character_automation_routes import gui
from test_character_operating_authoring import connected
from test_character_story_unknown_review import old_unknown,snapshot,token,submit,new_episode,review,acknowledgements

def test_previously_reviewed_unknown_is_not_prompted_again_for_a_different_new_episode(connected):
    c=connected;old=old_unknown(c);before=snapshot(c,old)
    first=submit(c,review_token=token(c),review_consent='true')
    assert first.status_code==200 and len(acknowledgements(c))==1
    other=new_episode(c)
    readiness=review(c,other).json()
    assert readiness['ready'] and readiness['review']['token']=='' and readiness['review']['count']==0
    assert submit(c,other).status_code==200
    assert len(c.state.calls)==2 and len(acknowledgements(c))==1 and snapshot(c,old)==before
