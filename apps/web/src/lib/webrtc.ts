import { apiPost } from "./api";

export async function startPlayback(sessionId: string, videoEl: HTMLVideoElement) {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  const mediaStream = new MediaStream();
  videoEl.srcObject = mediaStream;
  let disconnectCleanupTimer: number | null = null;

  pc.ontrack = (ev) => {
    const track = ev.track;
    if (!track) return;
    const hasTrack = mediaStream.getTracks().some((t) => t.id === track.id);
    if (!hasTrack) {
      mediaStream.addTrack(track);
    }
    videoEl.play().catch(() => {});
  };

  const cleanup = () => {
    if (disconnectCleanupTimer !== null) {
      window.clearTimeout(disconnectCleanupTimer);
      disconnectCleanupTimer = null;
    }
    videoEl.pause();
    videoEl.srcObject = null;
  };
  const scheduleDisconnectedCleanup = () => {
    if (disconnectCleanupTimer !== null) {
      return;
    }
    disconnectCleanupTimer = window.setTimeout(() => {
      disconnectCleanupTimer = null;
      if (
        pc.connectionState === "disconnected"
        || pc.iceConnectionState === "disconnected"
      ) {
        cleanup();
      }
    }, 8000);
  };
  const cancelDisconnectedCleanup = () => {
    if (disconnectCleanupTimer !== null) {
      window.clearTimeout(disconnectCleanupTimer);
      disconnectCleanupTimer = null;
    }
  };
  pc.addEventListener("connectionstatechange", () => {
    if (
      pc.connectionState === "closed"
      || pc.connectionState === "failed"
    ) {
      cleanup();
      return;
    }
    if (
      pc.connectionState === "connected"
      || pc.connectionState === "connecting"
    ) {
      cancelDisconnectedCleanup();
      return;
    }
    if (pc.connectionState === "disconnected") {
      scheduleDisconnectedCleanup();
    }
  });
  pc.addEventListener("iceconnectionstatechange", () => {
    if (
      pc.iceConnectionState === "closed"
      || pc.iceConnectionState === "failed"
    ) {
      cleanup();
      return;
    }
    if (
      pc.iceConnectionState === "connected"
      || pc.iceConnectionState === "completed"
      || pc.iceConnectionState === "checking"
    ) {
      cancelDisconnectedCleanup();
      return;
    }
    if (pc.iceConnectionState === "disconnected") {
      scheduleDisconnectedCleanup();
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
  return pc;
}
