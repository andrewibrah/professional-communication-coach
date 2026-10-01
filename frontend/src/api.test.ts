import {afterEach,expect,it,vi} from 'vitest';
afterEach(()=>vi.unstubAllGlobals());
const uploadId='12345678-1234-4234-8234-123456789abc';
const key='abcdefab-1234-4234-8234-123456789abc';
const authorization=()=>new Response(JSON.stringify({upload_id:uploadId,expires_at:new Date(Date.now()+300000).toISOString()}));
function relay(beforeLoad?:(xhr:any)=>void){
 const sent:FakeXHR[]=[];
 class FakeXHR {
  status=204;responseText='';timeout=0;upload={onprogress:null as any};headers:Record<string,string>={};method='';url='';body:unknown;
  onload:any;onerror:any;ontimeout:any;onabort:any;
  open(method:string,url:string){this.method=method;this.url=url;}
  setRequestHeader(name:string,value:string){this.headers[name]=value;}
  send(body:unknown){this.body=body;sent.push(this);this.upload.onprogress?.({lengthComputable:true,loaded:2,total:4});queueMicrotask(()=>{beforeLoad?.(this);this.onload();});}
  abort(){this.onabort?.();}
 }
 vi.stubGlobal('XMLHttpRequest',FakeXHR);return sent;
}
it('authorizes metadata, relays raw authenticated bytes, then processes with the same key',async()=>{
 const sent=relay();const result={id:'attempt'};const f=vi.fn(function(this:unknown){expect(this).toBe(globalThis);return Promise.resolve(f.mock.calls.length===1?authorization():new Response(JSON.stringify(result)));});
 const api=new Api(async()=>'token',f);const blob=new Blob(['audio'],{type:'audio/webm'});const progress=vi.fn();
 await expect(api.upload('session / a',blob,40,progress,key)).resolves.toEqual(result);
 expect(f.mock.calls[0]).toEqual(['/api/v1/sessions/session%20%2F%20a/attempt-uploads',expect.objectContaining({method:'POST',body:JSON.stringify({content_type:'audio/webm',size_bytes:5,duration_seconds:40}),headers:expect.objectContaining({Authorization:'Bearer token','Idempotency-Key':key})})]);
 expect(sent).toHaveLength(1);expect(sent[0]).toMatchObject({method:'PUT',url:`/api/v1/sessions/session%20%2F%20a/attempt-uploads/${uploadId}`,body:blob,headers:{Authorization:'Bearer token','Content-Type':'audio/webm'}});
 expect(progress).toHaveBeenCalledWith(50);expect(progress).toHaveBeenLastCalledWith(100);
 expect(f.mock.calls[1]).toEqual(['/api/v1/sessions/session%20%2F%20a/attempts',expect.objectContaining({method:'POST',body:JSON.stringify({upload_id:uploadId}),headers:expect.objectContaining({'Idempotency-Key':key})})]);
});
import {Api} from './api';
it('rejects an owner change between decoded processing JSON and the public upload return',async()=>{
 relay();let owner=1;const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockResolvedValueOnce({ok:true,json:()=>{const data=Promise.resolve({id:'private'});queueMicrotask(()=>queueMicrotask(()=>queueMicrotask(()=>owner++)));return data;}});const api=new Api(async()=>'token',f,()=>owner);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key)).rejects.toThrow('Account changed');
});
it('does not consult the token provider when already cancelled',async()=>{
 const controller=new AbortController();controller.abort();const token=vi.fn(async()=>'token');const api=new Api(token,vi.fn());await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key,controller.signal)).rejects.toThrow('cancelled');expect(token).not.toHaveBeenCalled();
});
it('reauthorizes after a cancelled byte relay rather than reusing its consumed authorization',async()=>{
 const controller=new AbortController();const sent=relay(()=>{if(!controller.signal.aborted)controller.abort();});
 const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockImplementationOnce(()=>Promise.resolve(authorization())).mockResolvedValueOnce(new Response(JSON.stringify({id:'saved'})));const api=new Api(async()=>'token',f);const blob=new Blob(['audio'],{type:'audio/webm'});
 await expect(api.upload('s',blob,40,()=>{},key,controller.signal)).rejects.toThrow('cancelled');
 await expect(api.upload('s',blob,40,()=>{},key)).resolves.toEqual({id:'saved'});expect(sent).toHaveLength(2);expect(f.mock.calls.map(c=>c[0])).toEqual(['/api/v1/sessions/s/attempt-uploads','/api/v1/sessions/s/attempt-uploads','/api/v1/sessions/s/attempts']);
});
it('retains the uploaded receipt when cancelled immediately after the byte acknowledgement',async()=>{
 const sent=relay();const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockResolvedValueOnce(new Response(JSON.stringify({id:'saved'})));const api=new Api(async()=>'token',f);const blob=new Blob(['audio'],{type:'audio/webm'});const controller=new AbortController();
 await expect(api.upload('s',blob,40,p=>{if(p===100)controller.abort();},key,controller.signal)).rejects.toThrow('cancelled');expect(f).toHaveBeenCalledTimes(1);
 await expect(api.upload('s',blob,40,()=>{},key)).resolves.toEqual({id:'saved'});expect(sent).toHaveLength(1);expect(f).toHaveBeenCalledTimes(2);
});
it.each(['token','authorization','json','bytes','processing'])('rejects old-owner work at the %s boundary before the next network request',async boundary=>{
 let owner=1;const sent=relay(()=>{if(boundary==='bytes')owner++;});
 const f=vi.fn().mockImplementationOnce(()=>{if(boundary==='authorization')owner++;if(boundary==='json')return Promise.resolve({ok:true,json:async()=>{owner++;return {upload_id:uploadId,expires_at:new Date(Date.now()+300000).toISOString()};}});return Promise.resolve(authorization());}).mockImplementationOnce(()=>{if(boundary==='processing')owner++;return Promise.resolve(new Response(JSON.stringify({id:'private'})));});
 const api=new Api(async()=>{if(boundary==='token')owner++;return 'token';},f,()=>owner);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key)).rejects.toThrow('Account changed');
 expect(f).toHaveBeenCalledTimes(boundary==='token'?0:boundary==='processing'?2:1);expect(sent).toHaveLength(['bytes','processing'].includes(boundary)?1:0);
});
it.each(['before','token','authorization','json','bytes'])('stops cancellation at the %s boundary',async boundary=>{
 const controller=new AbortController();if(boundary==='before')controller.abort();const sent=relay(()=>{if(boundary==='bytes')controller.abort();});
 const f=vi.fn(()=>{if(boundary==='authorization')controller.abort();if(boundary==='json')return Promise.resolve({ok:true,json:async()=>{controller.abort();return {upload_id:uploadId,expires_at:new Date(Date.now()+300000).toISOString()};}});return Promise.resolve(authorization());});
 const api=new Api(async()=>{if(boundary==='token')controller.abort();return 'token';},f as typeof fetch);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key,controller.signal)).rejects.toThrow('cancelled');expect(f).toHaveBeenCalledTimes(['before','token'].includes(boundary)?0:1);expect(sent).toHaveLength(boundary==='bytes'?1:0);
});
it('never reuses upload receipts across owner generations',async()=>{
 const sent=relay();let owner=1;const f=vi.fn().mockImplementation(()=>Promise.resolve(f.mock.calls.length%2===1?authorization():new Response(JSON.stringify({id:'saved'}))));const api=new Api(async()=>'token',f,()=>owner);const blob=new Blob(['audio'],{type:'audio/webm'});
 await api.upload('s',blob,40,()=>{},key);owner=2;await api.upload('s',blob,40,()=>{},key);expect(sent).toHaveLength(2);expect(f).toHaveBeenCalledTimes(4);
});
it.each([403,413,422,500])('never processes a failed byte relay (%s) or exposes its private payload',async status=>{
 const sent=relay(xhr=>{xhr.status=status;xhr.responseText='https://private.supabase.co/storage/secret-object';});const f=vi.fn(()=>Promise.resolve(authorization()));const api=new Api(async()=>'token',f);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key)).rejects.toThrow(`Upload failed (${status})`);expect(f).toHaveBeenCalledTimes(1);expect(sent).toHaveLength(1);
});
it('replays processing only after its response is lost even after authorization expires',async()=>{
 const sent=relay();const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockRejectedValueOnce(new TypeError('network disconnected')).mockResolvedValueOnce(new Response(JSON.stringify({id:'saved'})));
 const api=new Api(async()=>'token',f,()=>1);const blob=new Blob(['audio'],{type:'audio/webm'});
 await expect(api.upload('s',blob,40,()=>{},key)).rejects.toThrow();
 vi.spyOn(Date,'now').mockReturnValue(Date.now()+7200000);
 try{await expect(api.upload('s',blob,40,()=>{},key)).resolves.toEqual({id:'saved'});}finally{vi.restoreAllMocks();}
 expect(sent).toHaveLength(1);expect(f.mock.calls.map(c=>c[0])).toEqual(['/api/v1/sessions/s/attempt-uploads','/api/v1/sessions/s/attempts','/api/v1/sessions/s/attempts']);expect(f.mock.calls[2][1].body).toBe(JSON.stringify({upload_id:uploadId}));
});
it('requires a new recording after explicit processing failure without leaking server details',async()=>{
 relay();const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Audio processing failed; start a new recording https://private.supabase.co/secret'}),{status:502}));const api=new Api(async()=>'token',f);const blob=new Blob(['audio'],{type:'audio/webm'});
 await expect(api.upload('s',blob,40,()=>{},key)).rejects.toMatchObject({requiresNewRecording:true,message:expect.stringContaining('new recording')});
 await expect(api.upload('s',blob,40,()=>{},key)).rejects.toMatchObject({requiresNewRecording:true});expect(f).toHaveBeenCalledTimes(2);
});
it.each([
 [new Blob([],{type:'audio/webm'}),40],
 [new Blob([new Uint8Array(12582913)],{type:'audio/webm'}),40],
 [new Blob(['audio'],{type:'text/plain'}),40],
 [new Blob(['audio'],{type:'audio/webm'}),NaN],
 [new Blob(['audio'],{type:'audio/webm'}),29],
 [new Blob(['audio'],{type:'audio/webm'}),181],
])('rejects invalid audio metadata before authorization %#',async(blob,seconds)=>{
 const f=vi.fn();const api=new Api(async()=>'token',f);await expect(api.upload('s',blob,seconds,()=>{},key)).rejects.toThrow('Recording');expect(f).not.toHaveBeenCalled();
});
it('handles an unavailable processing key honestly instead of encouraging indefinite resubmission',async()=>{
 relay();const f=vi.fn().mockImplementationOnce(()=>Promise.resolve(authorization())).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Request already processing or key unavailable'}),{status:409}));const api=new Api(async()=>'token',f);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key)).rejects.toMatchObject({requiresNewRecording:true,message:expect.stringContaining('practice history')});
});
it.each([
 {upload_id:'not-a-uuid',expires_at:new Date(Date.now()+300000).toISOString()},
 {upload_id:uploadId.toUpperCase(),expires_at:new Date(Date.now()+300000).toISOString()},
 {upload_id:uploadId,expires_at:'not-a-date'},
 {upload_id:uploadId,expires_at:new Date(Date.now()-1000).toISOString()},
 {upload_id:uploadId,expires_at:new Date(Date.now()+7200000).toISOString()},
 null,
])('rejects malformed or long-lived upload authorization %# without sending bytes',async value=>{
 const sent=relay();const f=vi.fn().mockResolvedValue(new Response(JSON.stringify(value)));const api=new Api(async()=>'token',f);
 await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},key)).rejects.toThrow('upload authorization');expect(sent).toHaveLength(0);expect(f).toHaveBeenCalledTimes(1);
});
it.each(['key','ABCDEFAB-1234-4234-8234-123456789abc'])('rejects noncanonical idempotency key %s before the network',async invalidKey=>{
 const f=vi.fn();const api=new Api(async()=>'token',f);await expect(api.upload('s',new Blob(['audio'],{type:'audio/webm'}),40,()=>{},invalidKey)).rejects.toThrow('Idempotency');expect(f).not.toHaveBeenCalled();
});
it('calls browser fetch with its global receiver rather than the Api instance',async()=>{const nativeLikeFetch=vi.fn(function(this:unknown){if(this!==globalThis)throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");return Promise.resolve(new Response(JSON.stringify({role:'Engineer'})));});const api=new Api(async()=>'verified-token',nativeLikeFetch as typeof fetch);await expect(api.get('/profile')).resolves.toEqual({role:'Engineer'});});
it('rejects a private response when the account changes while it is in flight',async()=>{let owner:string|null='a';let finish:(r:Response)=>void=()=>{};const response=new Promise<Response>(r=>{finish=r;});const fetcher=vi.fn(()=>response);const api=new Api(async()=>'token-a',fetcher,()=>owner);const request=api.get('/profile');await vi.waitFor(()=>expect(fetcher).toHaveBeenCalled());owner='b';finish(new Response(JSON.stringify({role:'Private A'})));await expect(request).rejects.toThrow('Account changed');});
it('refuses an unauthenticated audio upload',async()=>{const api=new Api(async()=>null);await expect(api.upload('s',new Blob(['audio']),30,()=>{},'key')).rejects.toThrow('Sign in');});
it('attaches a bearer token and surfaces backend errors',async()=>{const f=vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'Daily quota reached'}),{status:429}));const api=new Api(async()=>'verified-token',f);await expect(api.get('/usage')).rejects.toThrow('Daily quota reached');expect(f.mock.calls[0][1].headers.Authorization).toBe('Bearer verified-token');});
it('fails closed before private requests when no authenticated session exists',async()=>{const fetcher=vi.fn();const api=new Api(async()=>null,fetcher);await expect(api.get('/profile')).rejects.toThrow('Sign in');expect(fetcher).not.toHaveBeenCalled();});