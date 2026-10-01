"""Actual Chromium/local WebRTC proof using synthetic Web Audio, no Auth/provider.

Runs the application's VoiceTransport unchanged. This is NOT microphone speech,
OpenAI coaching, provider termination, or two-user proof. No private data captured.
"""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROME = '/Users/me/.agent-browser/browsers/chrome-154.0.8037.92/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
ENV = os.environ | {'AGENT_BROWSER_SESSION': 'speechclear-guided-media-proof', 'AGENT_BROWSER_EXECUTABLE_PATH': CHROME, 'AGENT_BROWSER_DEFAULT_TIMEOUT': '90000'}


def run(*args, code=None):
    result = subprocess.run(['npx', '--yes', 'agent-browser', '--args', '--disable-features=WebRtcHideLocalIpsWithMdns,--allow-loopback-in-peer-connection', *args], env=ENV, input=code,
                            text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


SETUP = r"""(async()=>{
 const {VoiceTransport}=await import('/src/voice-session.ts');
 const button=document.createElement('button');button.id='guided-media-proof-start';button.textContent='Run synthetic local guided transport proof';button.style.cssText='position:fixed;top:12px;right:12px;z-index:2147483647;background:white;color:black;padding:12px';document.body.append(button);
 button.onclick=async()=>{
  let context,other,transport,local,output,audio,inputTrack;
  try{
   context=new AudioContext();await context.resume();
   const inputNode=context.createOscillator(),input=context.createMediaStreamDestination();inputNode.frequency.value=330;inputNode.connect(input);inputNode.start();inputTrack=input.stream.getAudioTracks()[0];
   const coachNode=context.createOscillator();output=context.createMediaStreamDestination();coachNode.frequency.value=440;coachNode.connect(output);coachNode.start();
   transport=new VoiceTransport({}, {getUserMedia:async()=>input.stream,createPeer:()=>{local=new RTCPeerConnection();return local;},createAudio:()=>{audio=new Audio();return audio;},tailMs:500,timeoutMs:12000});
   await transport.acquire();const disabledBefore=inputTrack.enabled===false;
   await transport.connect(async sdp=>{
    other=new RTCPeerConnection();output.stream.getAudioTracks().forEach(track=>other.addTrack(track,output.stream));
    await other.setRemoteDescription({type:'offer',sdp});await other.setLocalDescription(await other.createAnswer());
    if(other.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Other ICE timeout')),10000);const check=()=>{if(other.iceGatheringState==='complete'){clearTimeout(timer);other.removeEventListener('icegatheringstatechange',check);resolve();}};other.addEventListener('icegatheringstatechange',check);check();});
    return other.localDescription.sdp;
   });
   const id='11111111-1111-4111-8111-111111111111',prompt='22222222-2222-4222-8222-222222222222';
   const session={id,scenario_id:'help-desk',goal:'Synthetic transport verification',created_at:new Date().toISOString(),expires_at:new Date(Date.now()+300000).toISOString(),state:'listening',revision:1,prompt_visible:false,muted:false,max_retries:2,prompts:[{id:prompt,text:'Synthetic fixture only',exercise_type:'repetition',position:0}],prompt_index:0,attempts_on_prompt:0,turns:[],recap:null,status_message:'Synthetic authority fixture only'};
   transport.apply(session);await new Promise(r=>setTimeout(r,900));const enabledListening=inputTrack.enabled;
   const stats=await local.getStats();const inbound=[...stats.values()].filter(s=>s.type==='inbound-rtp'&&s.kind==='audio');const packets=inbound.reduce((n,s)=>n+(s.packetsReceived??0),0);
   const playbackStarted=audio.srcObject instanceof MediaStream&&!audio.paused;
   const audioOnly=local.localDescription.sdp.split(/\r?\n/).filter(s=>s.startsWith('m=')).every(s=>s.startsWith('m=audio '));
   transport.apply({...session,state:'coach_speaking',revision:2});const disabledSpeaking=!inputTrack.enabled;
   transport.close();const released=inputTrack.readyState==='ended'&&local.connectionState==='closed'&&audio.srcObject===null;
   window.__guidedProof={scope:'actual Chromium + local peer WebRTC + synthetic Web Audio; no live Auth/provider/microphone speech',disabledBefore,enabledListening,disabledSpeaking,playbackStarted,audioOnly,packetsReceived:packets,released,pass:disabledBefore&&enabledListening&&disabledSpeaking&&playbackStarted&&audioOnly&&packets>0&&released};
  }catch(error){window.__guidedProof={pass:false,error:String(error),localState:local?.connectionState,otherState:other?.connectionState,localIce:local?.iceConnectionState,otherIce:other?.iceConnectionState,localGathering:local?.iceGatheringState,otherGathering:other?.iceGatheringState,localCandidateCount:(local?.localDescription?.sdp.match(/a=candidate:/g)||[]).length,otherCandidateCount:(other?.localDescription?.sdp.match(/a=candidate:/g)||[]).length};}
  finally{transport?.close();other?.close();output?.stream.getTracks().forEach(t=>t.stop());if(context&&context.state!=='closed')await context.close();window.__guidedProof.cleanupReleased=(!inputTrack||inputTrack.readyState==='ended')&&(!local||local.connectionState==='closed')&&(!other||other.connectionState==='closed')&&(!audio||audio.srcObject===null);window.__guidedProofDone=true;}
 };
 return {installed:true};
})()"""

if __name__ == '__main__':
    try:
        run('open', 'http://localhost:5173')
        run('eval', '--stdin', code=SETUP)
        run('click', '#guided-media-proof-start')
        run('wait', '--fn', 'window.__guidedProofDone===true')
        receipt = json.loads(run('eval', '--stdin', code='JSON.stringify(window.__guidedProof)'))
        if isinstance(receipt, str):
            receipt = json.loads(receipt)
        print(json.dumps(receipt, indent=2))
        path = ROOT / '.hermes/docs/verification/GUIDED_BROWSER_RECEIPT.json'
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        print('Receipt:', path)
        assert receipt['pass'] is True, 'Synthetic browser peer connection did not pass; receipt preserved, do not claim live acceptance'
    finally:
        run('close')
