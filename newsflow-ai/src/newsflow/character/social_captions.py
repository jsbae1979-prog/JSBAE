"""Local Korean shorts captions. Code-owned effects; no AI or supplied ASS commands."""
from .editing import _caption, _ass_time, _get


def wrap(text):
    # Break at a space near the centre. Never truncate or split an escape sequence.
    if len(text) <= 12: return text
    spaces = [i for i,c in enumerate(text) if c == ' ' and 3 <= i <= len(text)-3]
    if not spaces: return text
    at=min(spaces,key=lambda i:abs(i-len(text)/2))
    return text[:at] + r'\N' + text[at+1:]


def write(target, story, timeline, presets):
    c=presets['caption'];size=c['size'];total=timeline[-1]['start']+timeline[-1]['seconds']
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1080','PlayResY: 1920','WrapStyle: 0',
           'ScaledBorderAndShadow: yes','','[V4+ Styles]',
           'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding']
    for name,fs,color in [('Hook',size+8,'&H0068E8FF'),('Beat',size,'&H00FFFFFF'),('Payoff',size+8,'&H0068E8FF')]:
        lines.append(f'Style: {name},{c["family"]},{fs},{color},{color},&H0015100B,&H90000000,-1,0,0,0,100,100,0,0,1,{c["outline"]},2,5,90,140,0,1')
    lines+=['','[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    hook=_caption(_get(story,'hook_caption',''));ending=_caption(_get(story,'end_caption',''));events=[]
    first_end=timeline[0]['start']+timeline[0]['seconds']
    hook_end=min(2.6, first_end,total)
    if hook:events.append((0,hook_end,'Hook',hook,330))
    for index,(scene,row) in enumerate(zip(_get(story,'scenes'),timeline)):
        text=_caption(_get(scene,'caption',''))
        if index==0 and text==hook:continue
        start=max(row['start']+.12,hook_end if index==0 and hook else 0)
        end=min(row['start']+row['seconds']-.12,start+3.0,total-2 if ending else total)
        if text and end>start:
            events.append((start,end,'Payoff' if index==len(timeline)-1 else 'Beat',text,1370))
    if ending:events.append((max(0,total-2),total,'Payoff',ending,1370))
    for start,end,style,text,y in events:
        effect=r'{\an5\pos(510,'+str(y)+r')\fad(80,100)\fscx94\fscy94\t(0,120,\fscx100\fscy100)}'
        lines.append(f'Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{effect}{wrap(text)}')
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    return len(events)
