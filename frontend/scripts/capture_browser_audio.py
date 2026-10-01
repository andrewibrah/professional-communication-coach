"""Capture non-private regression fixtures with the actual browser recorder.

Requires the Vite dev server and npx agent-browser. Uses a Web Audio oscillator,
not user microphone content, auth state, a mocked MediaRecorder, or ffmpeg input.
"""
import json
import os
from pathlib import Path
import subprocess
import base64

ROOT = Path(__file__).resolve().parents[2]
SESSION = "speechclear-completion"
ENV = os.environ | {"AGENT_BROWSER_DEFAULT_TIMEOUT": "90000"}
CHROME = os.environ.get("SPEECHCLEAR_TEST_CHROME")


def browser(*args, source=None):
    result = subprocess.run(
        ["npx", "--yes", "agent-browser", "--session", SESSION, "--json",
         *(["--executable-path", CHROME] if CHROME else []), *args],
        input=source,
        capture_output=True,
        text=True,
        timeout=120,
        env=ENV,
        check=True,
    )
    receipt = json.loads(result.stdout)
    if not receipt.get("success"):
        raise RuntimeError("Browser capture failed; inspect safe browser status")
    return receipt.get("data", {})


browser("open", "http://localhost:5173")
browser("find", "role", "button", "click", "--name", "Overview", "--exact")
browser("eval", "--stdin", source="""
(async () => {
  const {RecordingController} = await import('/src/recording.ts');
  window.audioCapture = {done:false, clips:[]};
  (async () => {
    for (const [name, milliseconds] of [['short',2000],['boundary',30000],['valid',31200]]) {
      const context = new AudioContext();
      await context.resume();
      const oscillator = context.createOscillator();
      const destination = context.createMediaStreamDestination();
      oscillator.frequency.value = 440;
      oscillator.connect(destination);
      oscillator.start();
      let resolve;
      const completed = new Promise(r => resolve = r);
      const controller = new RecordingController({
        getUserMedia:async () => destination.stream,
        Recorder:MediaRecorder
      });
      await controller.start(async (blob, seconds) => {
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = '';
        for (const byte of bytes) binary += String.fromCharCode(byte);
        window.audioCapture.clips.push({name, seconds, type:blob.type, size:blob.size, base64:btoa(binary)});
        resolve();
      });
      setTimeout(() => controller.stop(), milliseconds);
      await completed;
      oscillator.stop();
      await context.close();
    }
    window.audioCapture.done = true;
  })().catch(() => {window.audioCapture.error = true; window.audioCapture.done = true;});
  return {started:true, source:'Web Audio oscillator', recorder:'actual app RecordingController'};
})()
""")
browser("wait", "--fn", "window.audioCapture.done === true")
result = browser("eval", "--stdin", source="JSON.stringify(window.audioCapture)")
result = result.get("result", result)
if isinstance(result, str):
    result = json.loads(result)
if result.get("error") or len(result.get("clips", [])) != 3:
    raise RuntimeError("Browser did not produce all three fixtures")
folder = ROOT / "backend/tests/fixtures"
folder.mkdir(parents=True, exist_ok=True)
metadata = []
for clip in result["clips"]:
    path = folder / ("chromium-" + clip["name"] + ".webm")
    path.write_bytes(base64.b64decode(clip.pop("base64"), validate=True))
    clip["filename"] = path.name
    metadata.append(clip)
(folder / "browser-audio.json").write_text(json.dumps({
    "source": "Web Audio oscillator through actual app RecordingController and Chromium MediaRecorder",
    "private_content": False,
    "clips": metadata,
}, indent=2) + "\n")
print(json.dumps(metadata, indent=2))
