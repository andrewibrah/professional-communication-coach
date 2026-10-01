import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import App from './App';
import {emptyProfile} from './types';
const sdk=vi.hoisted(()=>({client:null as any}));
vi.mock('@supabase/supabase-js',()=>({createClient:()=>sdk.client}));
it('does not restore private history from a request that finishes after sign-out',async()=>{
 let event:(name:string,session:any)=>void=()=>{};
 const session={user:{id:'owner-a',email:'a@example.test',email_confirmed_at:'2026-01-01'},access_token:'test-token'};
 let resolveHistory:(value:Response)=>void=()=>{};
 const history=new Promise<Response>(resolve=>{resolveHistory=resolve;});
 sdk.client={auth:{getSession:vi.fn().mockResolvedValue({data:{session}}),getUser:vi.fn().mockResolvedValue({data:{user:session.user}}),onAuthStateChange:vi.fn((cb)=>{event=cb;return {data:{subscription:{unsubscribe:vi.fn()}}};})}};
 vi.stubGlobal('fetch',vi.fn(async(path:string)=>{
  if(path.endsWith('/config'))return new Response(JSON.stringify({auth_configured:true,supabase_url:'https://example.supabase.co',supabase_publishable_key:'public-test',ai_enabled:true}));
  if(path.endsWith('/scenarios'))return new Response(JSON.stringify({scenarios:[]}));
  if(path.endsWith('/sessions'))return history;
  if(path.endsWith('/profile'))return new Response(JSON.stringify(emptyProfile));
  return new Response(JSON.stringify({daily_used:0,daily_limit:20,monthly_used:0,monthly_limit:200}));
 }));
 render(<App/>);
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/v1/sessions',expect.anything()));
 act(()=>event('SIGNED_OUT',null));
 await act(async()=>{resolveHistory(new Response(JSON.stringify({sessions:[{id:'private',scenario_id:'introduction',goal:'PRIVATE OWNER A GOAL',created_at:'2026-01-01',attempt_count:1,latest_score:83}]})));await history;});
 fireEvent.click(screen.getByRole('button',{name:'Practice history'}));
 expect(screen.queryByText(/PRIVATE OWNER A GOAL/)).not.toBeInTheDocument();
 expect(screen.getByText('Your first conversation belongs here.')).toBeInTheDocument();
});
