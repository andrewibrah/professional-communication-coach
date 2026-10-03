import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import App from './App';
import {AuthDialog} from './AuthDialog';
const sdk=vi.hoisted(()=>({createClient:vi.fn(),client:{auth:{getSession:vi.fn().mockResolvedValue({data:{session:null}}),onAuthStateChange:vi.fn(()=>({data:{subscription:{unsubscribe:vi.fn()}}}))}}}));
vi.mock('@supabase/supabase-js',()=>({createClient:sdk.createClient}));
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.clearAllMocks();});
it('enables real Supabase sign-in from public build configuration when Pages has no API',async()=>{
 vi.stubEnv('VITE_SUPABASE_URL','https://example.supabase.co');
 vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY','sb_publishable_test_only');
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('Not found',{status:404})));
 sdk.createClient.mockReturnValue(sdk.client);
 render(<App/>);
 await waitFor(()=>expect(sdk.createClient).toHaveBeenCalledWith('https://example.supabase.co','sb_publishable_test_only'));
 fireEvent.click(screen.getByRole('button',{name:/^Sign in$/}));
 expect(screen.getByRole('button',{name:'Sign in securely'})).toBeEnabled();
 expect(screen.getByText(/Authentication is available.*practice.*API/i)).toBeInTheDocument();
});
it('keeps auth disabled when build configuration contains a privileged key',async()=>{
 vi.stubEnv('VITE_SUPABASE_URL','https://example.supabase.co');
 vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY','sb_secret_never_public');
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('Not found',{status:404})));
 render(<App/>);
 await screen.findByText(/Backend unavailable/);
 expect(sdk.createClient).not.toHaveBeenCalled();
});
it('uses the Pages repository URL for confirmation redirects instead of the account root',async()=>{
 vi.stubEnv('BASE_URL','/professional-communication-coach/');
 const signUp=vi.fn().mockResolvedValue({error:null});
 render(<AuthDialog client={{auth:{signUp}} as any} recovery={false} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Create an account'}));
 fireEvent.change(screen.getByRole('textbox',{name:'Email address'}),{target:{value:'test@example.test'}});
 fireEvent.change(screen.getByLabelText('Password'),{target:{value:'test-only-password'}});
 fireEvent.submit(screen.getByRole('button',{name:'Create account'}).closest('form')!);
 await waitFor(()=>expect(signUp).toHaveBeenCalledWith(expect.objectContaining({options:{emailRedirectTo:window.location.origin+'/professional-communication-coach/'}})));
});
