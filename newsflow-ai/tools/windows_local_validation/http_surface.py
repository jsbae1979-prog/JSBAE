"""Verification HTTP surface. Only one new read endpoint; no new writes."""
import re

LOCAL_POSTS=(r'/ai/drafts/[0-9]+',r'/api/samples/[^/]+/(?:copy|visibility)',r'/image-studio/drafts',r'/image-studio/defaults',r'/image-studio/[^/]+/reuse')

def request_allowed(method,path):
    if method=='GET' and path=='/api/feed-batches':return True
    if method in {'GET','HEAD'}:
        return path=='/' or path.startswith(('/studio/','/static/','/api/studio/','/api/samples','/media/','/video/','/character/','/image-studio/assets/','/favicon')) and not any(w in path for w in ('oauth','connect','callback','/start','/stop','events','stream'))
    return method=='POST' and any(re.fullmatch(p,path) for p in LOCAL_POSTS)
