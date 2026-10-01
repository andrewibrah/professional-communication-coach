// TEST-ONLY public wire fixtures. No live accounts, provider, or microphone.
import {describe,expect,it} from 'vitest';
import {parseGuidedAvailability,parseGuidedConnection,parseGuidedList,parseGuidedSession,type GuidedSession} from './guided-types';
import {audioSdp,networkDto} from './guided-test-doubles';

type Mutation=(s:GuidedSession)=>void;
const rejects=(mutate:Mutation)=>{const s=networkDto();mutate(s);expect(()=>parseGuidedSession(s)).toThrow('Invalid guided response.');};

describe('bounded public snapshots',()=>{
 it.each<[string,Mutation]>([
  ['empty goal',s=>{s.goal='';}],
  ['goal over 1000',s=>{s.goal='x'.repeat(1001);}],
  ['status over 400',s=>{s.status_message='x'.repeat(401);}],
  ['revision over PostgreSQL integer',s=>{s.revision=2147483648;}],
  ['retries over two',s=>{s.max_retries=3;}],
  ['empty target',s=>{s.prompts[0].text='';}],
  ['target over 240',s=>{s.prompts[0].text='x'.repeat(241);}],
  ['four prompts',s=>{s.prompts.push({...s.prompts[0],id:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3',position:3});}],
  ['one prompt is not a prepared batch',s=>{s.prompts=s.prompts.slice(0,1);}],
  ['two prompts are not a prepared batch',s=>{s.prompts=s.prompts.slice(0,2);}],
  ['position beyond two',s=>{s.prompts[0].position=3;}],
  ['unordered positions',s=>{s.prompts[0].position=1;s.prompts[1].position=0;}],
  ['index equal to prompt count',s=>{s.prompt_index=3;}],
  ['empty active snapshot',s=>{s.prompts=[];s.state='listening';}],
  ['empty snapshot with nonzero index',s=>{s.prompts=[];s.prompt_index=1;}],
  ['empty snapshot with attempts',s=>{s.prompts=[];s.attempts_on_prompt=1;}],
  ['text session identifier',s=>{s.id='session-a';}],
  ['uppercase UUID is not repaired',s=>{s.id=s.id.toUpperCase();}],
  ['compact UUID is not repaired',s=>{s.id=s.id.replaceAll('-','');}],
  ['text prompt identifier',s=>{s.prompts[0].id='prompt-a';}],
  ['unknown scenario',s=>{s.scenario_id='unknown';}],
  ['UUID scenario',s=>{s.scenario_id=s.id;}],
  ['naive session time',s=>{s.created_at='2026-10-01T12:00:00';}],
  ['non ISO session time',s=>{s.created_at='October 1, 2026 12:00:00 GMT';}],
  ['impossible calendar time',s=>{s.created_at='2026-02-30T12:00:00Z';s.expires_at='2026-02-30T12:05:00Z';}],
  ['nonpositive duration',s=>{s.expires_at=s.created_at;}],
  ['backwards duration',s=>{s.expires_at='2026-10-01T11:59:59Z';}],
  ['duration over 300 seconds',s=>{s.expires_at='2026-10-01T12:05:00.001Z';}],
 ])('rejects %s',(_,mutate)=>rejects(mutate));
 it('accepts exact maximum scalar bounds without changing literals',()=>{
  const s=networkDto();s.goal='x'.repeat(1000);s.status_message='x'.repeat(400);s.revision=2147483647;s.prompts.forEach(p=>{p.text='x'.repeat(240);});
  expect(parseGuidedSession(s)).toEqual(s);
 });
 it('measures backend character bounds as Unicode code points, not UTF-16 units',()=>{
  const s=networkDto();s.goal='🙂'.repeat(1000);s.status_message='🙂'.repeat(400);s.prompts.forEach(p=>{p.text='🙂'.repeat(240);});expect(parseGuidedSession(s)).toEqual(s);
 });
 it('enforces lifetime bounds at backend microsecond precision',()=>{
  rejects(s=>{s.expires_at='2026-10-01T12:05:00.000001Z';});
  const s={...networkDto(),expires_at:'2026-10-01T12:00:00.000001Z'};expect(parseGuidedSession(s)).toEqual(s);
 });
 it.each(['created','failed','finished'] as const)('accepts an empty %s snapshot',state=>{
  const s={...networkDto(),state,prompts:[]};expect(parseGuidedSession(s)).toEqual(s);
 });
 it('accepts aware ISO offsets and backend microseconds',()=>{
  const s={...networkDto(),created_at:'2026-10-01T08:00:00.123456-04:00',expires_at:'2026-10-01T12:05:00.123456+00:00'};expect(parseGuidedSession(s)).toEqual(s);
 });
});

const scored=():GuidedSession=>{
 const s=networkDto(),prompt_id=s.prompts[0].id;
 return {...s,state:'coach_speaking',attempts_on_prompt:1,turns:[{id:'cccccccc-cccc-cccc-cccc-ccccccccccc0',prompt_id,provider_item_id:'dddddddd-dddd-dddd-dddd-ddddddddddd0',attempt:1,transcript:'I can help with the next step.',prompt_visible:true,created_at:s.created_at,feedback:{prompt_id,strength:'A clear next step.',priority_correction:null,corrected_example:null,decision:'retry',evidence_basis:'transcript',evidence_quote:'next step',spoken_feedback:'Repeat the sentence.'}}],recap:{practiced_exercises:1,completed_attempts:1,focus:'Practice clear wording.',next_practice:'Repeat the sentence.'}};
};
describe('saved turn evidence and progression',()=>{
 it.each<[string,Mutation]>([
  ['text turn identifier',s=>{s.turns[0].id='turn-a';}],
  ['text feedback identifier',s=>{s.turns[0].feedback.prompt_id='prompt-a';}],
  ['empty provider item',s=>{s.turns[0].provider_item_id='';}],
  ['provider item over 200',s=>{s.turns[0].provider_item_id='x'.repeat(201);}],
  ['attempt zero',s=>{s.turns[0].attempt=0;}],
  ['attempt four',s=>{s.turns[0].attempt=4;}],
  ['attempt above configured retry budget',s=>{s.max_retries=0;s.turns.push({...s.turns[0],id:'cccccccc-cccc-cccc-cccc-ccccccccccc1',provider_item_id:'dddddddd-dddd-dddd-dddd-ddddddddddd1',attempt:2});s.attempts_on_prompt=2;s.recap!.completed_attempts=2;}],
  ['first attempt skips one',s=>{s.turns[0].attempt=2;}],
  ['current prompt attempt count mismatch',s=>{s.attempts_on_prompt=0;}],
  ['attempts belong to previous prompt',s=>{s.prompt_index=1;}],
  ['empty transcript',s=>{s.turns[0].transcript='';}],
  ['transcript over 4000',s=>{s.turns[0].transcript='x'.repeat(4001);s.turns[0].feedback.evidence_quote='x';}],
  ['naive turn time',s=>{s.turns[0].created_at='2026-10-01T12:00:00';}],
  ['duplicate turn identifier',s=>{s.turns.push({...s.turns[0],attempt:2,provider_item_id:'dddddddd-dddd-dddd-dddd-ddddddddddd1'});s.attempts_on_prompt=2;s.recap!.completed_attempts=2;}],
  ['duplicate provider item identifier',s=>{s.turns.push({...s.turns[0],attempt:2,id:'cccccccc-cccc-cccc-cccc-ccccccccccc1'});s.attempts_on_prompt=2;s.recap!.completed_attempts=2;}],
  ['ten saved turns',s=>{s.turns=Array.from({length:10},(_,i)=>({...s.turns[0],id:`cccccccc-cccc-cccc-cccc-ccccccccccc${i}`,provider_item_id:`dddddddd-dddd-dddd-dddd-ddddddddddd${i}`}));}],
  ['feedback prompt mismatch',s=>{s.turns[0].feedback.prompt_id=s.prompts[1].id;}],
  ['missing prompt reference',s=>{s.turns[0].prompt_id='eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee';s.turns[0].feedback.prompt_id=s.turns[0].prompt_id;}],
  ['invented evidence quote',s=>{s.turns[0].feedback.evidence_quote='not in transcript';}],
  ['strength without evidence',s=>{s.turns[0].feedback.evidence_quote=null;}],
  ['correction without evidence',s=>{s.turns[0].feedback.strength=null;s.turns[0].feedback.priority_correction='Use a direct next step.';s.turns[0].feedback.evidence_quote=null;}],
  ['empty spoken feedback',s=>{s.turns[0].feedback.spoken_feedback='';}],
  ['individual feedback over 400',s=>{s.turns[0].feedback.spoken_feedback='x'.repeat(401);}],
  ['empty optional feedback field',s=>{s.turns[0].feedback.strength='';}],
  ['combined feedback over 400',s=>{s.turns[0].feedback.strength='x'.repeat(200);s.turns[0].feedback.spoken_feedback='x'.repeat(201);}],
  ['four spoken sentences',s=>{s.turns[0].feedback.spoken_feedback='One. Two. Three. Four.';}],
  ['multiple corrections',s=>{s.turns[0].feedback.priority_correction='First. Second.';}],
  ['unsupported acoustic claim',s=>{s.turns[0].feedback.strength='Your pronunciation is clear.';}],
  ['uncertain scored attempt',s=>{s.turns[0].feedback={...s.turns[0].feedback,evidence_basis:'uncertain',decision:'clarify',strength:null,evidence_quote:null};}],
  ['confident clarify attempt',s=>{s.turns[0].feedback.decision='clarify';}],
  ['recap exercise count mismatch',s=>{s.recap!.practiced_exercises=2;}],
  ['recap attempt count mismatch',s=>{s.recap!.completed_attempts=2;}],
  ['recap over three exercises',s=>{s.recap!.practiced_exercises=4;}],
  ['recap over nine attempts',s=>{s.recap!.completed_attempts=10;}],
  ['empty recap focus',s=>{s.recap!.focus='';}],
  ['recap next practice over 400',s=>{s.recap!.next_practice='x'.repeat(401);}],
 ])('rejects %s',(_,mutate)=>{const s=scored();mutate(s);expect(()=>parseGuidedSession(s)).toThrow('Invalid guided response.');});
 it('accepts an opaque provider item unchanged, not as a UUID or route identifier',()=>{
  const s=scored();s.turns[0].provider_item_id='provider item/?#'.padEnd(200,'x');expect(parseGuidedSession(s)).toEqual(s);
 });
 it('accepts the complete three-prompt nine-turn budget and preserves the last finished index',()=>{
  const s=scored(),base=s.turns[0];s.state='finished';s.prompt_index=2;s.attempts_on_prompt=3;
  s.turns=s.prompts.flatMap(p=>[1,2,3].map(attempt=>({...base,id:`cccccccc-cccc-cccc-cccc-cccccccccc${p.position}${attempt}`,provider_item_id:`opaque-${p.position}-${attempt}`,prompt_id:p.id,attempt,feedback:{...base.feedback,prompt_id:p.id}})));
  s.recap={...s.recap!,practiced_exercises:3,completed_attempts:9};expect(parseGuidedSession(s)).toEqual(s);
 });
 it('accepts exact transcript and feedback limits with a single configured attempt',()=>{
  const s=scored();s.max_retries=0;s.turns[0].transcript='x'.repeat(4000);s.turns[0].feedback={...s.turns[0].feedback,strength:null,evidence_quote:'x'.repeat(400),spoken_feedback:'x'.repeat(400)};expect(parseGuidedSession(s)).toEqual(s);
 });
 it('accepts exact Unicode transcript, provider item, feedback and recap character limits',()=>{
  const s=scored();s.turns[0].provider_item_id='🙂'.repeat(200);s.turns[0].transcript='🙂'.repeat(4000);s.turns[0].feedback={...s.turns[0].feedback,strength:'🙂'.repeat(100),priority_correction:'🙂'.repeat(100),corrected_example:'🙂'.repeat(100),evidence_quote:'🙂'.repeat(400),spoken_feedback:'🙂'.repeat(100)};s.recap!.focus='🙂'.repeat(400);s.recap!.next_practice='🙂'.repeat(400);expect(parseGuidedSession(s)).toEqual(s);
 });
});

describe('bounded audio-only answer envelope',()=>{
 it.each([
  audioSdp.padEnd(24001,'x'),
  'v=0',
  'v=0evil\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n',
  audioSdp+'m=video 9 UDP/TLS/RTP/SAVPF 96\r\n',
  audioSdp+'m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n',
  audioSdp+audioSdp.split('\r\n')[1]+'\r\n',
  audioSdp.replace('audio 9','audio 0'),
  audioSdp.replace('audio 9','audio 65536'),
  audioSdp.replace('audio 9','audio -1'),
  audioSdp.replace('audio 9','audio nine'),
  audioSdp.replace('UDP/TLS/RTP/SAVPF','UDP/DTLS/SCTP'),
  audioSdp+'a=SCTP-port:5000\r\n',
  'v=0\r\nm=audio 9 RTP\r\n',
 ])('rejects malformed or non-audio SDP %#',sdp=>expect(()=>parseGuidedConnection({sdp,session:networkDto()})).toThrow('Invalid guided response.'));
 it('accepts an exact 24000-character audio answer without rewriting it',()=>{
  const answer={sdp:(audioSdp+'a=x:').padEnd(24000,'x'),session:networkDto()};expect(parseGuidedConnection(answer)).toEqual(answer);
 });
 it('validates every collection entry and every envelope field',()=>{
  expect(()=>parseGuidedList({sessions:[networkDto(),{...networkDto(),goal:''}]})).toThrow('Invalid guided');
  expect(()=>parseGuidedConnection({sdp:audioSdp,session:networkDto(),provider_payload:'private'})).toThrow('Invalid guided');
  expect(()=>parseGuidedConnection({sdp:audioSdp,session:{...networkDto(),provider_session_id:'private'}})).toThrow('Invalid guided');
 });
 it('rejects configuration that could extend the five-minute session limit',()=>{
  expect(()=>parseGuidedAvailability({guided_max_seconds:301})).toThrow('Invalid guided');
 });
});
