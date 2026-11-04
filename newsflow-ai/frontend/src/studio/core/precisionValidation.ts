import type {Item} from '../contracts';

export function timingIssue(duration:number,count:number,allowed:number[]):string {
  if(!Number.isInteger(duration)||duration<15||duration>60)return '영상 길이는 15~60초의 정수로 입력하세요.';
  if(!Number.isInteger(count)||count<2||count>12)return '장면 수는 2~12개로 입력하세요.';
  const seconds=allowed.filter(n=>Number.isInteger(n)&&n>=3&&n<=15);
  if(!seconds.length)return '영상 모델의 지원 길이를 확인하세요.';
  let sums=new Set([0]);
  for(let i=0;i<count;i++)sums=new Set([...sums].flatMap(sum=>seconds.map(n=>sum+n).filter(n=>n<=duration)));
  return sums.has(duration)?'':`이 모델에서는 ${duration}초를 ${count}장면으로 만들 수 없습니다. 길이 또는 장면 수를 바꾸세요.`;
}

export const basicSceneFields:Record<string,string>={description:'장면 설명',location:'장소',pose:'행동·자세',emotion:'표정·감정'};
export const advancedSceneFields:Record<string,string>={camera:'이미지 구도',props:'소품·위치',continuity:'이어질 요소',caption:'별도 자막',motion:'영상 동작 · 영어',motion_camera:'영상 카메라 · 영어',sound:'환경음'};
export function sceneErrors(scenario:Item,work:Item,allowed:number[]):Record<string,string>{
  const errors:Record<string,string>={},rows:Item[]=scenario.scenes??[];
  if(rows.length!==work.common.scene_count)errors._scenes=`장면은 ${work.common.scene_count}개여야 합니다.`;
  const required=new Set(['description','location','pose','emotion','camera','motion','motion_camera']);
  const limits:Record<string,number>={description:300,location:200,pose:300,emotion:150,camera:120,props:200,continuity:300,caption:20,motion:300,motion_camera:120,sound:100};
  rows.forEach((s,i)=>{
    const prefix=String(s.no);
    if(s.no!==i+1)errors._scenes='장면 순서를 확인하세요.';
    if(!Array.isArray(s.characters)||s.characters.length<1||s.characters.length>4||s.characters.some((id:string)=>!work.cast[id]))errors[`${prefix}.characters`]='등장 캐릭터를 선택하세요.';
    for(const [key,max] of Object.entries(limits)){
      const value=typeof s[key]==='string'?s[key]:'';
      if(required.has(key)&&!value.trim())errors[`${prefix}.${key}`]='내용을 입력하세요.';
      else if(Array.from(value).length>max)errors[`${prefix}.${key}`]=`${max}자 이내로 입력하세요.`;
    }
    for(const key of ['motion','motion_camera'])if(s[key]&&!/^[^가-힣]*[A-Za-z][^가-힣]*$/.test(s[key]))errors[`${prefix}.${key}`]='영상 지시는 영어로 입력하세요.';
    if(!Number.isInteger(s.seconds)||s.seconds<3||s.seconds>15||!allowed.includes(s.seconds))errors[`${prefix}.seconds`]=`지원 길이: ${allowed.filter(n=>n>=3&&n<=15).join(', ')}초`;
  });
  if(rows.reduce((sum,s)=>sum+Number(s.seconds||0),0)!==work.common.duration)errors._total=`장면 길이 합계를 ${work.common.duration}초로 맞추세요.`;
  return errors;
}


// Keep the stored provider response intact; only prepare a separate editable draft.
export function editableScenario(value:unknown,count:number):{scenario:Item;recovered:boolean}|null {
  const source=value&&typeof value==='object'&&!Array.isArray(value)?value as Item:{};
  const rows=Array.isArray(source.scenes)?source.scenes:[];
  if(rows.length>count)return null; // Never silently discard extra provider scenes.
  const textKeys=[...Object.keys(basicSceneFields),...Object.keys(advancedSceneFields)];
  const knownKeys=new Set([...textKeys,'no','characters','seconds','sfx']);
  const validEffects=(effects:unknown)=>Array.isArray(effects)&&effects.every(effect=>effect&&typeof effect==='object'&&!Array.isArray(effect)&&typeof effect.key==='string');
  const scenes=Array.from({length:count},(_,i)=>{
    const raw=rows[i],row=raw&&typeof raw==='object'&&!Array.isArray(raw)?raw:{};
    const fields=Object.fromEntries(textKeys
      .map(key=>[key,typeof row[key]==='string'?row[key]:'']));
    return {...fields,no:i+1,
      characters:Array.isArray(row.characters)&&row.characters.every((id:unknown)=>typeof id==='string')?[...row.characters]:[],
      seconds:typeof row.seconds==='number'?row.seconds:'',
      sfx:validEffects(row.sfx)?structuredClone(row.sfx):[]};
  });
  const scenario={scenes};
  // Omitted optional fields are harmless; warnings describe only missing/invalid editor data.
  const recovered=Object.keys(source).some(key=>key!=='scenes')||rows.length!==count||rows.some((row:Item,i:number)=>!row||typeof row!=='object'||Array.isArray(row)||
    row.no!==i+1||!Array.isArray(row.characters)||row.characters.some((id:unknown)=>typeof id!=='string')||
    typeof row.seconds!=='number'||[...Object.keys(basicSceneFields),'camera','motion','motion_camera'].some(key=>typeof row[key]!=='string')||
    Object.keys(row).some(key=>!knownKeys.has(key))||textKeys.some(key=>row[key]!==undefined&&typeof row[key]!=='string')||
    (row.sfx!==undefined&&!validEffects(row.sfx)));
  return {scenario,recovered};
}
