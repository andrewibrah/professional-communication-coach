import {afterEach,expect,it,vi} from 'vitest';
import {VoiceTransport,VoiceSession} from './voice-session';
import {GuidedApi} from './guided-api';
import {Api} from './api';
import {audioSdp,deferred,dto,mediaDoubles} from './guided-test-doubles';
afterEach(()=>vi.useRealTimers());
it('uses audio-only peer transport without a data channel and gates the microphone behind authoritative listening plus playback tail',async()=>{
 vi.useFakeTimers();const d=mediaDoubles();const transport=new VoiceTransport({},d.deps);const acquired=transport.acquire();expect(d.deps.getUserMedia).toHaveBeenCalledWith({audio:true});await acquired;expect(d.track.enabled).toBe(false);
 const exchange=vi.fn().mockResolvedValue(audioSdp);await transport.connect(exchange);expect(d.peer.createDataChannel).not.toHaveBeenCalled();expect(d.peer.addTrack).toHaveBeenCalledWith(d.track,d.stream);expect(exchange).toHaveBeenCalledWith(audioSdp);expect(d.audio.play).toHaveBeenCalled();
 transport.apply({...dto(),state:'coach_speaking'});await vi.advanceTimersByTimeAsync(1000);expect(d.track.enabled).toBe(false);
 transport.apply({...dto(),state:'listening',revision:1});await vi.advanceTimersByTimeAsync(499);expect(d.track.enabled).toBe(false);await vi.advanceTimersByTimeAsync(1);expect(d.track.enabled).toBe(true);
 transport.apply({...dto(),state:'reviewing',revision:2});expect(d.track.enabled).toBe(false);
 transport.close();expect(d.track.stop).toHaveBeenCalled();expect(d.peer.close).toHaveBeenCalled();expect(d.audio.srcObject).toBeNull();expect(vi.getTimerCount()).toBe(0);
});
it('stops a late permission stream after cancellation without ever creating a peer',async()=>{
 const d=mediaDoubles();const permission=deferred<MediaStream>();d.deps.getUserMedia.mockReturnValue(permission.promise);const t=new VoiceTransport({},d.deps);const pending=t.acquire();t.close();permission.resolve(d.stream);await expect(pending).rejects.toThrow('cancelled');expect(d.track.stop).toHaveBeenCalled();expect(d.peer.addTrack).not.toHaveBeenCalled();
});
it('starts microphone acquisition in the gesture, saves authoritative session state and tears down immediately before pause persistence',async()=>{
 const d=mediaDoubles();const saved={...dto(),state:'coach_speaking' as const,revision:1};const pause=deferred<any>();const api=new GuidedApi(new Api(async()=>'test',vi.fn()));vi.spyOn(api,'create').mockResolvedValue(dto());vi.spyOn(api,'connect').mockResolvedValue({sdp:audioSdp,session:saved});const command=vi.spyOn(api,'command').mockReturnValue(pause.promise);const updates=vi.fn();const c=new VoiceSession(api,updates,d.deps);
 const starting=c.start({scenario_id:'help-desk',goal:'Clarity',context:'',prompt_visible:true});expect(d.deps.getUserMedia).toHaveBeenCalledTimes(1);await starting;expect(c.view.session).toEqual(saved);expect(c.view.transport).toBe('connected');
 const pausing=c.action('pause');expect(d.track.stop).toHaveBeenCalled();expect(d.audio.srcObject).toBeNull();await vi.waitFor(()=>expect(command).toHaveBeenCalledWith(saved,'pause',undefined,expect.any(AbortSignal)));pause.resolve({...saved,state:'paused',revision:2});await pausing;expect(c.view.session?.state).toBe('paused');c.dispose(false);
});
it('ignores an obsolete Audio.play rejection after replay has restored a newer playback attempt',async()=>{
 vi.useFakeTimers();const d=mediaDoubles(),old=deferred<void>(),blocked=vi.fn();vi.mocked(d.audio.play).mockReturnValueOnce(old.promise);const t=new VoiceTransport({onAudioBlocked:blocked},d.deps);await t.acquire();await t.connect(async()=>audioSdp);t.apply({...dto(),state:'listening',revision:1});t.dropPlayback();await t.restorePlayback();old.reject(new Error('obsolete autoplay failure'));await vi.advanceTimersByTimeAsync(500);expect(blocked).not.toHaveBeenLastCalledWith(true);expect(d.track.enabled).toBe(true);t.close();
});
it('uses one authoritative heartbeat request per poll so default limits leave room for controls',async()=>{
 vi.useFakeTimers();const d=mediaDoubles();const api=new GuidedApi(new Api(async()=>'test',vi.fn()));
 const live={...dto(),state:'listening' as const,revision:1};vi.spyOn(api,'create').mockResolvedValue(dto());vi.spyOn(api,'connect').mockResolvedValue({sdp:audioSdp,session:live});const get=vi.spyOn(api,'get').mockResolvedValue(live);const heartbeat=vi.spyOn(api,'heartbeat').mockResolvedValue(live);
 const c=new VoiceSession(api,()=>{},d.deps);await c.start({scenario_id:'help-desk',goal:'Clarity',context:'',prompt_visible:true});await vi.advanceTimersByTimeAsync(60000);
 expect(heartbeat).toHaveBeenCalledTimes(30);expect(get).not.toHaveBeenCalled();expect(c.view.transport).toBe('connected');c.dispose(false);expect(vi.getTimerCount()).toBe(0);
});
