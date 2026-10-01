import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {GuidedSessionView} from './GuidedSessionView';
import {GuidedApi} from './guided-api';
import {Api} from './api';
import {mediaDoubles} from './guided-test-doubles';
it('allows the pre-session prompt preference while signed out without requesting microphone access',()=>{
 const d=mediaDoubles(),api=new GuidedApi(new Api(async()=>null,vi.fn()));
 render(<GuidedSessionView api={api} setup={{scenario_id:'help-desk',goal:'Clarity',context:'',prompt_visible:true}} available={false} verified={false} dependencies={d.deps}/>);
 fireEvent.click(screen.getByRole('button',{name:'Hide Prompt'}));
 expect(screen.getByRole('button',{name:'Show Prompt'})).toHaveAttribute('aria-pressed','false');
 expect(d.deps.getUserMedia).not.toHaveBeenCalled();
 expect(screen.getByRole('button',{name:'Start guided session'})).toBeDisabled();
});
