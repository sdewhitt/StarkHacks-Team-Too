// RobotCommandClient.cs
//
// Bi-directional client for the Python voice_bridge_server:
//   - Streams transcribed voice commands from the Quest to the LeRobot PC:
//       { "type": "command", "text": "pick up the red block", "ts": 1713480000.123 }
//   - Optionally subscribes to live robot joint positions pushed by the bridge:
//       { "type": "subscribe_state", "hz": 30 }
//     and receives frames of the form:
//       {
//         "type": "joint_state", "ts": ..., "monotonic": ..., "version": 42,
//         "keys":   ["shoulder_pan.pos", ...],
//         "values": [12.34, ...]
//       }
//
// Uses System.Net.WebSockets.ClientWebSocket which ships with .NET Standard
// 2.1 / Unity 2022+ (no external package required). JSON is parsed with
// Unity's built-in JsonUtility; the server emits `keys`/`values` as parallel
// arrays specifically because JsonUtility doesn't support Dictionary<,>.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace StarkHacks.QuestVoice
{
    public class RobotCommandClient : MonoBehaviour
    {
        [Header("Connection")]
        [Tooltip("ws:// URL of the robot bridge. Use the PC's LAN IP, e.g. ws://192.168.1.42:8765")]
        [SerializeField] private string serverUrl = "ws://192.168.1.42:8765";

        [Tooltip("Attempt to auto-reconnect if the socket drops.")]
        [SerializeField] private bool autoReconnect = true;

        [Tooltip("Seconds between reconnect attempts.")]
        [SerializeField] private float reconnectDelay = 2f;

        [Header("Joint State Subscription")]
        [Tooltip("Ask the bridge to stream live joint positions after connect.")]
        [SerializeField] private bool subscribeToJointState = true;

        [Tooltip("Requested joint-state publish rate in Hz (server caps at 200).")]
        [Range(1f, 200f)]
        [SerializeField] private float jointStateHz = 30f;

        /// <summary>
        /// Raised on the Unity main thread whenever a fresh joint-state frame
        /// arrives from the bridge. Consumers should treat the dictionary as
        /// read-only; its identity may be reused across invocations.
        /// </summary>
        public event Action<JointStateSnapshot> OnJointStateUpdated;

        private ClientWebSocket _socket;
        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<string> _outbox = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<JointStateSnapshot> _inboundState = new ConcurrentQueue<JointStateSnapshot>();

        private readonly Dictionary<string, float> _latestPositions = new Dictionary<string, float>();
        private readonly object _latestPositionsLock = new object();
        private long _latestVersion = -1;
        private double _latestTs;
        private double _latestMonotonic;

        /// <summary>
        /// Most recently observed joint positions keyed by motor name
        /// (e.g. "shoulder_pan.pos"). Safe to read from any thread.
        /// </summary>
        public IReadOnlyDictionary<string, float> LatestJointPositions
        {
            get
            {
                lock (_latestPositionsLock)
                {
                    // Return a defensive copy so callers don't race with the
                    // socket thread mutating the underlying dict.
                    return new Dictionary<string, float>(_latestPositions);
                }
            }
        }

        public long LatestJointStateVersion => Interlocked.Read(ref _latestVersion);

        private void OnEnable()
        {
            _cts = new CancellationTokenSource();
            _ = RunAsync(_cts.Token);
        }

        private void OnDisable()
        {
            _cts?.Cancel();
            try { _socket?.Abort(); } catch { }
            _socket?.Dispose();
            _socket = null;
        }

        private void Update()
        {
            // Pump inbound state frames onto the main thread so subscribers
            // can touch Unity APIs safely.
            while (_inboundState.TryDequeue(out var snap))
            {
                OnJointStateUpdated?.Invoke(snap);
            }
        }

        public void SendCommand(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return;
            double ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            string payload = $"{{\"type\":\"command\",\"text\":{EscapeJsonString(text)},\"ts\":{ts.ToString(System.Globalization.CultureInfo.InvariantCulture)}}}";
            _outbox.Enqueue(payload);
        }

        public void SubscribeToJointState(float hz)
        {
            string payload = $"{{\"type\":\"subscribe_state\",\"hz\":{hz.ToString(System.Globalization.CultureInfo.InvariantCulture)}}}";
            _outbox.Enqueue(payload);
        }

        public void UnsubscribeFromJointState()
        {
            _outbox.Enqueue("{\"type\":\"unsubscribe_state\"}");
        }

        private async Task RunAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    await ConnectAsync(ct);

                    if (subscribeToJointState)
                    {
                        SubscribeToJointState(jointStateHz);
                    }

                    await PumpAsync(ct);
                }
                catch (OperationCanceledException) { }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[RobotCommandClient] Socket error: {ex.Message}");
                }

                if (!autoReconnect || ct.IsCancellationRequested) break;
                try { await Task.Delay(TimeSpan.FromSeconds(reconnectDelay), ct); } catch { }
            }
        }

        private async Task ConnectAsync(CancellationToken ct)
        {
            _socket?.Dispose();
            _socket = new ClientWebSocket();
            Debug.Log($"[RobotCommandClient] Connecting to {serverUrl} ...");
            await _socket.ConnectAsync(new Uri(serverUrl), ct);
            Debug.Log("[RobotCommandClient] Connected.");
        }

        private async Task PumpAsync(CancellationToken ct)
        {
            var recvBuf = new byte[8192];
            var assembly = new StringBuilder();

            while (!ct.IsCancellationRequested && _socket != null && _socket.State == WebSocketState.Open)
            {
                while (_outbox.TryDequeue(out var msg))
                {
                    var bytes = Encoding.UTF8.GetBytes(msg);
                    await _socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, ct);
                }

                if (_socket.State != WebSocketState.Open) break;

                var receiveTask = _socket.ReceiveAsync(new ArraySegment<byte>(recvBuf), ct);
                var delay = Task.Delay(10, ct);
                var completed = await Task.WhenAny(receiveTask, delay);
                if (completed != receiveTask) continue;

                WebSocketReceiveResult result;
                try { result = receiveTask.Result; }
                catch { return; }

                if (result.MessageType == WebSocketMessageType.Close)
                {
                    await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "bye", ct);
                    return;
                }

                if (result.MessageType != WebSocketMessageType.Text) continue;

                assembly.Append(Encoding.UTF8.GetString(recvBuf, 0, result.Count));
                if (!result.EndOfMessage) continue;

                string raw = assembly.ToString();
                assembly.Clear();
                HandleInbound(raw);
            }
        }

        private void HandleInbound(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return;

            // Fast path: only attempt to parse joint_state frames. Unknown
            // frames (e.g. "ack") are ignored silently.
            // JsonUtility requires a matching field set; we use a permissive
            // DTO with optional fields.
            JointStateMessage msg;
            try { msg = JsonUtility.FromJson<JointStateMessage>(raw); }
            catch { return; }

            if (msg == null || msg.type != "joint_state") return;
            if (msg.keys == null || msg.values == null) return;
            int n = Math.Min(msg.keys.Length, msg.values.Length);
            if (n == 0) return;

            var snap = new JointStateSnapshot
            {
                Version = msg.version,
                TimestampUnix = msg.ts,
                MonotonicSeconds = msg.monotonic,
                Positions = new Dictionary<string, float>(n),
            };
            for (int i = 0; i < n; ++i)
            {
                snap.Positions[msg.keys[i]] = msg.values[i];
            }

            lock (_latestPositionsLock)
            {
                _latestPositions.Clear();
                foreach (var kv in snap.Positions) _latestPositions[kv.Key] = kv.Value;
                _latestTs = snap.TimestampUnix;
                _latestMonotonic = snap.MonotonicSeconds;
            }
            Interlocked.Exchange(ref _latestVersion, snap.Version);

            _inboundState.Enqueue(snap);
        }

        [Serializable]
        private class JointStateMessage
        {
            public string type;
            public double ts;
            public double monotonic;
            public long version;
            public string[] keys;
            public float[] values;
        }

        public struct JointStateSnapshot
        {
            public long Version;
            public double TimestampUnix;
            public double MonotonicSeconds;
            public Dictionary<string, float> Positions;
        }

        private static string EscapeJsonString(string s)
        {
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"':  sb.Append("\\\""); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.AppendFormat("\\u{0:X4}", (int)c);
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }
    }
}
