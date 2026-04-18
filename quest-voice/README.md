# Quest 3S Voice → LeRobot bridge

Captures the user's speech on the Meta Quest 3 / 3S using the **Meta XR
All-in-One SDK v85** (which bundles Voice SDK + Wit.ai), streams the live
transcription over WebSocket to the PC running LeRobot, and feeds the
transcript as the `task` prompt for the SmolVLA policy driving the arm.

```
  Quest 3S  ─ mic ─▶  AppVoiceExperience (Voice SDK)
                         │  partial / full transcripts
                         ▼
                  VoiceCommandController  ──▶  RobotCommandClient
                                                     │   WebSocket JSON
                                                     ▼
                                 voice_bridge_server.py  ──▶  SmolVLA (task=text)
```

---

## 1. Prerequisites

On your dev machine (Mac or Windows):

- **Unity Hub** + **Unity 6.0 LTS (6000.0.x)** with **Android Build Support**
  (includes Android SDK/NDK and OpenJDK). Unity 2022.3 LTS also works if you
  change `ProjectSettings/ProjectVersion.txt`.
- **ADB** (comes with Android SDK) for sideloading to the headset.
- The Quest **must be in Developer Mode** and connected via USB-C (or over
  Wi-Fi with `adb tcpip`).

On the Quest 3S:

- Quest OS v68+ (anything from 2024 on).
- Paired with a **Meta Developer account** + Developer Mode enabled.

One free account you need:

- **Wit.ai** at <https://wit.ai>. Create an app, go to *Settings*, copy the
  **Server Access Token** — you'll paste it into Unity in a minute.

---

## 2. Open the Unity project

```bash
# From the repo root
open -a "Unity Hub"   # or launch Unity Hub manually
# In Unity Hub: "Add project from disk" -> select the quest-voice/ folder
```

When Unity opens the project the first time it will **download the Meta XR
All-in-One SDK (v85.0.0)** automatically because it's pinned in
`Packages/manifest.json`. This takes a few minutes the first time.

If Unity complains about the editor version, either install Unity
**6000.0.36f1** via Unity Hub, or edit `ProjectSettings/ProjectVersion.txt` to
a 6.0 LTS or 2022.3 LTS version you already have installed.

### Run the Meta XR Project Setup Tool

After the SDK installs, Unity menu bar:

1. **Edit → Project Settings → XR Plug-in Management → Android** → check
   **Oculus**.
2. **Meta → Tools → Project Setup Tool** → click **Fix All** and **Apply All**
   for both *Outstanding Issues* and *Recommended Items*. This configures:
   - IL2CPP + ARM64
   - Android min SDK 29, target SDK 32+
   - Quest feature flags, graphics API (Vulkan), color space (Linear)
   - Microphone permission entry
3. Ensure **Microphone** is ticked in **Meta → Voice SDK → Settings** (or
   equivalently in the Oculus plugin settings).

### Paste the Wit.ai token

1. **Window → Meta → Voice SDK → Settings** (or **Assets → Create → Voice SDK
   → Configuration** if not present).
2. Create a **Wit Configuration** asset and paste the **Server Access Token**
   from your Wit.ai app.

### Build the scene

1. Open a new empty scene (or `SampleScene`).
2. Add the **OVRCameraRig** from `Meta XR Core SDK/Prefabs` (or **Building
   Blocks → Camera Rig** via the Meta menu). Delete the default `Main Camera`.
3. Create an empty GameObject called **VoiceManager** and add:
   - Component: **App Voice Experience** (Meta Voice SDK). Assign your Wit
     Configuration asset.
   - Component: **Voice Command Controller** (our script). Drag the App Voice
     Experience into the `Voice` slot.
   - Component: **Robot Command Client** (our script). Set `Server Url` to
     `ws://<PC-LAN-IP>:8765`, e.g. `ws://192.168.1.42:8765`. Drag this
     component into the `Robot Client` slot on `VoiceCommandController`.
4. (Optional but nice) Create a world-space Canvas with two TextMeshPro
   labels, wire them into the `Partial Transcript Label` and
   `Final Command Label` fields so you can see what the Quest heard.

### Build & run

1. **File → Build Settings → Android → Switch Platform**.
2. Plug in the Quest over USB and select it in **Run Device**.
3. Click **Build And Run**. Approve the ADB install on-headset; put the
   headset on and approve the **Microphone** permission when prompted.

---

## 3. Start the bridge on the LeRobot PC

```bash
# From the repo root
python -m pip install -r scripts/voice_bridge/requirements.txt

# Minimal standalone server (no robot yet - great for testing the Quest side)
python scripts/voice_bridge/voice_bridge_server.py --host 0.0.0.0 --port 8765
```

Speak into the Quest — you should see lines like:

```
2026-04-18 20:10:11,240 INFO voice_bridge: client connected: ('192.168.1.88', 48022)
2026-04-18 20:10:15,118 INFO voice_bridge: command: pick up the red block
```

Also watch `outputs/voice/latest_command.json` — it's updated on every
utterance.

### Firewall

The PC must accept inbound TCP on port **8765**. On macOS:

```bash
# allow python in System Settings > Network > Firewall, or:
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$(which python)"
```

---

## 4. Plug the transcripts into SmolVLA

`scripts/voice_bridge/run_smolvla_voice.py` is the reference loop: it starts
the bridge in a thread, loads `lerobot/smolvla_base`, and calls
`policy.select_action(...)` with the latest voice transcript as the `task`
prompt.

You need to fill in `_build_frame(task)` with real camera + proprio reads from
your arm. For a drop-in alternative you can use the official `lerobot-record`
entry point:

```bash
lerobot-record \
  --robot.type=so100_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.cameras="{ up: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}}" \
  --robot.id=my_arm \
  --dataset.repo_id=${HF_USER}/eval_voice \
  --dataset.single_task="$(jq -r .text outputs/voice/latest_command.json)" \
  --policy.path=lerobot/smolvla_base
```

…and re-invoke it whenever a new command is produced (or patch it to poll the
state file in its loop).

### Quick dry-run without the robot

```bash
python scripts/voice_bridge/run_smolvla_voice.py --dry-run
```

Every utterance prints `would dispatch task=... to SmolVLA`.

---

## 5. Gotchas

- **"Cannot connect to ws://…"** on the Quest: the PC firewall is blocking,
  the PC is on a different Wi-Fi, or you typed a stale LAN IP. Re-check the IP
  with `ipconfig getifaddr en0` (macOS) and make sure Quest + PC are on the
  same subnet. `cleartext-traffic="true"` in the AndroidManifest already
  allows non-TLS `ws://`.
- **No transcripts coming through**: open the headset's `adb logcat` and
  filter on `Wit` or `VoiceCommandController`. 401 from Wit means a bad
  server-access token; permission-denied means the mic permission was never
  granted (uninstall and reinstall the APK).
- **Latency**: partial transcripts are ~100 ms; final transcripts fire on
  ~800 ms of silence. If you want snappier commands, lower `Min Volume` /
  `End of speech timeout` in the `App Voice Experience` component.
- **Background mic capture is not allowed on Quest.** Our app has to be the
  foreground immersive app for the mic to stream.
- **Wake word** (optional) is set via the `Wake Word` field on
  `VoiceCommandController`. Leave empty to forward every utterance.
