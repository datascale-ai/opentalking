import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AvatarSummary, ExportVideoItem } from "../lib/api";
import { ApiError, apiPostForm, buildApiUrl, buildWsUrl, uploadExportVideo } from "../lib/api";
import type { FasterLivePortraitConfig } from "./SettingsPanel";

const MAGIC_FRAME = new TextEncoder().encode("FRAM");
const MAGIC_VIDEO = "VIDX";

type VideoCloneWorkspaceProps = {
  avatars: AvatarSummary[];
  avatarId: string;
  config: FasterLivePortraitConfig;
  onAvatarChange: (id: string) => void;
  onAvatarUploaded: (avatar: AvatarSummary) => void;
  onConfigChange: (config: FasterLivePortraitConfig) => void;
  onExportCreated?: (item: ExportVideoItem) => void;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
};

type CameraDevice = { deviceId: string; label: string };
type CloneStatus = "idle" | "requesting" | "connecting" | "live" | "error";
type VideoStartSource = "camera" | "upload";
type RuntimeConfigUpdate = Partial<FasterLivePortraitConfig> & { flag_crop_driving_video?: boolean };

const FPS_OPTIONS = [8, 12, 15, 20];
const RESOLUTION_OPTIONS = [360, 448, 512];
const ANIMATION_REGION_OPTIONS: { id: FasterLivePortraitConfig["animation_region"]; label: string }[] = [
  { id: "all", label: "全表情" },
  { id: "exp", label: "表情" },
  { id: "pose", label: "姿态" },
  { id: "lip", label: "嘴部" },
  { id: "eyes", label: "眼睛" },
];
const VIDEO_CLONE_SLIDERS: {
  key: Exclude<keyof FasterLivePortraitConfig, "animation_region" | "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">;
  label: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { key: "driving_multiplier", label: "动作幅度", min: 0, max: 2, step: 0.05 },
  { key: "expression_multiplier", label: "表情幅度", min: 0, max: 3, step: 0.05 },
  { key: "head_motion_multiplier", label: "头动幅度", min: 0, max: 2, step: 0.05 },
  { key: "mouth_open_multiplier", label: "张嘴开合", min: 0, max: 3, step: 0.05 },
  { key: "yaw_multiplier", label: "左右摇头", min: 0, max: 2, step: 0.05 },
  { key: "pitch_multiplier", label: "上下点头", min: 0, max: 2, step: 0.05 },
  { key: "roll_multiplier", label: "左右歪头", min: 0, max: 2, step: 0.05 },
  { key: "cfg_scale", label: "CFG Scale", min: 0, max: 10, step: 0.25 },
];
const VIDEO_CLONE_SWITCHES: {
  key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">;
  label: string;
}[] = [
  { key: "flag_pasteback", label: "拼回原图" },
  { key: "flag_stitching", label: "Stitching" },
  { key: "flag_relative_motion", label: "相对运动" },
  { key: "flag_normalize_lip", label: "唇形归一" },
  { key: "flag_lip_retargeting", label: "唇形重定向" },
];

function concatFramePayload(frame: ArrayBuffer): Uint8Array {
  const payload = new Uint8Array(MAGIC_FRAME.length + frame.byteLength);
  payload.set(MAGIC_FRAME, 0);
  payload.set(new Uint8Array(frame), MAGIC_FRAME.length);
  return payload;
}

function parseVideoPayload(payload: ArrayBuffer): Blob[] {
  const bytes = new Uint8Array(payload);
  const magic = new TextDecoder().decode(bytes.slice(0, 4));
  if (magic !== MAGIC_VIDEO || bytes.byteLength < 8) return [];
  const view = new DataView(payload);
  const count = view.getUint32(4, true);
  let offset = 8;
  const frames: Blob[] = [];
  for (let i = 0; i < count; i += 1) {
    if (offset + 4 > bytes.byteLength) break;
    const length = view.getUint32(offset, true);
    offset += 4;
    if (length <= 0 || offset + length > bytes.byteLength) break;
    frames.push(new Blob([bytes.slice(offset, offset + length)], { type: "image/jpeg" }));
    offset += length;
  }
  return frames;
}

function videoCloneStartErrorMessage(error: unknown, source: VideoStartSource): string {
  const name = error instanceof DOMException ? error.name : "";
  const message = error instanceof Error ? error.message : String(error);
  if (source === "upload") {
    return `无法播放上传视频：${message || "请确认文件格式可被当前浏览器播放。"}`;
  }
  if (name === "NotAllowedError" || name === "SecurityError") return "摄像头权限被拒绝。请在浏览器地址栏允许摄像头访问，或改用上传 driving video。";
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "未检测到可用摄像头。请连接摄像头，或改用上传 driving video。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "摄像头正被其他应用占用，关闭占用后重试，或改用上传 driving video。";
  }
  if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
    return "所选摄像头不可用，已尝试默认摄像头仍失败。请切换摄像头或改用上传 driving video。";
  }
  if (name === "NotSupportedError" || !navigator.mediaDevices?.getUserMedia) {
    return "当前浏览器或访问地址不支持摄像头。请使用本机 http://127.0.0.1 访问，或改用上传 driving video。";
  }
  return `启动失败：${message || "请检查摄像头权限、浏览器访问地址和视频克隆服务。"}`;
}

function normalizeVideoCloneConfigChange(nextConfig: FasterLivePortraitConfig): FasterLivePortraitConfig {
  if (nextConfig.flag_lip_retargeting && nextConfig.flag_relative_motion) {
    return { ...nextConfig, flag_relative_motion: false };
  }
  return nextConfig;
}

function sourceAvatarNameFromFile(file: File): string {
  const stem = file.name.replace(/\.[^.]+$/, "").trim();
  return stem ? `视频克隆 ${stem}` : "视频克隆 source";
}

function selectMediaRecorderMimeType(candidates: string[]): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
}

function outputRecordTitle(avatar: AvatarSummary | null): string {
  return `视频克隆录制 · ${avatar?.name ?? avatar?.id ?? "未命名形象"}`;
}

export function VideoCloneWorkspace({
  avatars,
  avatarId,
  config,
  onAvatarChange,
  onAvatarUploaded,
  onConfigChange,
  onExportCreated,
  onNotify,
}: VideoCloneWorkspaceProps) {
  const selectedAvatar = avatars.find((avatar) => avatar.id === avatarId) ?? avatars[0] ?? null;
  const [status, setStatus] = useState<CloneStatus>("idle");
  const [statusText, setStatusText] = useState("待启动");
  const [devices, setDevices] = useState<CameraDevice[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [fps, setFps] = useState(12);
  const [resolution, setResolution] = useState(448);
  const [mirror, setMirror] = useState(true);
  const [cropDriving, setCropDriving] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [sentFrames, setSentFrames] = useState(0);
  const [receivedFrames, setReceivedFrames] = useState(0);
  const [droppedFrames, setDroppedFrames] = useState(0);
  const [outputUrl, setOutputUrl] = useState<string | null>(null);
  const [outputRecording, setOutputRecording] = useState(false);
  const [outputRecordSaving, setOutputRecordSaving] = useState(false);
  const [uploadVideoUrl, setUploadVideoUrl] = useState<string | null>(null);
  const [uploadPreviewName, setUploadPreviewName] = useState("");
  const [sourceUploadBusy, setSourceUploadBusy] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const outputRecordCanvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const lastFrameSentAtRef = useRef(0);
  const outputUrlRef = useRef<string | null>(null);
  const latestOutputBlobRef = useRef<Blob | null>(null);
  const outputRecorderRef = useRef<MediaRecorder | null>(null);
  const outputRecordChunksRef = useRef<Blob[]>([]);
  const outputRecordStartedAtRef = useRef(0);
  const outputRecordTimerRef = useRef<number | null>(null);
  const outputRecordStreamRef = useRef<MediaStream | null>(null);
  const uploadVideoUrlRef = useRef<string | null>(null);
  const sourcePanelRef = useRef<HTMLElement | null>(null);

  const statusBadge = useMemo(() => {
    if (status === "live") return "border-emerald-200 bg-emerald-50 text-emerald-700";
    if (status === "connecting" || status === "requesting") return "border-amber-200 bg-amber-50 text-amber-700";
    if (status === "error") return "border-red-200 bg-red-50 text-red-700";
    return "border-slate-200 bg-slate-50 text-slate-600";
  }, [status]);

  const stopOutputRecording = useCallback(() => {
    const recorder = outputRecorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  const cleanupOutputRecordStream = useCallback(() => {
    if (outputRecordTimerRef.current !== null) {
      window.clearInterval(outputRecordTimerRef.current);
      outputRecordTimerRef.current = null;
    }
    if (outputRecordStreamRef.current) {
      for (const track of outputRecordStreamRef.current.getTracks()) track.stop();
      outputRecordStreamRef.current = null;
    }
  }, []);

  const drawLatestOutputFrame = useCallback(() => {
    const canvas = outputRecordCanvasRef.current;
    const blob = latestOutputBlobRef.current;
    if (!canvas || !blob) return;
    const img = new Image();
    img.onload = () => {
      const width = img.naturalWidth || selectedAvatar?.width || resolution;
      const height = img.naturalHeight || selectedAvatar?.height || resolution;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
      }
      URL.revokeObjectURL(img.src);
    };
    img.onerror = () => URL.revokeObjectURL(img.src);
    img.src = URL.createObjectURL(blob);
  }, [resolution, selectedAvatar?.height, selectedAvatar?.width]);

  const startOutputRecording = useCallback(() => {
    if (!selectedAvatar) {
      onNotify?.("请先选择数字人形象。", "info");
      return;
    }
    if (!latestOutputBlobRef.current) {
      onNotify?.("请先启动视频克隆并等待输出画面。", "info");
      return;
    }
    const canvas = outputRecordCanvasRef.current;
    if (!canvas) return;
    if (typeof MediaRecorder === "undefined" || !canvas.captureStream) {
      onNotify?.("当前浏览器不支持录制输出画面，请换用 Chrome。", "error");
      return;
    }
    if (outputRecorderRef.current?.state === "recording") return;
    cleanupOutputRecordStream();
    drawLatestOutputFrame();
    const stream = canvas.captureStream(fps);
    outputRecordStreamRef.current = stream;
    const mimeType = selectMediaRecorderMimeType([
      "video/mp4;codecs=avc1.42E01E",
      "video/mp4",
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
    ]);
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    outputRecordChunksRef.current = [];
    outputRecordStartedAtRef.current = performance.now();
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) outputRecordChunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const chunks = outputRecordChunksRef.current;
      outputRecordChunksRef.current = [];
      outputRecorderRef.current = null;
      cleanupOutputRecordStream();
      setOutputRecording(false);
      if (!chunks.length) {
        onNotify?.("录制内容为空，未生成导出视频。", "error");
        return;
      }
      const durationSec = Math.max(0.1, (performance.now() - outputRecordStartedAtRef.current) / 1000);
      const blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
      setOutputRecordSaving(true);
      void uploadExportVideo({
        blob,
        kind: "video_clone",
        title: outputRecordTitle(selectedAvatar),
        durationSec,
        avatarId: selectedAvatar.id,
        model: "fasterliveportrait",
      }).then((saved) => {
        onExportCreated?.(saved);
        onNotify?.(`视频克隆录制已保存，可在资产库查看：${saved.title}`, "success");
      }).catch((error) => {
        console.warn("upload video clone export failed", error);
        const detail = error instanceof ApiError ? error.detail : null;
        onNotify?.(detail ? `视频克隆录制上传失败：${detail}` : "视频克隆录制上传失败。", "error");
      }).finally(() => setOutputRecordSaving(false));
    };
    outputRecordTimerRef.current = window.setInterval(drawLatestOutputFrame, Math.max(20, Math.round(1000 / fps)));
    recorder.start(1000);
    outputRecorderRef.current = recorder;
    setOutputRecording(true);
    onNotify?.("已开始录制克隆输出画面。", "success");
  }, [cleanupOutputRecordStream, drawLatestOutputFrame, fps, onExportCreated, onNotify, selectedAvatar]);

  const stop = useCallback(() => {
    stopOutputRecording();
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "close" }));
        }
        wsRef.current.close();
      } catch {
        /* ignore */
      }
      wsRef.current = null;
    }
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop();
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
    }
    setStatus((prev) => (prev === "error" ? prev : "idle"));
    setStatusText("已停止");
  }, [stopOutputRecording]);

  useEffect(() => stop, [stop]);

  useEffect(() => {
    return () => {
      stopOutputRecording();
      cleanupOutputRecordStream();
      if (outputUrlRef.current) URL.revokeObjectURL(outputUrlRef.current);
      if (uploadVideoUrlRef.current) URL.revokeObjectURL(uploadVideoUrlRef.current);
    };
  }, [cleanupOutputRecordStream, stopOutputRecording]);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const all = await navigator.mediaDevices.enumerateDevices();
    const cameras = all
      .filter((device) => device.kind === "videoinput")
      .map((device, index) => ({ deviceId: device.deviceId, label: device.label || `摄像头 ${index + 1}` }));
    setDevices(cameras);
    if (!deviceId && cameras[0]) setDeviceId(cameras[0].deviceId);
  }, [deviceId]);

  useEffect(() => {
    void refreshDevices();
  }, [refreshDevices]);

  const sendFrame = useCallback(() => {
    const ws = wsRef.current;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !video || !canvas || video.readyState < 2) return;
    if (ws.bufferedAmount > 2_000_000) {
      setDroppedFrames((value) => value + 1);
      return;
    }
    const sourceWidth = video.videoWidth || resolution;
    const sourceHeight = video.videoHeight || resolution;
    const targetWidth = resolution;
    const targetHeight = Math.max(2, Math.round((sourceHeight / Math.max(1, sourceWidth)) * targetWidth));
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.save();
    const shouldMirrorFrame = mirror && !uploadVideoUrl;
    if (shouldMirrorFrame) {
      ctx.translate(targetWidth, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, 0, 0, targetWidth, targetHeight);
    ctx.restore();
    canvas.toBlob(
      async (blob) => {
        if (!blob || ws.readyState !== WebSocket.OPEN) return;
        lastFrameSentAtRef.current = performance.now();
        ws.send(concatFramePayload(await blob.arrayBuffer()));
        setSentFrames((value) => value + 1);
      },
      "image/jpeg",
      0.78,
    );
  }, [mirror, resolution, uploadVideoUrl]);

  const openCameraStream = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new DOMException("media devices unavailable", "NotSupportedError");
    }
    const baseVideo = {
      width: { ideal: resolution },
      frameRate: { ideal: fps, max: fps },
    };
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: {
          ...baseVideo,
          deviceId: deviceId ? { exact: deviceId } : undefined,
        },
        audio: false,
      });
    } catch (error) {
      if (!deviceId) throw error;
      return navigator.mediaDevices.getUserMedia({
        video: baseVideo,
        audio: false,
      });
    }
  }, [deviceId, fps, resolution]);

  const sendRuntimeConfigUpdate = useCallback((runtimeConfig: RuntimeConfigUpdate) => {
    const ws = wsRef.current;
    if (status !== "live" || !ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({ type: "config_update", config: runtimeConfig }));
    } catch {
      /* ignore */
    }
  }, [status]);

  const handleConfigChange = useCallback((nextConfig: FasterLivePortraitConfig) => {
    const normalizedConfig = normalizeVideoCloneConfigChange(nextConfig);
    onConfigChange(normalizedConfig);
    sendRuntimeConfigUpdate(normalizedConfig);
  }, [onConfigChange, sendRuntimeConfigUpdate]);

  const handleCropDrivingChange = useCallback((checked: boolean) => {
    setCropDriving(checked);
    sendRuntimeConfigUpdate({ flag_crop_driving_video: checked });
  }, [sendRuntimeConfigUpdate]);

  const start = useCallback(async () => {
    if (!selectedAvatar) {
      onNotify?.("请先选择一个数字人形象。", "info");
      return;
    }
    stop();
    setSentFrames(0);
    setReceivedFrames(0);
    setDroppedFrames(0);
    setLatencyMs(null);
    setStatus("requesting");
    setStatusText("请求摄像头权限");
    const source: VideoStartSource = uploadVideoUrl ? "upload" : "camera";
    const initConfig = normalizeVideoCloneConfigChange(config);
    try {
      if (videoRef.current) {
        if (uploadVideoUrl) {
          videoRef.current.srcObject = null;
          videoRef.current.src = uploadVideoUrl;
          videoRef.current.loop = true;
        } else {
          const stream = await openCameraStream();
          streamRef.current = stream;
          videoRef.current.srcObject = stream;
          videoRef.current.removeAttribute("src");
          videoRef.current.loop = false;
          await refreshDevices();
        }
        await videoRef.current.play();
      }

      setStatus("connecting");
      setStatusText("连接视频克隆服务");
      const ws = new WebSocket(buildWsUrl("/video-clone/fasterliveportrait/ws"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify({
          type: "init",
          avatar_id: selectedAvatar.id,
          fps,
          width: selectedAvatar.width || resolution,
          height: selectedAvatar.height || resolution,
          flag_crop_driving_video: cropDriving,
          ...initConfig,
        }));
      };
      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          try {
            const message = JSON.parse(event.data);
            if (message.type === "init_ok") {
              setStatus("live");
              setStatusText("实时驱动中");
              timerRef.current = window.setInterval(sendFrame, Math.max(20, Math.round(1000 / fps)));
            } else if (message.type === "error") {
              setStatus("error");
              setStatusText(message.message || "视频克隆错误");
              onNotify?.(message.message || "视频克隆错误", "error");
            }
          } catch {
            /* ignore */
          }
          return;
        }
        const frames = parseVideoPayload(event.data as ArrayBuffer);
        const last = frames[frames.length - 1];
        if (!last) return;
        latestOutputBlobRef.current = last;
        const nextUrl = URL.createObjectURL(last);
        if (outputRecording) drawLatestOutputFrame();
        if (outputUrlRef.current) URL.revokeObjectURL(outputUrlRef.current);
        outputUrlRef.current = nextUrl;
        setOutputUrl(nextUrl);
        setReceivedFrames((value) => value + frames.length);
        if (lastFrameSentAtRef.current) setLatencyMs(Math.max(0, Math.round(performance.now() - lastFrameSentAtRef.current)));
      };
      ws.onerror = () => {
        setStatus("error");
        setStatusText("连接失败");
        onNotify?.("视频克隆连接失败，请检查后端和 OmniRT。", "error");
      };
      ws.onclose = () => {
        if (timerRef.current !== null) {
          window.clearInterval(timerRef.current);
          timerRef.current = null;
        }
        wsRef.current = null;
        setStatus((prev) => (prev === "live" || prev === "connecting" ? "idle" : prev));
      };
    } catch (error) {
      setStatus("error");
      const detail = videoCloneStartErrorMessage(error, source);
      setStatusText(detail);
      onNotify?.(detail, "error");
      stop();
      setStatus("error");
      setStatusText(detail);
    }
  }, [config, cropDriving, fps, onNotify, openCameraStream, refreshDevices, resolution, selectedAvatar, sendFrame, stop, uploadVideoUrl]);

  const handleReturnToAvatarSelection = useCallback(() => {
    stop();
    if (outputUrlRef.current) {
      URL.revokeObjectURL(outputUrlRef.current);
      outputUrlRef.current = null;
    }
    latestOutputBlobRef.current = null;
    setOutputUrl(null);
    setSentFrames(0);
    setReceivedFrames(0);
    setDroppedFrames(0);
    setLatencyMs(null);
    sourcePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [stop]);

  const handleSourceUpload = useCallback(async (file: File | null) => {
    if (!file) return;
    if (!selectedAvatar) {
      onNotify?.("请先选择一个基础数字人形象，再上传 source。", "info");
      return;
    }
    if (!file.type.startsWith("image/")) {
      onNotify?.("source 形象请上传图片文件。", "error");
      return;
    }
    stop();
    if (outputUrlRef.current) {
      URL.revokeObjectURL(outputUrlRef.current);
      outputUrlRef.current = null;
    }
    latestOutputBlobRef.current = null;
    setOutputUrl(null);
    setSentFrames(0);
    setReceivedFrames(0);
    setDroppedFrames(0);
    setLatencyMs(null);
    setSourceUploadBusy(true);
    try {
      const form = new FormData();
      form.set("base_avatar_id", selectedAvatar.id);
      form.set("name", sourceAvatarNameFromFile(file));
      form.set("model", "fasterliveportrait");
      form.set("image", file);
      const created = await apiPostForm<AvatarSummary>("/avatars/custom", form);
      onAvatarUploaded(created);
      onNotify?.(`已上传 source 形象「${created.name ?? created.id}」。`, "success");
    } catch (error) {
      console.warn("upload video clone source failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `上传 source 失败：${detail}` : "上传 source 失败，请查看后端日志。", "error");
    } finally {
      setSourceUploadBusy(false);
    }
  }, [onAvatarUploaded, onNotify, selectedAvatar, stop]);

  const handleUploadPreview = useCallback((file: File | null) => {
    if (!file) return;
    stop();
    if (uploadVideoUrlRef.current) URL.revokeObjectURL(uploadVideoUrlRef.current);
    const url = URL.createObjectURL(file);
    uploadVideoUrlRef.current = url;
    setUploadVideoUrl(url);
    setUploadPreviewName(file.name);
    if (videoRef.current) {
      videoRef.current.srcObject = null;
      videoRef.current.src = url;
      videoRef.current.loop = true;
      videoRef.current.load();
    }
    onNotify?.("已切换为上传视频 driving，可点击开始生成克隆预览。", "success");
  }, [onNotify, stop]);

  const clearUploadedVideo = useCallback(() => {
    stop();
    if (uploadVideoUrlRef.current) {
      URL.revokeObjectURL(uploadVideoUrlRef.current);
      uploadVideoUrlRef.current = null;
    }
    setUploadVideoUrl(null);
    setUploadPreviewName("");
    if (videoRef.current) {
      videoRef.current.removeAttribute("src");
      videoRef.current.load();
    }
  }, [stop]);

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100 p-4">
      <canvas ref={canvasRef} className="hidden" />
      <canvas ref={outputRecordCanvasRef} className="hidden" />
      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[20rem_minmax(0,1fr)_22rem]">
        <section ref={sourcePanelRef} className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Source</p>
              <h2 className="mt-1 text-base font-semibold text-slate-950">数字人形象</h2>
            </div>
            <span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs font-medium text-cyan-700">固定 source</span>
          </div>
          <label className="mt-4 block rounded-lg border border-dashed border-cyan-200 bg-cyan-50/60 p-3 text-sm text-slate-700">
            <span className="block text-xs font-semibold text-cyan-700">上传 source 形象</span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">作为克隆输出的数字人资产；摄像头或 driving video 仍只负责驱动表情和头动。</span>
            <input
              type="file"
              accept="image/*"
              disabled={sourceUploadBusy}
              className="mt-2 block w-full text-xs disabled:cursor-not-allowed disabled:text-slate-400"
              onChange={(event) => {
                const input = event.currentTarget;
                void handleSourceUpload(input.files?.[0] ?? null).finally(() => {
                  input.value = "";
                });
              }}
            />
            {sourceUploadBusy ? <span className="mt-2 block text-xs font-medium text-cyan-700">正在加入形象库...</span> : null}
          </label>
          <div className="mt-4 space-y-2">
            {avatars.map((avatar) => {
              const selected = selectedAvatar?.id === avatar.id;
              return (
                <button
                  key={avatar.id}
                  type="button"
                  onClick={() => onAvatarChange(avatar.id)}
                  className={`flex w-full items-center gap-3 rounded-lg border p-2 text-left transition ${
                    selected ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <img
                    src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview`)}
                    alt={avatar.name ?? avatar.id}
                    className="h-12 w-12 rounded-md border border-slate-200 object-cover"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-slate-900">{avatar.name ?? avatar.id}</span>
                    <span className="block truncate text-xs text-slate-500">{avatar.model_type} · {avatar.width}x{avatar.height}</span>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-5 border-t border-slate-100 pt-4">
            <p className="text-xs font-semibold text-slate-500">驱动参数</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {ANIMATION_REGION_OPTIONS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => handleConfigChange({ ...config, animation_region: item.id })}
                  className={`rounded-lg border px-2 py-2 text-xs font-semibold ${
                    config.animation_region === item.id ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            {VIDEO_CLONE_SLIDERS.map((control) => (
              <label key={control.key} className="mt-3 block text-xs font-medium text-slate-600">
                <span className="flex justify-between"><span>{control.label}</span><span>{Number(config[control.key]).toFixed(2)}</span></span>
                <input
                  type="range"
                  min={control.min}
                  max={control.max}
                  step={control.step}
                  value={Number(config[control.key])}
                  onChange={(event) => handleConfigChange({ ...config, [control.key]: Number(event.target.value) })}
                  className="mt-1 w-full accent-cyan-600"
                />
              </label>
            ))}
            <div className="mt-4 space-y-2">
              {VIDEO_CLONE_SWITCHES.map((control) => (
                <label
                  key={control.key}
                  className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700"
                >
                  {control.label}
                  <input
                    type="checkbox"
                    checked={Boolean(config[control.key])}
                    onChange={(event) => handleConfigChange({ ...config, [control.key]: event.target.checked })}
                    className="h-4 w-4 accent-cyan-600"
                  />
                </label>
              ))}
            </div>
            <label className="mt-4 flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
              裁剪 driving 人脸
              <input type="checkbox" checked={cropDriving} onChange={(event) => handleCropDrivingChange(event.target.checked)} className="h-4 w-4 accent-cyan-600" />
            </label>
          </div>
        </section>

        <section className="flex min-h-[28rem] min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Output</p>
              <h2 className="text-base font-semibold text-slate-950">克隆输出</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={outputRecording ? stopOutputRecording : startOutputRecording}
                disabled={outputRecordSaving || (!outputRecording && !outputUrl)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50 ${outputRecording ? "bg-red-600 hover:bg-red-500" : "bg-cyan-600 hover:bg-cyan-500"}`}
              >
                {outputRecordSaving ? "保存中..." : outputRecording ? "结束录制" : "录制输出"}
              </button>
              <button
                type="button"
                onClick={handleReturnToAvatarSelection}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700"
              >
                更换形象
              </button>
              <div className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusBadge}`}>{statusText}</div>
            </div>
          </div>
          <div className="relative flex min-h-0 flex-1 items-center justify-center bg-slate-950 p-3">
            {outputUrl ? (
              <img src={outputUrl} alt="视频克隆输出" className="max-h-full max-w-full object-contain" />
            ) : selectedAvatar ? (
              <img
                src={buildApiUrl(`/avatars/${encodeURIComponent(selectedAvatar.id)}/preview`)}
                alt={selectedAvatar.name ?? selectedAvatar.id}
                className="max-h-full max-w-full object-contain opacity-80"
              />
            ) : null}
            <div className="absolute bottom-3 left-3 right-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-white/90 px-2.5 py-1 font-medium text-slate-700">发送 {sentFrames}</span>
              <span className="rounded-full bg-white/90 px-2.5 py-1 font-medium text-slate-700">接收 {receivedFrames}</span>
              <span className="rounded-full bg-white/90 px-2.5 py-1 font-medium text-slate-700">丢帧 {droppedFrames}</span>
              <span className="rounded-full bg-white/90 px-2.5 py-1 font-medium text-slate-700">延迟 {latencyMs ?? "-"} ms</span>
            </div>
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Driving</p>
              <h2 className="mt-1 text-base font-semibold text-slate-950">摄像头驱动</h2>
            </div>
            <button
              type="button"
              onClick={status === "live" || status === "connecting" || status === "requesting" ? stop : () => void start()}
              className={`rounded-lg px-3 py-2 text-sm font-semibold text-white ${status === "live" ? "bg-red-600 hover:bg-red-500" : "bg-cyan-600 hover:bg-cyan-500"}`}
            >
              {status === "live" || status === "connecting" || status === "requesting" ? "停止" : "开始"}
            </button>
          </div>
          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
            <video ref={videoRef} muted playsInline className={`aspect-video w-full ${uploadVideoUrl ? "object-contain" : "object-cover"} ${mirror && !uploadVideoUrl ? "scale-x-[-1]" : ""}`} />
          </div>
          <div className="mt-4 space-y-3">
            <label className="block text-xs font-semibold text-slate-600">
              摄像头
              <select disabled={Boolean(uploadVideoUrl)} value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400">
                {devices.length ? devices.map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>) : <option value="">默认摄像头</option>}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs font-semibold text-slate-600">
                FPS
                <select value={fps} onChange={(event) => setFps(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
                  {FPS_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="block text-xs font-semibold text-slate-600">
                分辨率
                <select value={resolution} onChange={(event) => setResolution(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
                  {RESOLUTION_OPTIONS.map((value) => <option key={value} value={value}>{value}px</option>)}
                </select>
              </label>
            </div>
            <label className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
              镜像预览
              <input type="checkbox" checked={mirror} onChange={(event) => setMirror(event.target.checked)} className="h-4 w-4 accent-cyan-600" />
            </label>
            <label className="block rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-600">
              <span className="block text-xs font-semibold text-slate-500">上传 driving video</span>
              <input type="file" accept="video/*" className="mt-2 block w-full text-xs" onChange={(event) => handleUploadPreview(event.target.files?.[0] ?? null)} />
              {uploadPreviewName ? (
                <span className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span className="truncate">{uploadPreviewName}</span>
                  <button type="button" onClick={clearUploadedVideo} className="shrink-0 font-semibold text-cyan-700 hover:text-cyan-600">
                    清除
                  </button>
                </span>
              ) : null}
            </label>
          </div>
        </aside>
      </div>
    </main>
  );
}
