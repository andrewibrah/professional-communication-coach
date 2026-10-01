import {Api} from './api';
import {parseGuidedSession,parseGuidedList,parseGuidedConnection,type GuidedAction,type GuidedSession,type GuidedSetup} from './guided-types';
export class GuidedApi{
 constructor(private api:Api){}
 private async request(path:string,init:RequestInit={}):Promise<unknown>{try{return await this.api.get<unknown>('/guided-sessions'+path,init);}catch(e){const message=e instanceof Error?e.message:'';if(['Account changed. Please retry from your current workspace.','Sign in with a verified account to continue.','Verify your email and sign in to continue.'].includes(message))throw new Error(message);throw new Error('Guided request failed. Check your connection and reload the saved session before trying another action.');}}
 private post(path:string,body:unknown,signal?:AbortSignal){return this.request(path,{method:'POST',body:JSON.stringify(body),signal});}
 async create(input:GuidedSetup,signal?:AbortSignal){return parseGuidedSession(await this.post('',{command_id:crypto.randomUUID(),...input},signal));}
 async get(id:string,signal?:AbortSignal){return parseGuidedSession(await this.request('/'+encodeURIComponent(id),{signal}));}
 async list(signal?:AbortSignal){return parseGuidedList(await this.request('',{signal}));}
 async connect(s:GuidedSession,sdp:string,signal?:AbortSignal){return parseGuidedConnection(await this.post('/'+encodeURIComponent(s.id)+'/connection',{command_id:crypto.randomUUID(),expected_revision:s.revision,sdp},signal));}
 async command(s:GuidedSession,action:GuidedAction,prompt_visible?:boolean,signal?:AbortSignal){return parseGuidedSession(await this.post('/'+encodeURIComponent(s.id)+'/commands',{command_id:crypto.randomUUID(),expected_revision:s.revision,prompt_id:s.prompts[s.prompt_index]?.id??null,action,...(action==='visibility'?{prompt_visible}: {})},signal));}
 async heartbeat(id:string,signal?:AbortSignal){return parseGuidedSession(await this.post('/'+encodeURIComponent(id)+'/heartbeat',{},signal));}
 async delete(id:string,signal?:AbortSignal){const r=await this.request('/'+encodeURIComponent(id),{method:'DELETE',signal});if(r!==undefined)throw new Error('Invalid guided deletion response.');}
}
