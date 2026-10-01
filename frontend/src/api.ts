export class UploadError extends Error {
 constructor(message:string,public readonly requiresNewRecording=false){super(message);this.name='UploadError';}
}
type UploadReceipt={upload_id:string;expires_at:number;uploaded:boolean;failed:boolean};
export class Api {
 private uploadOwner:unknown;
 private uploads=new Map<string,UploadReceipt>();
 constructor(private token:()=>Promise<string|null>,private fetcher:typeof fetch=fetch,private scope:()=>unknown=()=>null){}
 async upload<T>(id:string,blob:Blob,seconds:number,onProgress:(p:number)=>void,key:string,signal?:AbortSignal):Promise<T>{
 const owner=this.scope();
 const check=()=>{if(owner!==this.scope())throw new Error('Account changed. Please retry from your current workspace.');if(signal?.aborted)throw new Error('Upload cancelled.');};
 check();const token=await this.token();check();if(!token)throw new Error('Sign in with a verified account to continue.');
 const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
 if(!uuid.test(key))throw new Error('Idempotency key must be a canonical UUID. Record a new response.');
 if(!blob.size||blob.size>12582912||!Number.isFinite(seconds)||seconds<30||seconds>180||!['audio/webm','audio/ogg','audio/mp4','audio/wav','audio/x-wav','audio/mpeg'].includes(blob.type.split(';')[0].toLowerCase()))throw new Error('Recording must contain supported audio, be 30–180 seconds, and not exceed 12 MiB.');
 if(this.uploadOwner!==owner){this.uploads.clear();this.uploadOwner=owner;}
 const cacheKey=JSON.stringify([id,key]);
 let receipt=this.uploads.get(cacheKey);
 if(receipt?.failed)throw new UploadError('Processing failed. Start a new recording before submitting again.',true);
 const path='/api/v1/sessions/'+encodeURIComponent(id);
 const headers={'Content-Type':'application/json',Authorization:`Bearer ${token}`,'Idempotency-Key':key};
 const request=async(url:string,body:unknown,processing=false)=>{
 check();const response=await this.fetcher.call(globalThis,url,{method:'POST',headers,body:JSON.stringify(body),signal});check();
 if(!response.ok){
 // Never display provider payloads, private object paths, or Storage URLs.
 if(processing&&[400,404,409,410,422,502].includes(response.status)){
 if(receipt)receipt.failed=true;
 const message=response.status===409?'Recording is already processing or unavailable. Check practice history before starting a new recording.':'Processing failed. Start a new recording before submitting again.';
 throw new UploadError(message,true);
 }
 throw new UploadError(`Request failed (${response.status}). Please try again.`);
 }
 const data=await response.json().catch(()=>{throw new Error('The server returned an unreadable response. Please try again.');});check();return data;
 };
 if(!receipt?.uploaded){
 if(!receipt||receipt.expires_at<=Date.now()){
 const authorization=await request(path+'/attempt-uploads',{content_type:blob.type,size_bytes:blob.size,duration_seconds:seconds});check();
 const expiry=typeof authorization?.expires_at==='string'?Date.parse(authorization.expires_at):NaN;
 if(!authorization||typeof authorization.upload_id!=='string'||!uuid.test(authorization.upload_id)||!Number.isFinite(expiry)||expiry<=Date.now()||expiry>Date.now()+360000)throw new Error('Invalid upload authorization. Please try again.');
 receipt={upload_id:authorization.upload_id,expires_at:expiry,uploaded:false,failed:false};this.uploads.set(cacheKey,receipt);
 }
 const authorization=receipt;
 try{
 await new Promise<void>((resolve,reject)=>{
 const xhr=new XMLHttpRequest();xhr.open('PUT',path+'/attempt-uploads/'+encodeURIComponent(authorization.upload_id));xhr.setRequestHeader('Authorization',`Bearer ${token}`);xhr.setRequestHeader('Content-Type',blob.type);xhr.timeout=240000;
 const abort=()=>xhr.abort();const cleanup=()=>signal?.removeEventListener('abort',abort);
 const fail=(message:string)=>{cleanup();reject(new Error(message));};
 signal?.addEventListener('abort',abort,{once:true});
 xhr.upload.onprogress=e=>{try{check();if(e.lengthComputable)onProgress(Math.min(99,Math.round(e.loaded/e.total*100)));}catch(e){cleanup();xhr.abort();reject(e);}};
 xhr.onload=()=>{cleanup();try{check();if(xhr.status!==204)throw new Error(`Upload failed (${xhr.status}). Please try again.`);authorization.uploaded=true;onProgress(100);resolve();}catch(e){reject(e);}};
 xhr.onerror=()=>fail('Upload interrupted. Check your connection and retry.');xhr.ontimeout=()=>fail('Upload timed out. Please try again.');xhr.onabort=()=>fail('Upload cancelled.');
 try{check();xhr.send(blob);}catch(e){cleanup();reject(e);}
 });
 }catch(e){if(owner===this.scope()&&this.uploads.get(cacheKey)===authorization&&!authorization.uploaded)this.uploads.delete(cacheKey);check();throw e;}
 check();receipt.uploaded=true;
 }else{check();onProgress(100);}
 check();const result=await request(path+'/attempts',{upload_id:receipt.upload_id},true);check();return result as T;
 }
 async get<T>(path:string, init:RequestInit={}):Promise<T>{
 const scope=this.scope();const token=await this.token();if(scope!==this.scope())throw new Error('Account changed. Please retry from your current workspace.');if(!token)throw new Error('Sign in with a verified account to continue.');
 const response=await this.fetcher.call(globalThis,'/api/v1'+path,{...init,headers:{'Content-Type':'application/json',...init.headers,Authorization:`Bearer ${token}`}});
 const data=response.status===204?undefined:await response.json().catch(()=>{if(response.ok)throw new Error('The server returned an unreadable response. Please try again.');return {};});
 if(scope!==this.scope())throw new Error('Account changed. Please retry from your current workspace.');
 if(!response.ok)throw new Error(typeof data?.detail==='string'?data.detail:`Request failed (${response.status}). Please try again.`);
 return data as T;
 }
}
