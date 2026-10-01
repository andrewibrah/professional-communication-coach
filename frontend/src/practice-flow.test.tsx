import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {Api,UploadError} from './api';
import {RecordingController} from './recording';
import {SessionView} from './SessionView';
import type {Attempt,Config,PracticeSession,Report} from './types';
// Test-only provider response; never imported by application code.
const report:Report={overall_score:60,category_scores:{clarity:60,structure:60,conciseness:60,audience_fit:60,professional_tone:60},communication_strengths:['A clear opening'],transcript_evidence:[{quote:'I can help',observation:'Offers a practical next step'}],filler_words:[],jargon_flags:[],pacing_observations:['Steady pace'],weak_phrasing:[],missed_questions:[],priority_improvement:'Make the next step specific',suggested_practice_exercise:'Summarize the next action',improved_answer:'I can help you troubleshoot the connection.',next_time_recommendation:'End with an action'};
const first:Attempt={id:'first',session_id:'session-a',transcript:'I can help',duration_seconds:40,created_at:'2026-01-01',report};
const latest:Attempt={...first,id:'latest',report:{...report,overall_score:75}};
it('offers a new recording instead of resubmitting a terminally failed processing key',async()=>{
 let finish:(blob:Blob,seconds:number)=>void=()=>{};
 const start=vi.spyOn(RecordingController.prototype,'start').mockImplementation(async cb=>{finish=cb;});
 const stop=vi.spyOn(RecordingController.prototype,'stop').mockImplementation(()=>finish(new Blob(['audio'],{type:'audio/webm'}),40));
 const api=new Api(async()=>'token');const upload=vi.spyOn(api,'upload').mockRejectedValue(new UploadError('Processing failed. Start a new recording before submitting again.',true));
 const get=vi.spyOn(api,'get');const onChange=vi.fn();
 render(<SessionView session={{...session,attempts:[]}} api={api} config={{ai_enabled:true} as Config} onChange={onChange} onBack={()=>{}}/>);
 try{
 fireEvent.click(screen.getByRole('button',{name:'Start recording'}));await screen.findByRole('button',{name:'Finish recording'});fireEvent.click(screen.getByRole('button',{name:'Finish recording'}));fireEvent.click(screen.getByRole('button',{name:'Get my feedback'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('new recording');
 expect(screen.queryByRole('button',{name:'Get my feedback'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Start recording'})).toBeInTheDocument();expect(get).not.toHaveBeenCalled();expect(onChange).not.toHaveBeenCalled();expect(upload).toHaveBeenCalledTimes(1);
 }finally{start.mockRestore();stop.mockRestore();}
});
it('does not refresh a session after unmount while upload is completing',async()=>{
 let finish:(blob:Blob,seconds:number)=>void=()=>{};let resolve:(attempt:Attempt)=>void=()=>{};
 const start=vi.spyOn(RecordingController.prototype,'start').mockImplementation(async cb=>{finish=cb;});const stop=vi.spyOn(RecordingController.prototype,'stop').mockImplementation(()=>finish(new Blob(['audio'],{type:'audio/webm'}),40));
 const api=new Api(async()=>'token');const pending=new Promise<Attempt>(r=>{resolve=r;});vi.spyOn(api,'upload').mockReturnValue(pending);const get=vi.spyOn(api,'get');const onChange=vi.fn();
 const view=render(<SessionView session={{...session,attempts:[]}} api={api} config={{ai_enabled:true} as Config} onChange={onChange} onBack={()=>{}}/>);
 try{fireEvent.click(screen.getByRole('button',{name:'Start recording'}));await screen.findByRole('button',{name:'Finish recording'});fireEvent.click(screen.getByRole('button',{name:'Finish recording'}));fireEvent.click(screen.getByRole('button',{name:'Get my feedback'}));view.unmount();resolve(latest);await pending;await Promise.resolve();expect(get).not.toHaveBeenCalled();expect(onChange).not.toHaveBeenCalled();}finally{start.mockRestore();stop.mockRestore();}
});
const session:PracticeSession={id:'session-a',scenario_id:'help-desk',goal:'Clarity',context:'Help a customer',question:'What is your next step?',example_response:'Check the connection',created_at:'2026-01-01',attempts:[first]};
it('retries a failed upload with the same key and compares first versus latest in the same session',async()=>{
 let finish:(blob:Blob,seconds:number)=>void=()=>{};
 const start=vi.spyOn(RecordingController.prototype,'start').mockImplementation(async cb=>{finish=cb;});
 const stop=vi.spyOn(RecordingController.prototype,'stop').mockImplementation(()=>finish(new Blob(['test audio'],{type:'audio/webm'}),40));
 const api=new Api(async()=>'test-token');
 const upload=vi.spyOn(api,'upload').mockRejectedValueOnce(new Error('Upload interrupted')).mockResolvedValue(latest);
 const saved={...session,attempts:[first,latest]};
 const get=vi.spyOn(api,'get').mockResolvedValue(saved);
 const onChange=vi.fn();
 const props={session,api,config:{ai_enabled:true,max_upload_bytes:12582912} as Config,onChange,onBack:()=>{}};
 const view=render(<SessionView {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'Try again in this session'}));
 fireEvent.click(screen.getByRole('button',{name:'Start recording'}));
 await screen.findByRole('button',{name:'Finish recording'});
 fireEvent.click(screen.getByRole('button',{name:'Finish recording'}));
 fireEvent.click(screen.getByRole('button',{name:'Get my feedback'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Upload interrupted');
 fireEvent.click(screen.getByRole('button',{name:'Get my feedback'}));
 await waitFor(()=>expect(onChange).toHaveBeenCalledWith(saved));
 expect(upload.mock.calls[0][0]).toBe('session-a');
 expect(upload.mock.calls[1][4]).toBe(upload.mock.calls[0][4]);
 expect(upload.mock.calls[0][4]).toMatch(/^[0-9a-f-]{36}$/);
 expect(get).toHaveBeenCalledWith('/sessions/session-a');
 view.rerender(<SessionView {...props} session={saved}/>);
 expect(screen.getByText('First attempt')).toBeInTheDocument();
 expect(screen.getByText('Latest attempt')).toBeInTheDocument();
 expect(screen.getAllByText('I can help')).toHaveLength(4);
 expect(screen.getAllByText('Make the next step specific')).toHaveLength(2);
 expect(screen.getByText('75')).toBeInTheDocument();
 start.mockRestore();stop.mockRestore();
});
