export type ConnectionStatus = "idle" | "connecting" | "queued" | "live" | "expiring" | "error";

export interface QueueInfo {
  position: number;   // >0 = waiting, 0 = slot acquired, -1 = rejected
  message: string;    // "waiting" | "slot_acquired" | "queue_full" | "timeout"
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: number;
}
