// TEST-ONLY fixtures and browser doubles. Never import from application code.
import type {GuidedSession} from './guided-types';
import {vi} from 'vitest';
export const dto=():GuidedSession=>({id:'session-a',scenario_id:'help-desk',goal:'Clarity',created_at:new Date().toISOString(),expires_at:new Date(Date.now()+300000).toISOString(),state:'created',revision:0,prompt_visible:true,muted:false,max_retries:2,prompts:[{id:'prompt-a',text:'PRIVATE TARGET',exercise_type:'repetition',position:0}],prompt_index:0,attempts_on_prompt:0,turns:[],recap:null,status_message:'Ready'});
// Canonical public wire fixture; direct view/controller doubles above are not parsed.
export const networkDto=():GuidedSession=>({...dto(),id:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',created_at:'2026-10-01T12:00:00.000Z',expires_at:'2026-10-01T12:05:00.000Z',prompts:[0,1,2].map(position=>({id:`bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb${position}`,text:'PRIVATE TARGET',exercise_type:'repetition',position}))});
export function deferred<T>(){let resolve!:(v:T)=>void;let reject!:(e:unknown)=>void;const promise=new Promise<T>((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
export const audioSdp='v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n';
export function mediaDoubles(){
 const track={enabled:true,stop:vi.fn(),kind:'audio'};
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]} as unknown as MediaStream;
 const audio={srcObject:null,autoplay:false,play:vi.fn().mockResolvedValue(undefined),pause:vi.fn(),remove:vi.fn()} as unknown as HTMLAudioElement;
 class FakePeer extends EventTarget{
  connectionState:RTCPeerConnectionState='new';iceGatheringState:RTCIceGatheringState='complete';localDescription:RTCSessionDescriptionInit|null=null;
  ontrack:((event:RTCTrackEvent)=>void)|null=null;onconnectionstatechange:(()=>void)|null=null;
  addTrack=vi.fn();createDataChannel=vi.fn();close=vi.fn();
  createOffer=vi.fn(async()=>({type:'offer' as const,sdp:audioSdp}));
  setLocalDescription=vi.fn(async(d:RTCSessionDescriptionInit)=>{this.localDescription=d;});
  setRemoteDescription=vi.fn(async()=>{this.ontrack?.({streams:[stream],track} as unknown as RTCTrackEvent);this.connectionState='connected';this.dispatchEvent(new Event('connectionstatechange'));this.onconnectionstatechange?.();});
 }
 const peer=new FakePeer();const getUserMedia=vi.fn().mockResolvedValue(stream);
 return {track,stream,audio,peer,deps:{getUserMedia,createPeer:()=>peer as unknown as RTCPeerConnection,createAudio:()=>audio,tailMs:500,timeoutMs:1000}};
}
