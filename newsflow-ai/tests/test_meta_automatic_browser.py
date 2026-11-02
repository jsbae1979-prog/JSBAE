"""Synthetic browser verification; never controls the operating Chrome/profile."""
import pytest
from playwright.sync_api import expect
from test_meta_browser import connected, context
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from newsflow.meta.media import MetaDelivery
from newsflow.meta.graph import MetaGraph

pytestmark=pytest.mark.usefixtures("synthetic_app_isolation")


def test_storage_config_once_no_upload_and_secret_inputs_cleared(app,browser,connected,tmp_path):
    accounts,publisher,ids=connected
    publisher.delivery=MetaDelivery(accounts)
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page()
        page.goto(origin+"/studio/settings?tab=accounts")
        page.get_by_text("Instagram 이미지 자동 업로드 · 최초 연결",exact=True).click()
        page.get_by_label("저장소 API 주소(HTTPS)").fill("https://s3.example.com")
        page.get_by_label("지역",exact=True).fill("us-east-1")
        page.get_by_label("저장 공간 이름(버킷)").fill("synthetic-bucket")
        page.get_by_label("접근 키",exact=True).fill("SYNTHETICACCESS")
        page.get_by_label("비밀 키",exact=True).fill("synthetic-secret-key-only")
        page.get_by_role("button",name="자동 업로드 연결 저장",exact=True).click()
        expect(page.get_by_text("Instagram 이미지 자동 업로드 · 연결 설정됨",exact=True)).to_be_visible()
        expect(page.get_by_label("접근 키",exact=True)).to_have_value("")
        expect(page.get_by_label("비밀 키",exact=True)).to_have_value("")
        assert not publisher.graph.calls
        assert "synthetic-secret-key-only" not in page.content()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path/"automatic-upload-settings.png"))
        ctx.close()


def test_direct_facebook_ready_without_storage_and_upload_only_after_confirmation(app,browser,connected,tmp_path):
    from test_library_visibility import mixed
    accounts,publisher,ids=connected
    mixed(app)
    # Finished synthetic video is sufficient; resolve is injected, no actual upload until confirm.
    publisher.delivery=MetaDelivery(accounts)
    publisher.graph=MetaGraph(transport=lambda *a:pytest.fail("No upload while preparing"))
    publisher.resolve=lambda key:{"path":tmp_path/"unopened.mp4","kind":"video","sha256":"b"*64}
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page()
        page.goto(origin+"/studio/publishing")
        page.locator(".mg-publish-list").get_by_role("button").filter(has_text="합성 뉴스 영상").click()
        panel=page.locator("section").filter(has=page.get_by_role("heading",name="Facebook · Instagram 다중 계정 게시",exact=True)).last
        panel.get_by_role("checkbox",name="Facebook 페이지",exact=True).first.check()
        panel.get_by_role("checkbox",name="선택 계정·콘텐츠·문구와 권리·출처·AI 표시를 확인했습니다.",exact=True).check()
        panel.get_by_role("button",name="대상별 게시 준비 저장",exact=True).click()
        expect(panel.get_by_text("프로그램에서 Meta로 직접 업로드",exact=True)).to_be_visible()
        expect(panel.get_by_role("button",name="전송 승인 · 게시",exact=True)).to_be_enabled()
        expect(panel.get_by_text("고급 · 기존 파일별 주소 사용",exact=True)).to_have_count(0)
        page.on("dialog",lambda dialog:dialog.dismiss())
        panel.get_by_role("button",name="전송 승인 · 게시",exact=True).click()
        assert publisher.list()[0]["state"]=="draft"
        panel.screenshot(path=str(tmp_path/"direct-upload-ready.png"))
        ctx.close()
