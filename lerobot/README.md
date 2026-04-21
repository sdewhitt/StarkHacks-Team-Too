# ControVirtual

ControVirtual is our fork of LeRobot focused on remote skilled labor: a worker in a Meta Quest 3S can see a live digital twin of the workspace and control a pair of LeRobot arms using natural-language voice commands.

## Inspiration

Skilled physical workers with years of experience, such as a welder, technician, or assembly operators, are irreplaceable.

However, if they're sick, they're unable to perform, and if their condition worsens, they aren't able to use their skill. In addition, the employer loses that experience on the factory floor.

We felt this deeply both during COVID-19 and the years that came after, and we aimed to solve it with ControVirtual.

## What it does

ControVirtual connects a skilled operator wearing a Meta Quest 3S to a pair of LeRobot arms, from anywhere. The operator can see a live, immersive 3D camera feed of the robot's physical environment inside their Quest headset. To minimize difficulty of onboarding, they can control it with natural language commands; in other words, they can talk to it like they're instructing a colleague.

Through this, any business with skilled workers can now retain them and their expertise, through illness, mobility limitations, or geographic distance, by investing only as much as a small number of Meta Quest headsets and a few pairs of LeRobot arms.

## How We Built It

The major components of our development include:

### Robot Movement

We used the LeRobot API and behavioral cloning pipeline to train the follower arm from a small set of human demonstrations. The goal was a policy that could generalize to novel object positions rather than replay fixed scripts, while running inference tasks fast enough to feel responsive in real time. We kept the architecture lightweight specifically to minimize latency and reduce the number of episodes needed to get a working deployment.

### Voice Control

Operator commands are captured on-device and processed through wit.ai, which parses natural speech into structured, precise motor commands for the arms.

### VR Visualization

The robot's camera feed is streamed in real time to the Meta Quest 3S and rendered as a full 3D scene inside the headset using Unity. Since the operator now has complete spatial visibility of the robot's environment, they are present in the scene itself, and now can focus only on their task. To stabilize this, we had to implement careful frame synchronization through the pipeline connecting the camera to Unity's rendering loop to minimize drift and latency.

### Server

A local Python TCP/IP server bridges the Quest, the wit.ai response, and the LeRobot API, keeping the entire setup fully local, which is minimizes latency and optimizes for enterprise adoption.

## System Architecture

```text
Meta Quest 3S (voice + VR)
   -> wit.ai transcript
   -> local TCP command bridge (port 8765)
   -> LeRobot policy + robot driver
   -> robot telemetry
   -> Quest digital twin + browser visualization
```

Relevant workspace components:

- `scripts/voice_bridge/voice_bridge_server.py`: command + joint state TCP bridge.
- `scripts/voice_bridge/fake_robot_state_feeder.py`: hardware-free telemetry simulator.
- `meta-quest-camera-feed/server.py`: camera stream + twin state endpoints.
- `meta-quest-camera-feed/ROBOT_STATE_INTEGRATION.md`: state payload schema.
- `quest-voice/`: Unity Quest app project.

## Challenges We Ran Into

The hardest challenge we faced was making our system practical for deployment in real-life scenarios, such as a factory. Given that an enterprise cannot realistically record thousands of episodes for all tasks, and that a pretrained model may not cleanly transfer to all environments, we had to design an algorithm for inference that could maintain our need for fast inference, while being able to learn from a very small number of episodes.

To solve this problem, we modified the standard Imitation Learning algorithm, to be able to learn from as few as 50 episodes, and prioritized diversity over quantity of episodes. More specifically, we restructured how demonstrations are sampled during training to maximize coverage of the task space, which allowed the policy to generalize from a small but well-curated dataset.

## Accomplishments

We're extremely proud of our implementation of VR visualization, specifically, minimizing latency from the robot in a 3D scene rendered from a private, local server, with no cloud infrastructure. We are also proud of the few-episode Imitation Learning algorithm, which makes our system applicable in real-life scenes.

## What We Learned

We learned key insights into training imitation learning, and other RL algorithms, such as the factors of quality and diversity of the dataset, and how to be able to create datasets that find the optimal fits for these parameters.

## What's next for Team Too

We plan to implement simulations: virtual replicas of the physical environment, in the headset, in order to onboard and train new workers faster, as well as be able to preview unfamiliar hardware safely. The biggest challenge, we estimate, will be creating a virtual replica on the headset, while matching every real detail perfectly.

## Quickstart (This Fork)

The fork spans multiple folders in this workspace, so run from your workspace root (the folder that contains `lerobot/`, `meta-quest-camera-feed/`, and `quest-voice/`):

```bash
cd .
```

### 1) Install dependencies

Core LeRobot environment (inside `lerobot/`):

```bash
cd lerobot
uv sync --locked --extra all
```

Voice-bridge extras (if needed):

```bash
cd .
python -m pip install -r scripts/voice_bridge/requirements.txt
```

### 2) Run a hardware-free end-to-end dry run

Terminal A (camera + digital twin HTTP server):

```bash
cd meta-quest-camera-feed
python server.py
```

Terminal B (fake robot telemetry + bridge):

```bash
cd .
python scripts/voice_bridge/fake_robot_state_feeder.py --host 0.0.0.0 --port 8765 --hz 30 --http-server http://127.0.0.1:5000
```

Then open `http://<your-lan-ip>:5000` in Quest Browser to verify the moving twin.

### 3) Run with real robot bridge

```bash
cd .
python scripts/voice_bridge/voice_bridge_server.py --host 0.0.0.0 --port 8765
```

For real hardware telemetry in this fork, use `scripts/voice_bridge/server_for_robot.py` after updating robot port/id in that file.

```bash
cd .
python scripts/voice_bridge/server_for_robot.py --host 0.0.0.0 --port 8765
```

### 4) Quest app setup

Use the Unity project in `quest-voice/` and follow `quest-voice/README.md` for headset build, wit.ai configuration, and microphone permissions.

## Policy Training Notes

You can still use standard LeRobot training/eval commands from upstream docs. Example pattern:

```bash
cd lerobot
uv run lerobot-train --policy=act --dataset.repo_id=<your_dataset_repo>
```

For this fork, the key change is not a brand-new policy family but a low-data curation/training process tuned for deployment with small, diverse episode sets.

## Built With

- imitation-learning
- natural-language-processing
- python
- pytorch
- tcp-ip
- unity
- wit.ai

## Additional demo context

Today, if a 40-year-old factory worker gets disabled, they have to leave and possibly retire. Even the employer loses ears of expertise on the floor. Contraverirtual solves this. Contraverirtual puts the worker back in the scene using a MetaQuest 3S, a private server, and a pair of robot arms on site. They can see a three-dimensional realtime visualization of the space and control it with voice commands, all in natural language. At first we tried out the small VA model which is vision language action which received a prompt and translates that into an action and then we decided to fine-tune the model based on a set of episodes which we recorded. We recorded 50 episodes in which the robot picks up a screwdriver and moves it to a randomly placed piece of paper. Then we fine-tuned it on the AMD GPU cluster courtesy of AMD. As you can see, it's working pretty well. In this video, the server sends over data to the robot arm to make the model of it move. Using a MetaQuest VR headset, the user is able to visualize a 3D model of the arm. Uh, as the user walks around, they can see the model in 3D space as well as pick it up and move it. When the user uh wants to see how the robot moves, they can see the movements mimicked. When the user has the headset on, their voice is recorded and using WIT AI, the uh transcription is then sent over a TCP server back to the host laptop, which is able to use um the text from their voice to inference the model and tell the robot arm what to do. >> Our skilled experts deserve to keep working with Controversial. they can today and still be as present in the scene as they would physically. Next, we're solving the overarching problem.

## Upstream Attribution

ControVirtual is built on top of [huggingface/lerobot](https://github.com/huggingface/lerobot). We keep LeRobot's Apache-2.0 license and acknowledge the upstream team for the core robotics framework.
