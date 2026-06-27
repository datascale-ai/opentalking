import type { CSSProperties } from "react";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

type VideoBackgroundProps = {
  className?: string;
  style?: CSSProperties;
  stream?: MediaStream | null;
};

export function playWithMutedFallback(video: HTMLVideoElement) {
  void video.play().catch(() => {
    video.muted = true;
    void video.play().catch(() => {});
  });
}

export const VideoBackground = forwardRef<HTMLVideoElement, VideoBackgroundProps>(
  ({ className, style, stream }, ref) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    useImperativeHandle(ref, () => videoRef.current as HTMLVideoElement);

    useEffect(() => {
      const video = videoRef.current;
      if (!video) return;
      if (video.srcObject !== stream) {
        video.srcObject = stream ?? null;
      }
      if (stream) {
        video.muted = false;
        video.volume = 1;
        playWithMutedFallback(video);
      } else {
        video.muted = true;
      }
    }, [stream]);

    return (
      <video
        ref={videoRef}
        className={className ?? "absolute inset-0 h-full w-full object-contain"}
        style={style}
        autoPlay
        playsInline
        muted={!stream}
      />
    );
  },
);

VideoBackground.displayName = "VideoBackground";
