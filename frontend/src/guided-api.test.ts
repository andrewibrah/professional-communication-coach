import {expect,it,vi} from 'vitest';
import {Api} from './api';
import {GuidedApi} from './guided-api';
import {parseGuidedAvailability} from './guided-types';
import {networkDto as dto} from './guided-test-doubles';
it('creates through the existing authenticated owner-scoped Api and validates the public DTO',async()=>{
 const expected=dto();const f=vi.fn(function(this:unknown){expect(this).toBe(globalThis);return Promise.resolve(new Response(JSON.stringify(expected)));});
 const guided=new GuidedApi(new Api(async()=>'test-only-token',f));
 await expect(guided.create({scenario_id:'help-desk',goal:'Clarity',context:'',prompt_visible:true})).resolves.toEqual(expected);
 const [path,init]=f.mock.calls[0] as unknown as [string,RequestInit];expect(path).toBe('/api/v1/guided-sessions');expect(JSON.parse(String(init.body))).toMatchObject({command_id:expect.stringMatching(/^[a-f0-9-]{36}$/),prompt_visible:true});
 expect(init.headers).toMatchObject({Authorization:'Bearer test-only-token'});
});
it.each([null,{...dto(),revision:-1},{...dto(),state:'invented'},{...dto(),prompts:[{id:'p',text:'x'.repeat(20001),exercise_type:'repetition',position:0}]},{...dto(),provider_session_id:'secret'},{...dto(),recap:{practiced_exercises:1,completed_attempts:1,focus:'x'}}])('rejects malformed or private DTOs %#',async data=>{
 const guided=new GuidedApi(new Api(async()=>'test',vi.fn().mockResolvedValue(new Response(JSON.stringify(data)))));await expect(guided.get('session-a')).rejects.toThrow('Invalid guided');
});
it('does not return old owner snapshots or expose backend/provider error payloads',async()=>{
 let owner=0;const guided=new GuidedApi(new Api(async()=>'test',vi.fn(async()=>{owner++;return new Response(JSON.stringify(dto()));}),()=>owner));await expect(guided.get('session-a')).rejects.toThrow('Account changed');
 const failed=new GuidedApi(new Api(async()=>'test',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'provider private secret target'}),{status:502}))));await expect(failed.get('session-a')).rejects.toThrow('Guided request failed');
});
it('defaults missing optional guided configuration to unavailable and validates every supplied field',()=>{
 expect(parseGuidedAvailability({})).toEqual({guided_voice_available:false});expect(parseGuidedAvailability({guided_voice_available:true,guided_max_seconds:300,guided_unavailable_reason:''})).toEqual({guided_voice_available:true,guided_max_seconds:300,guided_unavailable_reason:''});for(const value of [{guided_voice_available:'true'},{guided_max_seconds:1.1},{guided_unavailable_reason:'https://provider.example/secret'},{guided_unavailable_reason:'x'.repeat(501)}])expect(()=>parseGuidedAvailability(value)).toThrow('Invalid guided');
});
it.each(['Account changed PRIVATE PROVIDER PAYLOAD','Sign in https://private.example/secret','Verify your email Bearer private-token'])('does not trust auth-looking provider error prefixes %#',async detail=>{
 const guided=new GuidedApi(new Api(async()=>'test',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail}),{status:502}))));
 await expect(guided.get(dto().id)).rejects.toThrow('Guided request failed.');
});
it.each(['Account changed. Please retry from your current workspace.','Sign in with a verified account to continue.','Verify your email and sign in to continue.'])('preserves the exact existing safe auth error %#',async message=>{
 const guided=new GuidedApi(new Api(async()=>{throw new Error(message);},vi.fn()));await expect(guided.get(dto().id)).rejects.toThrow(message);
});
