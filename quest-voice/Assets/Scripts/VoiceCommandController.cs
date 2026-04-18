// VoiceCommandController.cs
//
// Continuous voice capture + transcription on Meta Quest 3 / 3S using the
// Meta XR Voice SDK (Wit.ai). Streams partial + final transcripts to a
// RobotCommandClient, which forwards them over WebSocket to the LeRobot PC.
//
// Scene setup (done in the Unity Editor):
//   1) Add an empty GameObject "VoiceManager".
//   2) Add the "App Voice Experience" component (Meta Voice SDK).
//      - Assign a Wit Configuration asset (Window > Meta > Voice SDK > Wit
//        Configuration), paste your Wit.ai server access token.
//   3) Add this VoiceCommandController component to the same object and drag
//      the AppVoiceExperience reference into the inspector slot.
//   4) Add a RobotCommandClient component and wire it to this controller.
//
// Permission: the AndroidManifest in Assets/Plugins/Android already declares
// RECORD_AUDIO. On first run, the app requests it at runtime.

using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Android;
using Meta.WitAi;
using Meta.WitAi.Events;
using Oculus.Voice;

namespace StarkHacks.QuestVoice
{
    public class VoiceCommandController : MonoBehaviour
    {
        [Header("Voice SDK")]
        [Tooltip("Drag the AppVoiceExperience component here (Meta Voice SDK).")]
        [SerializeField] private AppVoiceExperience appVoice;

        [Header("Downstream")]
        [Tooltip("Receives final transcripts and forwards them to the robot.")]
        [SerializeField] private RobotCommandClient robotClient;

        [Header("Behaviour")]
        [Tooltip("Automatically re-activate listening after each utterance.")]
        [SerializeField] private bool continuousListening = true;

        [Tooltip("Delay (seconds) before restarting the mic after an utterance ends.")]
        [SerializeField] private float restartDelaySeconds = 0.25f;

        [Tooltip("Optional wake word. If non-empty, only transcripts containing this word trigger a command. Leave empty to forward all speech.")]
        [SerializeField] private string wakeWord = "";

        [Tooltip("Ignore transcripts shorter than this many characters (noise filter).")]
        [SerializeField] private int minTranscriptLength = 3;

        [Header("UI (optional)")]
        [Tooltip("Optional TMP text to show live partial transcript.")]
        [SerializeField] private TMPro.TMP_Text partialTranscriptLabel;

        [Tooltip("Optional TMP text to show latest final command.")]
        [SerializeField] private TMPro.TMP_Text finalCommandLabel;

        private string _lastCommand;
        private bool _micReady;

        private void Awake()
        {
            if (appVoice == null) appVoice = GetComponent<AppVoiceExperience>();
            if (robotClient == null) robotClient = GetComponent<RobotCommandClient>();
        }

        private void OnEnable()
        {
            if (appVoice == null)
            {
                Debug.LogError("[VoiceCommandController] AppVoiceExperience not assigned.");
                return;
            }

            var ev = appVoice.VoiceEvents;
            ev.OnPartialTranscription.AddListener(HandlePartial);
            ev.OnFullTranscription.AddListener(HandleFinal);
            ev.OnStartListening.AddListener(HandleStart);
            ev.OnStoppedListening.AddListener(HandleStop);
            ev.OnError.AddListener(HandleError);
        }

        private void OnDisable()
        {
            if (appVoice == null) return;
            var ev = appVoice.VoiceEvents;
            ev.OnPartialTranscription.RemoveListener(HandlePartial);
            ev.OnFullTranscription.RemoveListener(HandleFinal);
            ev.OnStartListening.RemoveListener(HandleStart);
            ev.OnStoppedListening.RemoveListener(HandleStop);
            ev.OnError.RemoveListener(HandleError);
        }

        private IEnumerator Start()
        {
            yield return RequestMicPermission();
            if (_micReady && continuousListening)
            {
                Activate();
            }
        }

        private IEnumerator RequestMicPermission()
        {
#if UNITY_ANDROID
            if (!Permission.HasUserAuthorizedPermission(Permission.Microphone))
            {
                Permission.RequestUserPermission(Permission.Microphone);
                // Wait up to ~5s for the system dialog.
                float t = 0f;
                while (!Permission.HasUserAuthorizedPermission(Permission.Microphone) && t < 5f)
                {
                    t += Time.deltaTime;
                    yield return null;
                }
            }
            _micReady = Permission.HasUserAuthorizedPermission(Permission.Microphone);
            if (!_micReady)
            {
                Debug.LogError("[VoiceCommandController] RECORD_AUDIO permission denied.");
            }
#else
            _micReady = true;
            yield break;
#endif
        }

        public void Activate()
        {
            if (appVoice == null || !_micReady) return;
            if (appVoice.Active) return;
            appVoice.Activate();
        }

        public void Deactivate()
        {
            if (appVoice == null) return;
            appVoice.Deactivate();
        }

        private void HandleStart()
        {
            Debug.Log("[VoiceCommandController] Listening…");
            if (partialTranscriptLabel != null) partialTranscriptLabel.text = "[listening]";
        }

        private void HandleStop()
        {
            if (continuousListening)
            {
                StartCoroutine(RestartAfterDelay());
            }
        }

        private IEnumerator RestartAfterDelay()
        {
            yield return new WaitForSeconds(restartDelaySeconds);
            Activate();
        }

        private void HandleError(string error, string message)
        {
            Debug.LogWarning($"[VoiceCommandController] Voice error: {error} / {message}");
            if (continuousListening) StartCoroutine(RestartAfterDelay());
        }

        private void HandlePartial(string transcription)
        {
            if (partialTranscriptLabel != null) partialTranscriptLabel.text = transcription;
        }

        private void HandleFinal(string transcription)
        {
            if (string.IsNullOrWhiteSpace(transcription)) return;

            var cleaned = transcription.Trim();
            if (cleaned.Length < minTranscriptLength) return;

            if (!string.IsNullOrEmpty(wakeWord))
            {
                if (cleaned.IndexOf(wakeWord, StringComparison.OrdinalIgnoreCase) < 0) return;
                cleaned = StripWakeWord(cleaned, wakeWord);
                if (cleaned.Length < minTranscriptLength) return;
            }

            if (cleaned.Equals(_lastCommand, StringComparison.OrdinalIgnoreCase)) return;
            _lastCommand = cleaned;

            Debug.Log($"[VoiceCommandController] Command: {cleaned}");
            if (finalCommandLabel != null) finalCommandLabel.text = cleaned;
            if (partialTranscriptLabel != null) partialTranscriptLabel.text = "";

            if (robotClient != null) robotClient.SendCommand(cleaned);
        }

        private static string StripWakeWord(string text, string wake)
        {
            int idx = text.IndexOf(wake, StringComparison.OrdinalIgnoreCase);
            if (idx < 0) return text;
            var tail = text.Substring(idx + wake.Length);
            return tail.TrimStart(' ', ',', '.', ':', ';');
        }
    }
}
