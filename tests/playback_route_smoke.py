import sys,requests
base=sys.argv[1]+'/api/v2/demo-videos/'
for name in ('ldpolyp_clip01.mp4','sun_seg_seq01.mp4'):
    full=requests.get(base+name,timeout=30);full.raise_for_status();data=full.content
    assert len(data)==int(full.headers['content-length']) and b'avc1' in data[:10000]
    for value,want in [('bytes=0-31',data[:32]),('bytes=-42',data[-42:]),(f'bytes={len(data)-1}-{len(data)+50}',data[-1:])]:
        r=requests.get(base+name,headers={'Range':value},timeout=30)
        assert r.status_code==206 and r.content==want,(name,value,r.status_code)
    r=requests.get(base+name,headers={'Range':f'bytes={len(data)}-'},timeout=30);assert r.status_code==416
missing=requests.get(base+'unrecorded-playback-qa.mp4',timeout=30);assert missing.status_code==404,missing.status_code
print('Verified complete playback bytes, start/end seeking, oversized ranges and missing media')
