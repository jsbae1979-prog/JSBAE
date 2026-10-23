from pathlib import Path
import json,sys
from playwright.sync_api import sync_playwright
phase=sys.argv[1]
root=Path('/tmp/newsflow-premium-live')/phase;root.mkdir(parents=True,exist_ok=True)
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 ctx=b.new_context(reduced_motion='reduce',locale='ko-KR')
 external=[]
 def guard(route):
  if route.request.url.startswith('http://127.0.0.1:47943/'):
   route.continue_()
  else:
   external.append(route.request.url);route.abort()
 ctx.route('**/*',guard)
 page=ctx.new_page()
 for w,h in [(1366,768),(1920,1080),(390,844)]:
  page.set_viewport_size({'width':w,'height':h})
  for name,url in [('home','/'),('create','/create'),('settings','/simple-settings'),('library','/videos'),('editor','/ai?draft_id=1'),('publish','/?video=1&publish_platform=unified#publish-workspace')]:
   response=page.goto('http://127.0.0.1:47943'+url);page.wait_for_load_state('networkidle')
   if name=='editor':
    v=page.locator('.editor-preview video')
    if v.count():
     v.evaluate('async v=>{v.muted=true;await v.play();v.pause()}')
   metrics=page.evaluate('''()=>{const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';return {overflow:document.documentElement.scrollWidth>innerWidth,small_text:[...document.querySelectorAll('a,p,label,small,strong,summary,button,select,span')].filter(e=>visible(e)&&e.textContent.trim()&&e.children.length===0&&parseFloat(getComputedStyle(e).fontSize)<12).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.trim().slice(0,65),px:getComputedStyle(e).fontSize})),buttons:[...document.querySelectorAll('button,a.button')].filter(visible).map(e=>({label:e.textContent.trim().slice(0,40),height:e.getBoundingClientRect().height})),font:getComputedStyle(document.body).fontFamily}}''')
   results.append({'page':name,'viewport':f'{w}x{h}','http':response.status,**metrics})
   if w==1366 or name in ('home','settings'):
    if name=='publish':page.locator('#publish-workspace').evaluate('e=>e.scrollIntoView({behavior:"instant"})')
    page.screenshot(path=str(root/f'{name}-{w}.png'))
 assert not external
 (root/'audit.json').write_text(json.dumps({'results':results,'external_browser_requests':len(external)},ensure_ascii=False,indent=2))
 b.close()
