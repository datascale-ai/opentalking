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

export type WeChatImportSpeaker = {
  id: string;
  name: string;
  message_count: number;
  is_self: boolean;
  metadata: Record<string, unknown>;
};

export type WeChatImportJob = {
  id: string;
  status: "needs_speaker_selection" | "draft_ready" | "committed" | "error" | string;
  speakers: WeChatImportSpeaker[];
  profile_id: string;
  memory_library_id: string;
  avatar_id: string;
  avatar_model: string;
  character_id: string;
  selected_speaker_id?: string | null;
  persona_md?: string | null;
  source_metadata: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type WeChatImportCommitResult = {
  job_id: string;
  persona_id: string;
  memory_imported: number;
  persona_md_bytes: number;
  profile_id: string;
  character_id: string;
  memory_library_id: string;
};
