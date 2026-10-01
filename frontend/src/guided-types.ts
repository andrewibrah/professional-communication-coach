export const guidedStates=['created','connecting','coach_speaking','listening','reviewing','paused','reconnecting','finished','failed'] as const;
export type GuidedState=typeof guidedStates[number];
export type GuidedAction='replay'|'retry'|'done'|'pause'|'resume'|'mute'|'unmute'|'finish'|'visibility'|'reconnect';
export type GuidedPrompt={id:string;text:string;exercise_type:'repetition';position:number};
export type GuidedFeedback={prompt_id:string;strength:string|null;priority_correction:string|null;corrected_example:string|null;decision:'retry'|'next'|'simplify'|'finish'|'clarify';evidence_basis:'transcript'|'uncertain';evidence_quote:string|null;spoken_feedback:string};
export type GuidedTurn={id:string;prompt_id:string;provider_item_id:string;attempt:number;transcript:string;feedback:GuidedFeedback;prompt_visible:boolean;created_at:string};
export type GuidedRecap={practiced_exercises:number;completed_attempts:number;focus:string;next_practice:string};
export type GuidedSession={id:string;scenario_id:string;goal:string;created_at:string;expires_at:string;state:GuidedState;revision:number;prompt_visible:boolean;muted:boolean;max_retries:number;prompts:GuidedPrompt[];prompt_index:number;attempts_on_prompt:number;turns:GuidedTurn[];recap:GuidedRecap|null;status_message:string};
export type GuidedSetup={scenario_id:string;goal:string;context:string;prompt_visible:boolean};
const invalid=()=>new Error('Invalid guided response. Please reload your guided history.');
function record(value:unknown,keys:string[]):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value))throw invalid();const r=value as Record<string,unknown>;if(Object.keys(r).some(k=>!keys.includes(k))||keys.some(k=>!(k in r)))throw invalid();return r;}
const characters=(s:string)=>Array.from(s).length;
function text(v:unknown,max:number,min=0):string{if(typeof v!=='string')throw invalid();const length=characters(v);if(length<min||length>max||v.includes('\u0000'))throw invalid();return v;}
function id(v:unknown):string{const s=text(v,36,36);if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(s))throw invalid();return s;}
function count(v:unknown,max=10000):number{if(typeof v!=='number'||!Number.isInteger(v)||v<0||v>max)throw invalid();return v;}
function bool(v:unknown):boolean{if(typeof v!=='boolean')throw invalid();return v;}
function date(v:unknown):string{
 const s=text(v,64),m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(s);
 if(!m)throw invalid();
 const [year,month,day,hour,minute,second]=m.slice(1,7).map(Number);
 const days=[31,year%4===0&&(year%100!==0||year%400===0)?29:28,31,30,31,30,31,31,30,31,30,31];
 if(year<1||month<1||month>12||day<1||day>days[month-1]||hour>23||minute>59||second>59||!Number.isFinite(Date.parse(s)))throw invalid();
 return s;
}
// Preserve backend microsecond precision when checking the lifetime boundary.
function micros(s:string):bigint{const m=/^(.*?)(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(s)!;return BigInt(Date.parse(m[1]+m[3]))*1000n+BigInt((m[2]??'').padEnd(6,'0'));}
function one<T extends string>(v:unknown,values:readonly T[]):T{if(typeof v!=='string'||!values.includes(v as T))throw invalid();return v as T;}
function nullable(v:unknown):string|null{return v===null?null:text(v,400,1);}
function list<T>(v:unknown,max:number,parse:(v:unknown)=>T):T[]{if(!Array.isArray(v)||v.length>max)throw invalid();return v.map(parse);}
function prompt(v:unknown):GuidedPrompt{const r=record(v,['id','text','exercise_type','position']);return {id:id(r.id),text:text(r.text,240,1),exercise_type:one(r.exercise_type,['repetition']),position:count(r.position,2)};}
const audioClaims=/\b(pronunc\w*|enunciat\w*|prosody|intonation|pitch|volume|pacing|pace|accent|cadence|rhythm|loud\w*|softly|voice|audio|speaking speed|vocal|sounded|sound clear|slow down|slowly|slower|speak faster|vocal emphasis)\b/i;
const sentenceCount=(s:string)=>(s.match(/[.!?]+(?:\s|$)/g)??[]).length;
function feedback(v:unknown):GuidedFeedback{
 const r=record(v,['prompt_id','strength','priority_correction','corrected_example','decision','evidence_basis','evidence_quote','spoken_feedback']);
 const f:GuidedFeedback={prompt_id:id(r.prompt_id),strength:nullable(r.strength),priority_correction:nullable(r.priority_correction),corrected_example:nullable(r.corrected_example),decision:one(r.decision,['retry','next','simplify','finish','clarify']),evidence_basis:one(r.evidence_basis,['transcript','uncertain']),evidence_quote:nullable(r.evidence_quote),spoken_feedback:text(r.spoken_feedback,400,1)};
 const fields=[f.strength,f.priority_correction,f.corrected_example,f.spoken_feedback];
 if(fields.reduce((n,s)=>n+(s===null?0:characters(s)),0)>400||fields.some(s=>s!==null&&audioClaims.test(s))||sentenceCount(f.spoken_feedback)>3||(f.priority_correction!==null&&sentenceCount(f.priority_correction)>1))throw invalid();
 if((f.strength!==null||f.priority_correction!==null)&&f.evidence_quote===null)throw invalid();
 // Uncertain clarification is never persisted as a scored/completed turn.
 if(f.evidence_basis!=='transcript'||f.decision==='clarify')throw invalid();
 return f;
}
function turn(v:unknown):GuidedTurn{
 const r=record(v,['id','prompt_id','provider_item_id','attempt','transcript','feedback','prompt_visible','created_at']);
 const t:GuidedTurn={id:id(r.id),prompt_id:id(r.prompt_id),provider_item_id:text(r.provider_item_id,200,1),attempt:count(r.attempt,3),transcript:text(r.transcript,4000,1),feedback:feedback(r.feedback),prompt_visible:bool(r.prompt_visible),created_at:date(r.created_at)};
 if(t.attempt<1||t.feedback.prompt_id!==t.prompt_id||(t.feedback.evidence_quote!==null&&!t.transcript.includes(t.feedback.evidence_quote)))throw invalid();
 return t;
}
function recap(v:unknown):GuidedRecap|null{if(v===null)return null;const r=record(v,['practiced_exercises','completed_attempts','focus','next_practice']);return {practiced_exercises:count(r.practiced_exercises,3),completed_attempts:count(r.completed_attempts,9),focus:text(r.focus,400,1),next_practice:text(r.next_practice,400,1)};}
export function parseGuidedSession(v:unknown):GuidedSession{
 const r=record(v,['id','scenario_id','goal','created_at','expires_at','state','revision','prompt_visible','muted','max_retries','prompts','prompt_index','attempts_on_prompt','turns','recap','status_message']);
 const s:GuidedSession={id:id(r.id),scenario_id:one(r.scenario_id,['introduction','technical-interview','help-desk','cybersecurity','sales','escalation']),goal:text(r.goal,1000,1),created_at:date(r.created_at),expires_at:date(r.expires_at),state:one(r.state,guidedStates),revision:count(r.revision,2147483647),prompt_visible:bool(r.prompt_visible),muted:bool(r.muted),max_retries:count(r.max_retries,2),prompts:list(r.prompts,3,prompt),prompt_index:count(r.prompt_index,2),attempts_on_prompt:count(r.attempts_on_prompt,3),turns:list(r.turns,9,turn),recap:recap(r.recap),status_message:text(r.status_message,400)};
 const duration=micros(s.expires_at)-micros(s.created_at);
 if(duration<=0n||duration>300000000n)throw invalid();
 if(s.prompts.length===0){if(!['created','failed','finished'].includes(s.state)||s.prompt_index!==0||s.attempts_on_prompt!==0||s.turns.length)throw invalid();}
 else if(s.prompts.length!==3||s.prompt_index>=s.prompts.length)throw invalid();
 if(new Set(s.prompts.map(p=>p.id)).size!==s.prompts.length||s.prompts.some((p,i)=>p.position!==i)||new Set(s.turns.map(t=>t.id)).size!==s.turns.length||new Set(s.turns.map(t=>t.provider_item_id)).size!==s.turns.length)throw invalid();
 const counts=new Map(s.prompts.map(p=>[p.id,0]));
 for(const t of s.turns){const previous=counts.get(t.prompt_id);if(previous===undefined||t.attempt!==previous+1||t.attempt>s.max_retries+1)throw invalid();counts.set(t.prompt_id,previous+1);}
 if(s.prompts.length&&counts.get(s.prompts[s.prompt_index].id)!==s.attempts_on_prompt)throw invalid();
 if(s.recap&&(s.recap.completed_attempts!==s.turns.length||s.recap.practiced_exercises!==new Set(s.turns.map(t=>t.prompt_id)).size))throw invalid();
 return s;
}
export function parseGuidedList(v:unknown):GuidedSession[]{const r=record(v,['sessions']);return list(r.sessions,1000,parseGuidedSession);}
export function parseGuidedConnection(v:unknown):{sdp:string;session:GuidedSession}{
 const r=record(v,['sdp','session']),sdp=text(r.sdp,24000,1),lines=sdp.split(/\r\n|\n|\r/),media=lines.filter(line=>line.startsWith('m=')).map(line=>line.trim().split(/\s+/));
 if(lines[0]!=='v=0'||media.length!==1||media[0].length<4||media[0][0]!=='m=audio'||!/^\d+$/.test(media[0][1])||Number(media[0][1])<1||Number(media[0][1])>65535||/SCTP/i.test(media[0][2])||lines.some(line=>/^a=sctp/i.test(line)))throw invalid();
 return {sdp,session:parseGuidedSession(r.session)};
}
export const isGuidedEnded=(s:GuidedSession)=>s.state==='finished'||s.state==='failed';
export function parseGuidedAvailability(value:unknown):{guided_voice_available:boolean;guided_max_seconds?:number;guided_unavailable_reason?:string}{if(!value||typeof value!=='object'||Array.isArray(value))throw invalid();const r=value as Record<string,unknown>;const result:{guided_voice_available:boolean;guided_max_seconds?:number;guided_unavailable_reason?:string}={guided_voice_available:r.guided_voice_available===undefined?false:bool(r.guided_voice_available)};if(r.guided_max_seconds!==undefined){result.guided_max_seconds=count(r.guided_max_seconds,300);if(result.guided_max_seconds<1)throw invalid();}if(r.guided_unavailable_reason!==undefined){const reason=text(r.guided_unavailable_reason,500);if(/[\x00-\x1f<>]|https?:|sk-[a-zA-Z0-9]|Bearer\s/i.test(reason))throw invalid();result.guided_unavailable_reason=reason;}return result;}
