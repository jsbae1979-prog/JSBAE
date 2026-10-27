import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
out=Path('/tmp/newsflow-ui-final-frozen-browser')
checks=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 for width,height in [(1366,768),(1920,1080),(390,844)]:
  page=b.new_page(viewport={'width':width,'height':height},locale='ko-KR')
  page.route('**/*',lambda route:route.continue_() if route.request.url.startswith('http://127.0.0.1:8893/') else route.abort())
  page.goto('http://127.0.0.1:8893/ai?draft_id=4')
  expect(page.locator('.demo-banner')).to_be_visible()
  page.get_by_role('button',name='장면 2',exact=True).click()
  field=page.locator('[data-topic-scene]:visible')
  expect(field.locator('[name="caption"]')).to_have_value('반도체')
  assert field.locator('[name="narration"]').get_attribute('readonly') is not None
  controls=field.locator('button').all()
  rects=[c.bounding_box() for c in controls]
  for i,a in enumerate(rects):
   assert a['x']>=0 and a['x']+a['width']<=width+1
   for c in rects[i+1:]:
    overlap_x=min(a['x']+a['width'],c['x']+c['width'])-max(a['x'],c['x'])
    overlap_y=min(a['y']+a['height'],c['y']+c['height'])-max(a['y'],c['y'])
    assert overlap_x<=1 or overlap_y<=1, (width,a,c)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
  page.evaluate('window.scrollTo(0,0)')
  page.wait_for_function('window.scrollY === 0')
  page.screenshot(path=str(out/f'scene-saved-{width}.png'),full_page=True)
  checks.append({'width':width,'height':height,'button_rectangles':rects,'overlap':False,'horizontal_overflow':False,'saved_caption':'반도체','readonly':True})
  page.close()
 b.close()
(out/'scene-layout.json').write_text(json.dumps({'status':'PASS','checks':checks,'scope':'saved synthetic protected scene; no POST'},ensure_ascii=False,indent=2))
print('PASS scene layouts:',len(checks))
