"""Decode every video frame and enforce the browser replay format before publishing."""
import re
import shutil
import struct
import subprocess
from pathlib import Path

def validate_replay(path, expected_frames):
    path=Path(path)
    size=path.stat().st_size
    boxes=[]
    with path.open('rb') as stream:
        while stream.tell()<size:
            start=stream.tell()
            header=stream.read(8)
            if len(header)!=8: raise ValueError('Incomplete MP4 box')
            length,kind=struct.unpack('>I4s',header)
            if length==1: length=struct.unpack('>Q',stream.read(8))[0]
            if length==0: length=size-start
            if length<stream.tell()-start or start+length>size: raise ValueError('Invalid MP4 box length')
            boxes.append(kind)
            stream.seek(start+length)
    if not boxes or boxes[0]!=b'ftyp' or boxes.index(b'moov')>boxes.index(b'mdat'):
        raise ValueError('MP4 metadata must precede media for streaming')
    exe=shutil.which('ffmpeg')
    if not exe:
        import imageio_ffmpeg
        exe=imageio_ffmpeg.get_ffmpeg_exe()
    result=subprocess.run([exe,'-nostdin','-hide_banner','-nostats','-xerror','-threads','2','-i',str(path),
        '-map','0:v:0','-an','-fps_mode','passthrough','-progress','pipe:1','-f','null','-'],
        capture_output=True,text=True,errors='replace',check=True)
    stream_line=next((s for s in result.stderr.splitlines() if 'Video:' in s),'')
    counts=re.findall(r'^frame=(\d+)\s*$',result.stdout,re.M)
    if not re.search(r'Video: h264\b',stream_line) or not re.search(r'\byuv420p\b',stream_line):
        raise ValueError('Expected H.264 / 8-bit yuv420p')
    if not counts or int(counts[-1])!=expected_frames or expected_frames<=0:
        raise ValueError(f'Decoded frame count differs from {expected_frames}')
    return {'decoded_frames':expected_frames,'codec':'h264','pixel_format':'yuv420p','faststart':True}
