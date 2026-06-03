import { apiPost } from "./api";

function requestVideoPlayback(videoEl: HTMLVideoElement) {
  videoEl.autoplay = true;
  videoEl.playsInline = true;
  const attempt = () => {
    void videoEl.play().catch(() => {
      // If the browser blocks autoplay with audio, retry muted so video still paints.
      videoEl.muted = true;
      void videoEl.play().catch(() => {});
    });
  };
  attempt();
  return attempt;
}

export type PlaybackHandle = { pc: RTCPeerConnection; remoteStream: MediaStream };

export type StartPlaybackOptions = {
  onRemoteStream?: (remoteStream: MediaStream) => void;
};

export async function startPlayback(
  sessionId: string,
  videoEl: HTMLVideoElement,
  options: StartPlaybackOptions = {},
): Promise<PlaybackHandle> {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  const mediaStream = new MediaStream();
  videoEl.srcObject = mediaStream;
  const ensurePlayback = requestVideoPlayback(videoEl);

  pc.ontrack = (ev) => {
    const track = ev.track;
    if (!track) return;
    const hasTrack = mediaStream.getTracks().some((t) => t.id === track.id);
    if (!hasTrack) {
      mediaStream.addTrack(track);
      options.onRemoteStream?.(mediaStream);
    }
    ensurePlayback();
  };

  const cleanup = () => {
    videoEl.pause();
    videoEl.srcObject = null;
  };
  pc.addEventListener("connectionstatechange", () => {
    if (
      pc.connectionState === "closed"
      || pc.connectionState === "failed"
      || pc.connectionState === "disconnected"
    ) {
      cleanup();
    }
  });
  pc.addEventListener("iceconnectionstatechange", () => {
    if (
      pc.iceConnectionState === "closed"
      || pc.iceConnectionState === "failed"
      || pc.iceConnectionState === "disconnected"
    ) {
      cleanup();
    }
  });

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const answer = await apiPost<{ sdp: string; type: RTCSdpType }>(
    `/sessions/${sessionId}/webrtc/offer`,
    { sdp: pc.localDescription?.sdp ?? "", type: pc.localDescription?.type ?? "offer" }
  );

  await pc.setRemoteDescription(new RTCSessionDescription(answer));
  ensurePlayback();
  options.onRemoteStream?.(mediaStream);
  return { pc, remoteStream: mediaStream };
}
