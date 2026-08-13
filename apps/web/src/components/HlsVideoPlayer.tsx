import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";

export type HlsPlayerState = "idle" | "loading" | "ready" | "playing" | "ended" | "error";

type HlsVideoPlayerProps = {
  src: string;
  token: string;
  className?: string;
  autoPlay?: boolean;
  /** `once` is used for generated videos and starts at the oldest live window. */
  playbackMode?: "live" | "once";
  /** The source job has reached a terminal state and no new HLS media is expected. */
  streamEnded?: boolean;
  onStateChange?: (state: HlsPlayerState) => void;
};

function basicAuthorization(token: string): string | null {
  const value = token.trim();
  if (!value || typeof window === "undefined") return null;
  try {
    return `Basic ${window.btoa(value)}`;
  } catch {
    return null;
  }
}

function playerErrorMessage(token: string, status?: number): string {
  if (status === 401 || status === 403) {
    return "浏览器接收 Token 无效，请填写 reader:<读取密码>。";
  }
  return token.trim()
    ? "HLS 流尚未上线或已经结束，请重新生成视频；播放器会在发布期间自动等待。"
    : "HLS 需要浏览器接收 Token：reader:<读取密码>。";
}

export function HlsVideoPlayer({
  src,
  token,
  className = "aspect-video h-auto w-full object-contain",
  autoPlay = true,
  playbackMode = "live",
  streamEnded = false,
  onStateChange,
}: HlsVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playbackStartedRef = useRef(false);
  const mediaSessionStartedRef = useRef(false);
  const streamEndedRef = useRef(streamEnded);
  const endPlaybackRef = useRef<(() => void) | null>(null);
  const [state, setState] = useState<HlsPlayerState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    streamEndedRef.current = streamEnded;
    if (streamEnded) endPlaybackRef.current?.();
  }, [streamEnded]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src.trim()) {
      setState("idle");
      onStateChange?.("idle");
      return undefined;
    }

    let disposed = false;
    playbackStartedRef.current = false;
    mediaSessionStartedRef.current = false;
    const updateState = (next: HlsPlayerState) => {
      if (disposed) return;
      setState(next);
      onStateChange?.(next);
    };
    const authorization = basicAuthorization(token);
    const oncePlayback = playbackMode === "once";
    setError(null);
    updateState("loading");

    const onPlaying = () => {
      mediaSessionStartedRef.current = true;
      playbackStartedRef.current = true;
      updateState("playing");
    };
    const onTimeUpdate = () => {
      // A live HLS stream can emit `waiting` while the next segment is being
      // appended even though playback has already advanced. Do not replace a
      // healthy playing state with a permanent loading spinner in that case.
      if (video.currentTime > 0 && !video.paused) {
        mediaSessionStartedRef.current = true;
        playbackStartedRef.current = true;
        updateState("playing");
      }
    };
    const onCanPlay = () => {
      mediaSessionStartedRef.current = true;
      if (!video.paused && video.currentTime > 0) updateState("playing");
    };
    const onWaiting = () => {
      if (!playbackStartedRef.current) updateState("loading");
    };
    video.addEventListener("playing", onPlaying);
    video.addEventListener("timeupdate", onTimeUpdate);
    video.addEventListener("waiting", onWaiting);
    video.addEventListener("canplay", onCanPlay);

    let hls: Hls | null = null;
    let retryTimer: number | null = null;
    let retryCount = 0;
    let retryStopped = false;

    const stopHls = () => {
      hls?.destroy();
      hls = null;
    };

    const scheduleRetry = (message = "正在等待 HLS 生成可播放分片，请保持视频任务处于发布中…") => {
      if (disposed || retryStopped || retryTimer !== null) return;
      retryCount += 1;
      if (retryCount > 30) {
        setError(
          (playbackStartedRef.current || mediaSessionStartedRef.current)
            ? "HLS 播放会话暂时不可用，请确认 RTMPS 仍在发布。"
            : playerErrorMessage(token),
        );
        updateState("error");
        return;
      }
      stopHls();
      setError(message);
      updateState("loading");
      retryTimer = window.setTimeout(() => {
        retryTimer = null;
        mountHls();
      }, Math.min(2500, 500 + retryCount * 200));
    };

    const markEnded = () => {
      if (disposed || retryStopped) return;
      retryStopped = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
        retryTimer = null;
      }
      // Keep the MediaSource attached so the last buffered HLS media remains
      // visible/audible until the user leaves the preview. Cleanup still
      // destroys the instance when the component is actually unmounted.
      hls?.stopLoad();
      setError("HLS 发布已完成，浏览器预览已结束；请查看下方 MP4。");
      updateState("ended");
    };
    endPlaybackRef.current = markEnded;

    if (streamEndedRef.current) {
      markEnded();
    }

    const mountHls = () => {
      if (disposed || retryStopped) return;
      if (!Hls.isSupported()) return;
      const hlsConfig = {
        enableWorker: true,
        // MediaMTX serves standard fMP4 HLS. The once-mode target
        // latency is deliberately large so hls.js clamps to the oldest
        // segment still in the live window instead of jumping to live edge
        // and dropping the first few seconds of the generated video.
        lowLatencyMode: false,
        // Do not let hls.js auto-tune a live start position before the
        // manifest handler can select the oldest available segment for an
        // offline once-through video.
        autoStartLoad: !oncePlayback,
        startPosition: oncePlayback ? 0 : -1,
        backBufferLength: oncePlayback ? 60 : 30,
        ...(oncePlayback
          ? { liveSyncDuration: 60, liveMaxLatencyDuration: 90, liveSyncMode: "buffered" as const, initialLiveManifestSize: 1 }
          : { liveSyncDurationCount: 1, liveMaxLatencyDurationCount: 3 }),
        xhrSetup: (xhr: XMLHttpRequest) => {
          // MediaMTX performs a cookie-check redirect before serving the
          // playlist and child playlists. The player is cross-origin from
          // the Studio page, so explicitly keep that cookie on every HLS
          // request in addition to the Basic Authorization header.
          xhr.withCredentials = true;
          if (authorization) xhr.setRequestHeader("Authorization", authorization);
        },
      };
      hls = new Hls(hlsConfig);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        mediaSessionStartedRef.current = true;
        retryCount = 0;
        setError(null);
        updateState("ready");
        if (oncePlayback) hls?.startLoad(0);
        if (autoPlay) {
          void video.play().catch(() => {
            // Browser autoplay policy may require the user to press play.
          });
        }
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        const status = data.response?.code;
        if (status === 401 || status === 403) {
          if (streamEndedRef.current) {
            markEnded();
          } else if (playbackStartedRef.current || mediaSessionStartedRef.current) {
            // MediaMTX retires a live HLS session when its current window is
            // replaced. A 401/403 after media has already played is therefore
            // often a stale session, not a bad reader token. Recreate the
            // session while the source job is still active.
            scheduleRetry(
              playbackStartedRef.current || mediaSessionStartedRef.current
                ? "HLS 播放会话已更新，正在重新连接…"
                : "正在等待 HLS 流上线，请保持视频任务处于发布中…",
            );
          } else {
            // A 401/403 before any HLS manifest was accepted is an actual
            // reader-auth failure. Keep the actionable token message for this
            // initial-auth case only.
            stopHls();
            setError(playerErrorMessage(token, status));
            updateState("error");
          }
          return;
        }
        const waitingForManifest = [
          "manifestLoadError",
          "manifestLoadTimeOut",
          "levelLoadError",
          "levelLoadTimeOut",
        ].includes(data.details);
        // HLS playlist reloads can be canceled when the next reload
        // supersedes them; remounting the MediaSource here causes a visible
        // spinner and can lose the already buffered beginning.
        const mediaAlreadyPlaying = playbackStartedRef.current || mediaSessionStartedRef.current;
        if (data.fatal || (waitingForManifest && !mediaAlreadyPlaying)) scheduleRetry();
      });
      hls.attachMedia(video);
      hls.loadSource(src.trim());
    };

    const onEnded = () => {
      if (streamEndedRef.current || playbackStartedRef.current) markEnded();
    };
    video.addEventListener("ended", onEnded);

    if (Hls.isSupported()) {
      mountHls();
    } else if (video.canPlayType("application/vnd.apple.mpegurl") && !authorization) {
      // Safari can play HLS natively, but its HTMLMediaElement API does not
      // provide a safe way to attach Basic Auth to every playlist/segment.
      video.src = src.trim();
      video.addEventListener("loadedmetadata", () => {
        updateState("ready");
        if (autoPlay) void video.play().catch(() => undefined);
      }, { once: true });
    } else {
      setError(playerErrorMessage(token));
      updateState("error");
    }

    return () => {
      disposed = true;
      retryStopped = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      video.removeEventListener("playing", onPlaying);
      video.removeEventListener("timeupdate", onTimeUpdate);
      video.removeEventListener("waiting", onWaiting);
      video.removeEventListener("canplay", onCanPlay);
      video.removeEventListener("ended", onEnded);
      if (endPlaybackRef.current === markEnded) endPlaybackRef.current = null;
      stopHls();
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [autoPlay, onStateChange, playbackMode, src, token]);

  return (
    <div className="relative overflow-hidden rounded-xl bg-slate-950">
      <video ref={videoRef} controls playsInline preload="auto" className={className} />
      {state === "loading" ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-slate-950/75 px-3 py-2 text-xs text-white/80">
          {error ?? "正在加载 HLS 音视频…"}
        </div>
      ) : null}
      {state === "error" ? (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-950/90 px-5 text-center text-xs leading-relaxed text-red-200">
          {error ?? "HLS 播放失败。"}
        </div>
      ) : null}
    </div>
  );
}
