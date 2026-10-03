import type {Config} from './types';

// Only publishable credentials may enter a static bundle. Backend authority stays unavailable.
export function publicAuthConfig():Config|null{
 const url=import.meta.env.VITE_SUPABASE_URL;
 const key=import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
 if(typeof url!=='string'||typeof key!=='string'||!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key))return null;
 try{const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.search||parsed.hash||parsed.pathname!=='/')return null;}catch{return null;}
 return {supabase_url:url,supabase_publishable_key:key,auth_configured:true,ai_enabled:false,min_recording_seconds:30,max_recording_seconds:180,max_upload_bytes:12582912,guided_voice_available:false,guided_max_seconds:300,guided_unavailable_reason:'Practice requires a connected API.'};
}

export function authRedirectUrl():string{
 return new URL(import.meta.env.BASE_URL,window.location.origin).href;
}
