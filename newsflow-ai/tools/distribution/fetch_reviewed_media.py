"""Disposable CI only: download official media archive; extract only pinned tools."""
import argparse,hashlib,io,json,os
from pathlib import Path
import urllib.request
import zipfile

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Windows':raise SystemExit('Disposable Windows CI only')
    if a.output.exists():raise SystemExit('New output required')
    pins={'ffmpeg.exe':'3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec','ffprobe.exe':'f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52'}
    url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    with urllib.request.urlopen(url,timeout=90) as response:
        data=response.read(160*1024*1024+1)
    if len(data)>160*1024*1024:raise SystemExit('Archive limit')
    selected={}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name,digest in pins.items():
            matches=[i for i in z.infolist() if i.filename.endswith('/bin/'+name)]
            if len(matches)!=1 or matches[0].file_size>150*1024*1024:raise SystemExit('Archive member mismatch')
            payload=z.read(matches[0])
            if hashlib.sha256(payload).hexdigest()!=digest:raise SystemExit('Reviewed media changed; do not silently repin')
            selected[name]=payload
    a.output.mkdir(parents=True)
    for name,payload in selected.items():(a.output/name).write_bytes(payload)
    print(json.dumps({'source':url,'archive_sha256':hashlib.sha256(data).hexdigest(),'tools':pins}))
if __name__=='__main__':main()
