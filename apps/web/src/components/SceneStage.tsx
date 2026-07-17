import { useCallback, useEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import type { ClientRendererDescriptor, SceneBackgroundAsset, SceneComposition } from "../lib/api";
import { buildApiUrl } from "../lib/api";
import { Light2dAvatar } from "./Light2dAvatar";
import { VideoBackground } from "./VideoBackground";

type SceneStageProps = {
  videoRef: RefObject<HTMLVideoElement>;
  videoStream?: MediaStream | null;
  scene: SceneComposition | null;
  backgrounds: SceneBackgroundAsset[];
  subtitle?: string | null;
  avatarMaskUrl?: string | null;
  avatarAdjust?: {
    x: number;
    y: number;
    scale: number;
  };
  children?: ReactNode;
  className?: string;
  compactSquareStage?: boolean;
  clientRenderer?: ClientRendererDescriptor | null;
};

function backgroundUrl(background: SceneBackgroundAsset): string {
  return buildApiUrl(background.url);
}

const AVATAR_ANCHOR_CLASSES = {
  center: "items-center justify-center",
  bottom: "items-end justify-center",
  left: "items-center justify-start",
  right: "items-center justify-end",
} as const;

const AVATAR_ANCHOR_OBJECT_POSITIONS = {
  center: "object-center",
  bottom: "object-[center_bottom]",
  left: "object-[left_center]",
  right: "object-[right_center]",
} as const;

const AVATAR_ANCHOR_TRANSFORM_ORIGINS = {
  center: "center",
  bottom: "center bottom",
  left: "left center",
  right: "right center",
} as const;

export function SceneStage({
  videoRef,
  videoStream = null,
  scene,
  backgrounds,
  subtitle,
  avatarMaskUrl = null,
  avatarAdjust,
  children,
  className = "",
  compactSquareStage = false,
  clientRenderer = null,
}: SceneStageProps) {
  const [rendererFailed, setRendererFailed] = useState(false);
  useEffect(() => setRendererFailed(false), [clientRenderer?.config_url]);
  const handleRendererError = useCallback(() => setRendererFailed(true), []);
  const background = scene?.background_id
    ? backgrounds.find((item) => item.id === scene.background_id) ?? null
    : null;
  const subtitleStyle = scene?.subtitle_style ?? "lower-third";
  const avatarFit = scene?.avatar_fit === "cover" ? "object-cover" : "object-contain";
  const avatarAnchor = scene?.avatar_anchor ?? "center";
  const avatarAnchorClass = AVATAR_ANCHOR_CLASSES[avatarAnchor as keyof typeof AVATAR_ANCHOR_CLASSES] ?? AVATAR_ANCHOR_CLASSES.center;
  const avatarObjectPosition = AVATAR_ANCHOR_OBJECT_POSITIONS[avatarAnchor as keyof typeof AVATAR_ANCHOR_OBJECT_POSITIONS] ?? AVATAR_ANCHOR_OBJECT_POSITIONS.center;
  const avatarTransformOrigin = AVATAR_ANCHOR_TRANSFORM_ORIGINS[avatarAnchor as keyof typeof AVATAR_ANCHOR_TRANSFORM_ORIGINS] ?? AVATAR_ANCHOR_TRANSFORM_ORIGINS.center;
  const avatarMaskSize = scene?.avatar_fit === "cover" ? "cover" : "contain";
  const avatarMaskPosition = avatarAnchor === "bottom"
    ? "center bottom"
    : avatarAnchor === "left"
      ? "left center"
      : avatarAnchor === "right"
        ? "right center"
        : "center";
  const hasSceneBackground = Boolean(scene);
  const backgroundColor = scene?.background_color || "#ffffff";
  const sceneAvatarScale = scene?.avatar_scale ?? 1;
  const avatarDisplayScale = sceneAvatarScale * (avatarAdjust?.scale ?? 1);
  const avatarTransform = avatarAdjust
    ? `translate(${avatarAdjust.x}px, ${avatarAdjust.y}px) scale(${avatarDisplayScale})`
    : `scale(${sceneAvatarScale})`;
  const avatarMaskStyle: CSSProperties | undefined = avatarMaskUrl
    ? {
        WebkitMaskImage: `url("${avatarMaskUrl}")`,
        WebkitMaskRepeat: "no-repeat",
        WebkitMaskSize: avatarMaskSize,
        WebkitMaskPosition: avatarMaskPosition,
        maskImage: `url("${avatarMaskUrl}")`,
        maskMode: "alpha",
        maskRepeat: "no-repeat",
        maskSize: avatarMaskSize,
        maskPosition: avatarMaskPosition,
      }
    : undefined;

  return (
    <div className={`relative min-h-0 overflow-hidden ${hasSceneBackground ? "bg-slate-950" : "bg-white"} ${className}`}>
      <div className="scene-background-layer absolute inset-0" style={{ backgroundColor }}>
        {background?.kind === "image" ? (
          <img src={backgroundUrl(background)} alt={background.name} className="h-full w-full object-cover" />
        ) : null}
        {background?.kind === "video" ? (
          <video src={backgroundUrl(background)} className="h-full w-full object-cover" autoPlay muted loop playsInline />
        ) : null}
        {hasSceneBackground ? <div className="absolute inset-0 bg-slate-950/10" /> : null}
      </div>

      <div className={`absolute inset-0 flex p-4 sm:p-6 lg:p-8 ${avatarAnchorClass}`}>
        <div
          className={
            compactSquareStage
              ? "relative aspect-square w-full max-w-[42rem] max-h-full"
              : "relative h-full w-full"
          }
          style={{ transform: avatarTransform, transformOrigin: avatarTransformOrigin }}
        >
          <VideoBackground
            ref={videoRef}
            stream={videoStream}
            className={`absolute inset-0 h-full w-full ${avatarFit} ${avatarObjectPosition} ${clientRenderer && !rendererFailed ? "opacity-0" : "opacity-100"}`}
            style={avatarMaskStyle}
          />
          {clientRenderer && !rendererFailed ? (
            <Light2dAvatar
              renderer={clientRenderer}
              stream={videoStream}
              className="absolute inset-0"
              onRendererError={handleRendererError}
            />
          ) : null}
        </div>
      </div>

      {subtitle && subtitleStyle !== "none" ? (
        <div
          className={
            subtitleStyle === "compact"
              ? "absolute inset-x-4 bottom-4 z-20 mx-auto max-w-lg rounded-lg bg-slate-950/72 px-4 py-2 text-center text-sm font-medium leading-relaxed text-white shadow-lg backdrop-blur"
              : "absolute inset-x-4 bottom-6 z-20 mx-auto max-w-2xl rounded-lg border border-white/15 bg-slate-950/75 px-5 py-3 text-center text-base font-semibold leading-relaxed text-white shadow-xl backdrop-blur"
          }
        >
          {subtitle}
        </div>
      ) : null}

      {children}
    </div>
  );
}
