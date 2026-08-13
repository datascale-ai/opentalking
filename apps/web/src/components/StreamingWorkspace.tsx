import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  apiDeleteWithHeaders,
  apiGetWithHeaders,
  apiPostWithHeaders,
} from "../lib/api";
import type { ToastTone } from "./ToastStack";
import { HlsVideoPlayer, type HlsPlayerState } from "./HlsVideoPlayer";

type StreamingOutput = {
  output_id: string;
  session_id: string;
  type: "rtmps" | "whip" | string;
  name: string;
  connection_state: string;
  health: string;
  secret_configured: boolean;
  attempts: number;
  sent_video?: number;
  sent_audio?: number;
  bytes_sent?: number;
  last_error?: string | null;
};

type StreamingWorkspaceProps = {
  sessionId: string | null;
  sessionLive: boolean;
  onNotify?: (message: string, tone?: ToastTone) => void;
  onSendText?: (text: string) => void;
  onGoRealtime?: () => void;
};

const ENDPOINTS_STORAGE_KEY = "opentalking-streaming-endpoints-v1";

type EndpointPreferences = {
  rtmpsEndpoint: string;
  whipEndpoint: string;
  whepEndpoint: string;
  hlsEndpoint: string;
};

function browserHost(): string {
  if (typeof window === "undefined") return "127.0.0.1";
  return window.location.hostname || "127.0.0.1";
}

function defaultEndpoints(): EndpointPreferences {
  return {
    // Publishing is performed by the API process on the server, so its local
    // endpoint remains loopback. WHEP is called by the browser itself and
    // must use the host that served the page when the browser is remote.
    rtmpsEndpoint: "rtmps://127.0.0.1:1936/live",
    whipEndpoint: "https://127.0.0.1:8889/whip-test/whip",
    whepEndpoint: `https://${browserHost()}:8889/whip-test/whep`,
    hlsEndpoint: "/streaming/hls/live/rtmps-test/index.m3u8",
  };
}

function normalizeHlsEndpoint(value: string): string {
  const trimmed = value.trim();
  try {
    const parsed = new URL(trimmed, window.location.href);
    if (parsed.port === "8888" && parsed.pathname.startsWith("/live/")) {
      return `/streaming/hls${parsed.pathname}${parsed.search}`;
    }
  } catch {
    /* keep user-entered value for validation/error display */
  }
  return trimmed;
}

function readEndpointPreferences(): EndpointPreferences {
  const defaults = defaultEndpoints();
  try {
    const raw = window.localStorage.getItem(ENDPOINTS_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<EndpointPreferences>;
    const preferences = {
      ...defaults,
      ...Object.fromEntries(
        Object.entries(parsed).filter(
          ([key, value]) =>
            key !== "rtmpsStreamKey" && typeof value === "string" && value.trim(),
        ),
      ),
    } as EndpointPreferences;
    preferences.hlsEndpoint = normalizeHlsEndpoint(preferences.hlsEndpoint);
    if (
      !["127.0.0.1", "localhost"].includes(browserHost()) &&
      /^https:\/\/(127\.0\.0\.1|localhost):8889\//.test(preferences.whepEndpoint)
    ) {
      preferences.whepEndpoint = defaults.whepEndpoint;
    }
    return preferences;
  } catch {
    return defaults;
  }
}

function writeEndpointPreferences(preferences: EndpointPreferences): void {
  try {
    window.localStorage.setItem(ENDPOINTS_STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    /* localStorage is optional */
  }
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function stateLabel(value: string): string {
  switch (value) {
    case "connected":
      return "已连接";
    case "connecting":
      return "连接中";
    case "reconnecting":
      return "重连中";
    case "disconnected":
      return "已断开";
    case "failed":
      return "失败";
    default:
      return "待连接";
  }
}

function stateClass(value: string): string {
  switch (value) {
    case "connected":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    case "connecting":
    case "reconnecting":
      return "border-amber-200 bg-amber-50 text-amber-700";
    case "failed":
      return "border-red-200 bg-red-50 text-red-700";
    default:
      return "border-slate-200 bg-slate-50 text-slate-600";
  }
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "password";
  autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-slate-600">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100"
      />
    </label>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700"
      onClick={() => {
        if (!navigator.clipboard) return;
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
    >
      {copied ? "已复制" : "复制"}
    </button>
  );
}

export function StreamingWorkspace({
  sessionId,
  sessionLive,
  onNotify,
  onSendText,
  onGoRealtime,
}: StreamingWorkspaceProps) {
  const initialEndpoints = readEndpointPreferences();
  const [rtmpsEndpoint, setRtmpsEndpoint] = useState(initialEndpoints.rtmpsEndpoint);
  // Stream keys and bearer tokens are credentials. Keep them in component
  // state only; endpoint preferences are the only values persisted locally.
  const [rtmpsStreamKey, setRtmpsStreamKey] = useState("rtmps-test");
  const [rtmpsUsername, setRtmpsUsername] = useState("publisher");
  const [rtmpsPassword, setRtmpsPassword] = useState("");
  const [whipEndpoint, setWhipEndpoint] = useState(initialEndpoints.whipEndpoint);
  const [whipToken, setWhipToken] = useState("");
  const [whepEndpoint, setWhepEndpoint] = useState(initialEndpoints.whepEndpoint);
  const [whepToken, setWhepToken] = useState("");
  const [hlsEndpoint, setHlsEndpoint] = useState(initialEndpoints.hlsEndpoint);
  const [hlsToken, setHlsToken] = useState("");
  const [hlsReceiverActive, setHlsReceiverActive] = useState(false);
  const [hlsPlayerState, setHlsPlayerState] = useState<HlsPlayerState>("idle");
  const [controlToken, setControlToken] = useState("");
  const [readerUrl, setReaderUrl] = useState(
    "rtsp://reader:<reader-password>@127.0.0.1:8554/live/rtmps-test",
  );
  const [testText, setTestText] = useState("OpenTalking 流媒体测试");
  const [outputs, setOutputs] = useState<StreamingOutput[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receiverState, setReceiverState] = useState<"idle" | "connecting" | "live" | "error">("idle");
  const [receiverError, setReceiverError] = useState<string | null>(null);
  const [receiverStream, setReceiverStream] = useState<MediaStream | null>(null);
  const receiverPcRef = useRef<RTCPeerConnection | null>(null);
  const receiverResourceRef = useRef<string | null>(null);
  const receiverVideoRef = useRef<HTMLVideoElement>(null);
  const receiverStreamRef = useRef<MediaStream | null>(null);

  const notify = useCallback(
    (message: string, tone: ToastTone = "info") => onNotify?.(message, tone),
    [onNotify],
  );

  const authHeaders = useCallback((): Record<string, string> => {
    const token = controlToken.trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [controlToken]);

  const refreshOutputs = useCallback(async () => {
    if (!sessionId) {
      setOutputs([]);
      return;
    }
    setRefreshing(true);
    try {
      const next = await apiGetWithHeaders<StreamingOutput[]>(
        `/sessions/${encodeURIComponent(sessionId)}/outputs`,
        authHeaders(),
      );
      setOutputs(Array.isArray(next) ? next : []);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "流媒体输出读取失败"));
    } finally {
      setRefreshing(false);
    }
  }, [authHeaders, sessionId]);

  useEffect(() => {
    writeEndpointPreferences({ rtmpsEndpoint, whipEndpoint, whepEndpoint, hlsEndpoint });
  }, [hlsEndpoint, rtmpsEndpoint, whipEndpoint, whepEndpoint]);

  useEffect(() => {
    void refreshOutputs();
    if (!sessionId) return;
    const timer = window.setInterval(() => void refreshOutputs(), 1800);
    return () => window.clearInterval(timer);
  }, [refreshOutputs, sessionId]);

  useEffect(() => {
    const video = receiverVideoRef.current;
    if (!video) return;
    video.srcObject = receiverStream;
    if (receiverStream) {
      void video.play().catch(() => {
        /* Playback can require a second click in stricter browsers. */
      });
    }
  }, [receiverStream]);

  const stopReceiver = useCallback(async () => {
    const resource = receiverResourceRef.current;
    receiverResourceRef.current = null;
    if (resource && whepToken.trim()) {
      try {
        await fetch(resource, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${whepToken.trim()}` },
        });
      } catch {
        /* Closing the peer connection is sufficient for local playback. */
      }
    }
    receiverPcRef.current?.close();
    receiverPcRef.current = null;
    receiverStreamRef.current?.getTracks().forEach((track) => track.stop());
    receiverStreamRef.current = null;
    setReceiverStream(null);
    setReceiverState("idle");
  }, [whepToken]);

  useEffect(() => () => {
    receiverPcRef.current?.close();
    receiverStreamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  const waitForIceGathering = useCallback(async (pc: RTCPeerConnection) => {
    if (pc.iceGatheringState === "complete") return;
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        pc.removeEventListener("icegatheringstatechange", onChange);
        resolve();
      };
      const onChange = () => {
        if (pc.iceGatheringState === "complete") finish();
      };
      pc.addEventListener("icegatheringstatechange", onChange);
      window.setTimeout(finish, 5000);
    });
  }, []);

  const startReceiver = useCallback(async () => {
    const endpoint = whepEndpoint.trim();
    const token = whepToken.trim();
    if (!endpoint || !endpoint.startsWith("https://")) {
      setReceiverError("WHEP endpoint 必须使用 https://");
      setReceiverState("error");
      return;
    }
    await stopReceiver();
    setReceiverState("connecting");
    setReceiverError(null);
    const pc = new RTCPeerConnection();
    receiverPcRef.current = pc;
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });
    pc.ontrack = (event) => {
      const stream = event.streams[0] ?? receiverStreamRef.current ?? new MediaStream();
      if (!event.streams[0] && !stream.getTracks().some((track) => track.id === event.track.id)) {
        stream.addTrack(event.track);
      }
      receiverStreamRef.current = stream;
      setReceiverStream(stream);
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") setReceiverState("live");
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        setReceiverState("error");
        setReceiverError(`WHEP 连接状态：${pc.connectionState}`);
      }
    };
    pc.oniceconnectionstatechange = () => {
      if (["failed", "disconnected"].includes(pc.iceConnectionState)) {
        setReceiverState("error");
        setReceiverError(`WHEP ICE 连接失败：${pc.iceConnectionState}。请确认本地 harness 已映射 8189/udp 和 8190/tcp。`);
      }
    };
    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
      const local = pc.localDescription;
      if (!local?.sdp) throw new Error("浏览器没有生成有效的 WebRTC offer");
      const headers: Record<string, string> = {
        "Content-Type": "application/sdp",
        Accept: "application/sdp",
      };
      if (token) headers.Authorization = `Bearer ${token}`;
      const response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: local.sdp,
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`WHEP ${response.status}${detail ? `：${detail}` : ""}`);
      }
      const answer = await response.text();
      await pc.setRemoteDescription({ type: "answer", sdp: answer });
      const location = response.headers.get("Location");
      if (location) receiverResourceRef.current = new URL(location, endpoint).toString();
      setReceiverState("live");
      notify("WHEP 接收已连接，下面的视频区域正在播放。", "success");
    } catch (err) {
      pc.close();
      receiverPcRef.current = null;
      setReceiverState("error");
      const message = errorMessage(err, "WHEP 接收失败");
      setReceiverError(message.includes("CERTIFICATE") ? "浏览器不信任本地证书，请先打开 WHEP 地址并接受证书。" : message);
      notify(`WHEP 接收失败：${message}`, "error");
    }
  }, [notify, stopReceiver, waitForIceGathering, whepEndpoint, whepToken]);

  const toggleHlsReceiver = useCallback(() => {
    if (hlsReceiverActive) {
      setHlsReceiverActive(false);
      setHlsPlayerState("idle");
      return;
    }
    if (!hlsEndpoint.trim()) {
      notify("请填写 HLS 播放地址。", "info");
      return;
    }
    if (!hlsToken.trim()) {
      notify("请填写浏览器接收 Token：reader:<读取密码>。", "info");
      return;
    }
    setHlsReceiverActive(true);
  }, [hlsEndpoint, hlsReceiverActive, hlsToken, notify]);

  const handleHlsPlayerState = useCallback((next: HlsPlayerState) => {
    setHlsPlayerState(next);
  }, []);

  const createOutput = useCallback(
    async (type: "rtmps" | "whip") => {
      if (!sessionId) {
        notify("请先在“实时对话”中启动一个数字人会话。", "info");
        onGoRealtime?.();
        return;
      }
      if (!sessionLive) {
        notify("当前会话还没有进入实时状态，请稍候再试。", "info");
        return;
      }
      if (type === "rtmps" && (!rtmpsEndpoint.trim() || !rtmpsStreamKey.trim())) {
        notify("请填写 RTMPS endpoint 和 stream key。密码按目标服务要求填写即可。", "info");
        return;
      }
      if (type === "whip" && (!whipEndpoint.trim() || !whipToken.trim())) {
        notify("请填写 WHIP endpoint 和发布 Bearer Token。", "info");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const transport = type === "rtmps"
          ? {
              endpoint: rtmpsEndpoint.trim(),
              stream_key: rtmpsStreamKey.trim(),
              username: rtmpsUsername.trim() || undefined,
              password: rtmpsPassword.trim(),
            }
          : {
              endpoint: whipEndpoint.trim(),
              bearer_token: whipToken.trim(),
            };
        await apiPostWithHeaders(
          `/sessions/${encodeURIComponent(sessionId)}/outputs`,
          {
            type,
            name: type === "rtmps" ? "Studio RTMPS" : "Studio WHIP",
            auto_connect: true,
            transport,
          },
          {
            ...authHeaders(),
            "Idempotency-Key": `studio-${type}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          },
        );
        await refreshOutputs();
        notify(`${type.toUpperCase()} 输出已创建并开始连接。`, "success");
      } catch (err) {
        const message = errorMessage(err, `${type.toUpperCase()} 输出创建失败`);
        setError(message);
        notify(`${type.toUpperCase()} 输出失败：${message}`, "error");
      } finally {
        setLoading(false);
      }
    },
    [
      authHeaders,
      notify,
      onGoRealtime,
      refreshOutputs,
      rtmpsEndpoint,
      rtmpsPassword,
      rtmpsStreamKey,
      rtmpsUsername,
      sessionId,
      sessionLive,
      whipEndpoint,
      whipToken,
    ],
  );

  const mutateOutput = useCallback(
    async (output: StreamingOutput, action: "connect" | "disconnect" | "reconnect" | "delete") => {
      if (!sessionId) return;
      setLoading(true);
      try {
        const path = `/sessions/${encodeURIComponent(sessionId)}/outputs/${encodeURIComponent(output.output_id)}`;
        if (action === "delete") {
          await apiDeleteWithHeaders(path, {
            ...authHeaders(),
            "Idempotency-Key": `studio-delete-${output.output_id}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          });
        } else {
          await apiPostWithHeaders(
            `${path}/${action}`,
            {},
            {
              ...authHeaders(),
              "Idempotency-Key": `studio-${action}-${output.output_id}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            },
          );
        }
        await refreshOutputs();
      } catch (err) {
        const message = errorMessage(err, "输出操作失败");
        setError(message);
        notify(`输出操作失败：${message}`, "error");
      } finally {
        setLoading(false);
      }
    },
    [authHeaders, notify, refreshOutputs, sessionId],
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-slate-100 p-4 lg:p-6">
      <div className="mx-auto max-w-7xl space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-600">OpenTalking Streaming</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">流媒体发送与接收</h1>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-500">
                在这里把当前实时数字人会话推送到 RTMPS 或 WHIP。RTMPS 的 H.264/AAC 推荐通过 HLS 在浏览器中接收，WHIP 则通过 WHEP 接收。
                流媒体输出和实时对话共用同一个会话画面与音频。
              </p>
            </div>
            <div className={`rounded-xl border px-3 py-2 text-xs font-semibold ${sessionLive ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
              {sessionLive ? `实时会话：${sessionId}` : "尚未启动实时会话"}
            </div>
          </div>
          {!sessionLive ? (
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <span>请先启动实时对话，流媒体按钮才会把数字人画面接入发送端。</span>
              <button type="button" onClick={onGoRealtime} className="rounded-lg bg-amber-900 px-3 py-2 text-xs font-semibold text-white transition hover:bg-amber-800">
                返回实时对话
              </button>
            </div>
          ) : null}
        </section>

        <div className="grid gap-4 xl:grid-cols-2">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-950">发送端 · RTMPS</h2>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">OpenTalking 编码 H.264/AAC，并推送到 MediaMTX 或你的直播平台。</p>
              </div>
              <span className="rounded-full border border-orange-200 bg-orange-50 px-2.5 py-1 text-[11px] font-semibold text-orange-700">RTMPS</span>
            </div>
            <div className="mt-5 space-y-3">
              <Field label="推送 endpoint" value={rtmpsEndpoint} onChange={setRtmpsEndpoint} placeholder="rtmps://host:1936/live" />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Stream key" value={rtmpsStreamKey} onChange={setRtmpsStreamKey} />
                <Field label="发布用户名" value={rtmpsUsername} onChange={setRtmpsUsername} autoComplete="username" />
              </div>
              <Field label="发布密码（不会回显到输出列表）" value={rtmpsPassword} onChange={setRtmpsPassword} type="password" autoComplete="current-password" />
              <button type="button" disabled={loading || !sessionLive} onClick={() => void createOutput("rtmps")} className="w-full rounded-lg bg-orange-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:opacity-45">
                {loading ? "处理中..." : "连接 RTMPS 发送端"}
              </button>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-950">发送端 · WHIP</h2>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">通过 WebRTC WHIP 发布，适合实时数字人低延迟接入。</p>
              </div>
              <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-700">WHIP</span>
            </div>
            <div className="mt-5 space-y-3">
              <Field label="WHIP endpoint" value={whipEndpoint} onChange={setWhipEndpoint} placeholder="https://host:8889/path/whip" />
              <Field label="发布 Bearer Token" value={whipToken} onChange={setWhipToken} type="password" autoComplete="off" />
              <button type="button" disabled={loading || !sessionLive} onClick={() => void createOutput("whip")} className="w-full rounded-lg bg-violet-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-45">
                {loading ? "处理中..." : "连接 WHIP 发送端"}
              </button>
            </div>
          </section>
        </div>

        <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-950">接收端 · HLS 浏览器播放器（RTMPS 推荐）</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">RTMPS H.264/AAC → HLS，浏览器可同时播放画面和声音。HLS 比 WHEP 延迟略高，但不会丢掉 AAC 音频。</p>
            </div>
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${hlsPlayerState === "playing" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : hlsPlayerState === "error" ? "border-red-200 bg-red-50 text-red-700" : "border-cyan-200 bg-cyan-50 text-cyan-700"}`}>
              {hlsPlayerState === "playing" ? "播放中" : hlsPlayerState === "loading" ? "加载中" : hlsPlayerState === "ready" ? "已就绪" : hlsPlayerState === "ended" ? "已结束" : hlsPlayerState === "error" ? "失败" : "未播放"}
            </span>
          </div>
          <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)]">
            <div className="overflow-hidden rounded-xl bg-slate-950 shadow-inner">
              {hlsReceiverActive ? (
                <HlsVideoPlayer src={hlsEndpoint} token={hlsToken} onStateChange={handleHlsPlayerState} />
              ) : (
                <div className="flex aspect-video items-center justify-center px-6 text-center text-sm text-slate-400">点击“开始 HLS 接收”后，这里直接播放 RTMPS 的画面和声音。</div>
              )}
            </div>
            <div className="space-y-3">
              <Field label="HLS 播放地址（同源代理）" value={hlsEndpoint} onChange={setHlsEndpoint} placeholder="/streaming/hls/live/rtmps-test/index.m3u8" />
              <Field label="浏览器接收 Token（格式：reader:读取密码）" value={hlsToken} onChange={setHlsToken} type="password" autoComplete="off" />
              <button type="button" onClick={toggleHlsReceiver} className={`w-full rounded-lg px-3 py-2 text-xs font-semibold text-white ${hlsReceiverActive ? "bg-slate-700 hover:bg-slate-600" : "bg-cyan-700 hover:bg-cyan-600"}`}>
                {hlsReceiverActive ? "停止 HLS 接收" : "开始 HLS 接收"}
              </button>
              <p className="text-xs leading-relaxed text-slate-500">不需要点击“打开接收服务”，播放器会自动把 Token 放到 HLS 请求头中；浏览器只需在视频控件里点击播放即可出声。</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-950">输出连接管理</h2>
              <p className="mt-1 text-xs text-slate-500">输出密钥只在创建请求中使用，后端列表不会返回密钥。</p>
            </div>
            <button type="button" disabled={refreshing} onClick={() => void refreshOutputs()} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700 disabled:opacity-50">
              {refreshing ? "刷新中..." : "刷新状态"}
            </button>
          </div>
          {error ? <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p> : null}
          {outputs.length === 0 ? (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">当前会话还没有 RTMPS/WHIP 输出。</div>
          ) : (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {outputs.map((output) => (
                <div key={output.output_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase ${output.type === "whip" ? "border-violet-200 bg-violet-50 text-violet-700" : "border-orange-200 bg-orange-50 text-orange-700"}`}>{output.type}</span>
                      <span className="truncate text-sm font-semibold text-slate-900">{output.name}</span>
                    </div>
                    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${stateClass(output.connection_state)}`}>{stateLabel(output.connection_state)}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-lg bg-white px-3 py-2"><span className="text-slate-500">健康度</span><strong className="ml-2 text-slate-800">{output.health}</strong></div>
                    <div className="rounded-lg bg-white px-3 py-2"><span className="text-slate-500">尝试</span><strong className="ml-2 text-slate-800">{output.attempts}</strong></div>
                    <div className="rounded-lg bg-white px-3 py-2"><span className="text-slate-500">媒体帧</span><strong className="ml-2 text-slate-800">{output.sent_video ?? 0} / {output.sent_audio ?? 0}</strong></div>
                    <div className="rounded-lg bg-white px-3 py-2"><span className="text-slate-500">发送字节</span><strong className="ml-2 text-slate-800">{output.bytes_sent ? `${(output.bytes_sent / 1024).toFixed(1)} KB` : "—"}</strong></div>
                  </div>
                  {output.last_error ? <p className="mt-2 break-words text-xs text-red-600">{output.last_error}</p> : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {output.connection_state === "connected" ? (
                      <button type="button" disabled={loading} onClick={() => void mutateOutput(output, "disconnect")} className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:border-amber-200 hover:text-amber-700">断开</button>
                    ) : (
                      <button type="button" disabled={loading} onClick={() => void mutateOutput(output, "connect")} className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100">连接</button>
                    )}
                    <button type="button" disabled={loading} onClick={() => void mutateOutput(output, "reconnect")} className="rounded-md border border-cyan-200 bg-cyan-50 px-2.5 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100">重连</button>
                    <button type="button" disabled={loading} onClick={() => void mutateOutput(output, "delete")} className="rounded-md border border-red-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50">删除</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-950">接收端 · 浏览器 WHEP 播放器（WHIP 专用）</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">WHIP 流使用 H.264/Opus，通过 WHEP 可以低延迟播放画面和声音。RTMPS 流请使用上面的 HLS 播放器，不要在这里接收。</p>
            </div>
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${receiverState === "live" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : receiverState === "error" ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
              {receiverState === "live" ? "接收中" : receiverState === "connecting" ? "连接中" : receiverState === "error" ? "接收失败" : "未接收"}
            </span>
          </div>
          <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)]">
            <div className="overflow-hidden rounded-xl bg-slate-950 shadow-inner">
              <video ref={receiverVideoRef} autoPlay playsInline controls className={`aspect-video h-auto w-full object-contain ${receiverStream ? "block" : "hidden"}`} />
              {!receiverStream ? <div className="flex aspect-video items-center justify-center px-6 text-center text-sm text-slate-400">点击“开始 WHEP 接收”后，这里显示 MediaMTX 的实时画面。</div> : null}
            </div>
            <div className="space-y-3">
              <Field label="WHEP endpoint" value={whepEndpoint} onChange={setWhepEndpoint} placeholder="https://host:8889/path/whep" />
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setWhepEndpoint(defaultEndpoints().whepEndpoint)} className="rounded-md border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-[11px] font-semibold text-violet-700 hover:bg-violet-100">接收 WHIP 流</button>
                <button type="button" onClick={() => setWhepEndpoint("https://127.0.0.1:8889/live/rtmps-test/whep")} className="rounded-md border border-orange-200 bg-orange-50 px-2.5 py-1.5 text-[11px] font-semibold text-orange-700 hover:bg-orange-100">接收 RTMPS 流</button>
              </div>
              <Field label="接收 Bearer Token（格式：reader:读取密码）" value={whepToken} onChange={setWhepToken} type="password" autoComplete="off" />
              <div className="flex flex-wrap gap-2">
                {receiverState === "live" || receiverState === "connecting" ? (
                  <button type="button" onClick={() => void stopReceiver()} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:border-red-200 hover:text-red-700">停止接收</button>
                ) : (
                  <button type="button" onClick={() => void startReceiver()} className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800">开始 WHEP 接收</button>
                )}
                <a href={whepEndpoint.replace(/\/whep\/?$/, "")} target="_blank" rel="noreferrer" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:border-cyan-200 hover:text-cyan-700">打开接收服务</a>
              </div>
              {receiverError ? <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">{receiverError}</p> : null}
              <p className="text-xs leading-relaxed text-slate-500">本地 harness 填 `reader:&lt;读取密码&gt;`，不要填发布端 WHIP token。首次使用自签名证书时，请先在新标签页打开接收服务并接受证书提示，再回到这里点击开始。</p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
            <h2 className="text-base font-semibold text-slate-950">RTMPS 接收地址</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">RTMPS 是发布协议；浏览器查看发布流请使用上面的 HLS 播放器，HLS 保留 H.264/AAC。下面的 RTSP 地址仅用于 ffprobe 或文件级验收。</p>
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <code className="min-w-0 flex-1 break-all text-xs text-slate-700">{readerUrl}</code>
              <CopyButton value={readerUrl} />
            </div>
            <label className="mt-3 block"><span className="text-xs font-semibold text-slate-600">自定义查看地址（可选）</span><input value={readerUrl} onChange={(event) => setReaderUrl(event.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" /></label>
          </div>
          <div className="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-5 shadow-sm sm:p-6">
            <h2 className="text-base font-semibold text-slate-950">发送测试语句</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">使用当前实时会话发送一段文本，方便观察 RTMPS/HLS/WHEP 接收端是否同步出现媒体。</p>
            <div className="mt-4 flex gap-2"><input value={testText} onChange={(event) => setTestText(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:ring-2 focus:ring-cyan-100" /><button type="button" disabled={!sessionLive || !testText.trim()} onClick={() => onSendText?.(testText.trim())} className="rounded-lg bg-cyan-700 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-45">发送</button></div>
            <label className="mt-4 block"><span className="text-xs font-semibold text-slate-600">Streaming 控制 Token（生产环境需要；本地测试可留空）</span><input type="password" value={controlToken} onChange={(event) => setControlToken(event.target.value)} autoComplete="off" className="mt-1.5 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:ring-2 focus:ring-cyan-100" /></label>
          </div>
        </section>
      </div>
    </div>
  );
}
