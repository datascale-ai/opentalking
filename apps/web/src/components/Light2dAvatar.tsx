import { useEffect, useRef } from "react";

import { buildApiUrl } from "../lib/api";
import type { ClientRendererDescriptor } from "../lib/api";
import { computeRms, createEnergySmoother, mouthStateForEnergy, type MouthState } from "../light2d/audio";
import { light2dAssetUrl, parseLight2dConfig, type Light2dConfig, type Light2dLayer } from "../light2d/config";

type Light2dAvatarProps = {
  renderer: ClientRendererDescriptor;
  stream: MediaStream | null;
  className?: string;
  onRendererError: () => void;
};

type LayerImages = {
  base: HTMLImageElement;
  blink: HTMLImageElement;
  mouth: Record<MouthState, HTMLImageElement>;
};

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Light2D asset failed: ${url}`));
    image.src = url;
  });
}

async function loadImages(config: Light2dConfig, assetBaseUrl: string): Promise<LayerImages> {
  const load = (layer: Light2dLayer) => loadImage(light2dAssetUrl(buildApiUrl(assetBaseUrl), layer.source));
  const [base, blink, closed, small, medium, large] = await Promise.all([
    load(config.layers.base),
    load(config.layers.blink),
    load(config.layers.mouth.closed),
    load(config.layers.mouth.small),
    load(config.layers.mouth.medium),
    load(config.layers.mouth.large),
  ]);
  return { base, blink, mouth: { closed, small, medium, large } };
}

function drawLayer(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  layer: Light2dLayer,
  alpha = 1,
): void {
  const [x, y, width, height] = layer.rect;
  context.globalAlpha = alpha;
  context.drawImage(image, x, y, width, height);
}

export function Light2dAvatar({ renderer, stream, className = "", onRendererError }: Light2dAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let animationFrame = 0;
    let audioContext: AudioContext | null = null;
    let sourceNode: MediaStreamAudioSourceNode | null = null;
    let analyser: AnalyserNode | null = null;
    let resumeAudio = () => undefined;

    const start = async () => {
      const response = await fetch(buildApiUrl(renderer.config_url), { cache: "no-store" });
      if (!response.ok) throw new Error(`Light2D config failed: ${response.status}`);
      const config = parseLight2dConfig(await response.json());
      const images = await loadImages(config, renderer.asset_base_url);
      if (cancelled) return;

      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) throw new Error("Canvas 2D is unavailable");
      canvas.width = config.canvas.width;
      canvas.height = config.canvas.height;

      const audioTracks = stream?.getAudioTracks() ?? [];
      if (stream && audioTracks.length > 0) {
        audioContext = new AudioContext();
        resumeAudio = () => {
          if (audioContext?.state === "suspended") void audioContext.resume().catch(() => undefined);
        };
        window.addEventListener("pointerdown", resumeAudio, { passive: true });
        window.addEventListener("keydown", resumeAudio);
        resumeAudio();
        sourceNode = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0;
        sourceNode.connect(analyser);
      }

      const samples = new Float32Array(analyser?.fftSize ?? 1024);
      const smoother = createEnergySmoother(config.audio);
      let currentMouth: MouthState = "closed";
      let previousMouth: MouthState = "closed";
      let mouthChangedAt = performance.now();
      let lastTime = performance.now();

      const render = (now: number) => {
        if (cancelled) return;
        const deltaMs = Math.min(100, Math.max(0, now - lastTime));
        lastTime = now;
        let rawEnergy = 0;
        if (analyser) {
          analyser.getFloatTimeDomainData(samples);
          rawEnergy = computeRms(samples);
        }
        const gatedEnergy = rawEnergy < config.audio.silence_gate ? 0 : rawEnergy;
        const energy = smoother.update(gatedEnergy, deltaMs);
        const nextMouth = mouthStateForEnergy(energy, config.audio);
        if (nextMouth !== currentMouth) {
          previousMouth = currentMouth;
          currentMouth = nextMouth;
          mouthChangedAt = now;
        }
        const mouthProgress = Math.min(1, (now - mouthChangedAt) / config.audio.crossfade_ms);
        const breathPhase = (now % config.animation.breath_period_ms) / config.animation.breath_period_ms;
        const swayPhase = breathPhase * Math.PI * 2;
        const speakingWeight = Math.min(1, energy / Math.max(config.audio.medium_threshold, 0.001));
        const scaleY = 1 + Math.sin(swayPhase) * config.animation.breath_scale + speakingWeight * 0.003;
        const rotation = Math.sin(swayPhase * 0.75) * config.animation.sway_degrees + speakingWeight * 0.12;
        const blinkLocal = now % config.animation.blink_period_ms;
        const blinking = blinkLocal < config.animation.blink_duration_ms;

        context.clearRect(0, 0, canvas.width, canvas.height);
        context.save();
        context.translate(canvas.width / 2, canvas.height);
        context.rotate((rotation * Math.PI) / 180);
        context.scale(1, scaleY);
        context.translate(-canvas.width / 2, -canvas.height);
        drawLayer(context, images.base, config.layers.base);
        if (mouthProgress < 1 && previousMouth !== currentMouth) {
          drawLayer(context, images.mouth[previousMouth], config.layers.mouth[previousMouth], 1 - mouthProgress);
        }
        drawLayer(context, images.mouth[currentMouth], config.layers.mouth[currentMouth], mouthProgress);
        if (blinking) drawLayer(context, images.blink, config.layers.blink);
        context.restore();
        context.globalAlpha = 1;
        canvas.dataset.mouthState = currentMouth;
        canvas.dataset.audioEnergy = energy.toFixed(4);
        canvas.dataset.rendererReady = "true";
        animationFrame = requestAnimationFrame(render);
      };
      animationFrame = requestAnimationFrame(render);
    };

    void start().catch((error) => {
      if (!cancelled) {
        console.warn("Light2D renderer failed", error);
        onRendererError();
      }
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(animationFrame);
      window.removeEventListener("pointerdown", resumeAudio);
      window.removeEventListener("keydown", resumeAudio);
      sourceNode?.disconnect();
      analyser?.disconnect();
      if (audioContext) void audioContext.close();
    };
  }, [onRendererError, renderer.asset_base_url, renderer.config_url, stream]);

  return <canvas ref={canvasRef} className={`h-full w-full object-contain ${className}`} aria-label="Light2D 动漫形象" />;
}
