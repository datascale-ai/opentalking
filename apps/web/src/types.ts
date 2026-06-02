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

export type MemoryLibrary = {
  id: string;
  name: string;
  profile_id: string;
  character_id: string;
  memory_count: number;
  created_at: string;
  updated_at: string;
};

export type MemoryItem = {
  id: string;
  text: string;
  type: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

export type MemoryTurn = {
  role: "user" | "assistant";
  content: string;
};
