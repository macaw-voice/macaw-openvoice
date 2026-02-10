import { z } from "zod";

const modelSchema = z.object({
  name: z.string(),
  engine: z.string(),
  version: z.string(),
  description: z.string().optional().default(""),
  type: z.string(),
  capabilities: z.record(z.any()),
  resources: z.record(z.any()),
});

const queueSchema = z.object({
  depth: z.number(),
  depth_by_priority: z.record(z.number()),
});

const segmentSchema = z.object({
  id: z.number(),
  start: z.number(),
  end: z.number(),
  text: z.string(),
  avg_logprob: z.number(),
  no_speech_prob: z.number(),
  compression_ratio: z.number(),
});

const wordSchema = z.object({
  word: z.string(),
  start: z.number(),
  end: z.number(),
  probability: z.number().nullable().optional(),
});

const jobSchema = z.object({
  request_id: z.string(),
  model: z.string(),
  priority: z.string(),
  language: z.string().nullable(),
  status: z.string(),
  created_at: z.number(),
  updated_at: z.number(),
  error: z.string().optional(),
  result: z
    .object({
      text: z.string(),
      language: z.string(),
      duration: z.number(),
      segments: z.array(segmentSchema),
      words: z.array(wordSchema).nullable(),
    })
    .nullable()
    .optional(),
});

const jobListSchema = z.object({
  items: z.array(jobSchema),
});

const modelListSchema = z.object({
  items: z.array(modelSchema),
});

export type DemoModel = z.infer<typeof modelSchema>;
export type DemoJob = z.infer<typeof jobSchema>;
export type QueueMetrics = z.infer<typeof queueSchema>;

const DEFAULT_BASE_URL = "http://localhost:9000";

function baseUrl() {
  return process.env.NEXT_PUBLIC_DEMO_API ?? DEFAULT_BASE_URL;
}

function wsBaseUrl() {
  const url = baseUrl();
  return url.replace(/^http/, "ws");
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl()}${path}`, {
    headers: {
      Accept: "application/json",
    },
    ...init,
    cache: "no-store",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchModels(): Promise<DemoModel[]> {
  const data = await getJson<unknown>("/demo/models");
  const parsed = modelListSchema.parse(data);
  return parsed.items;
}

export async function fetchQueue(): Promise<QueueMetrics> {
  const data = await getJson<unknown>("/demo/queue");
  return queueSchema.parse(data);
}

export async function fetchJobs(): Promise<DemoJob[]> {
  const data = await getJson<unknown>("/demo/jobs");
  const parsed = jobListSchema.parse(data);
  return parsed.items;
}

export async function fetchJob(requestId: string): Promise<DemoJob> {
  const data = await getJson<unknown>(`/demo/jobs/${requestId}`);
  return jobSchema.parse(data);
}

export interface CreateJobPayload {
  file: File;
  model: string;
  priority: string;
  language?: string | null;
}

export async function createJob(payload: CreateJobPayload): Promise<{ request_id: string }> {
  const form = new FormData();
  form.append("file", payload.file);
  form.append("model", payload.model);
  form.append("priority", payload.priority);
  if (payload.language) {
    form.append("language", payload.language);
  }

  const response = await fetch(`${baseUrl()}/demo/jobs`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Falha ao criar job (${response.status})`);
  }

  return (await response.json()) as { request_id: string };
}

export async function cancelJob(requestId: string): Promise<void> {
  const response = await fetch(`${baseUrl()}/demo/jobs/${requestId}/cancel`, {
    method: "POST",
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Falha ao cancelar job");
  }
}

// --- Streaming STT via WebSocket ---

export interface StreamingSTTCallbacks {
  // STT events
  onSessionCreated?: (data: Record<string, unknown>) => void;
  onVadSpeechStart?: () => void;
  onVadSpeechEnd?: () => void;
  onTranscriptPartial?: (text: string, segmentId: number) => void;
  onTranscriptFinal?: (text: string, segmentId: number) => void;
  onError?: (message: string, recoverable?: boolean) => void;
  onClose?: () => void;
  // TTS events (full-duplex)
  onTtsSpeakingStart?: (requestId: string) => void;
  onTtsSpeakingEnd?: (requestId: string, cancelled: boolean) => void;
  onTtsAudio?: (audioData: ArrayBuffer) => void;
  // Session events
  onSessionHold?: () => void;
  onRateLimit?: (delayMs: number) => void;
  onFramesDropped?: (droppedMs: number) => void;
}

export function createRealtimeConnection(
  model: string,
  language: string | undefined,
  callbacks: StreamingSTTCallbacks,
): WebSocket {
  const params = new URLSearchParams({ model });
  if (language) params.set("language", language);

  const ws = new WebSocket(`${wsBaseUrl()}/api/v1/realtime?${params.toString()}`);

  ws.binaryType = "arraybuffer";

  ws.onmessage = (event) => {
    // Binary frames = TTS audio (server -> client)
    if (event.data instanceof ArrayBuffer) {
      callbacks.onTtsAudio?.(event.data);
      return;
    }

    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data) as Record<string, unknown>;
        const type = msg.type as string;
        switch (type) {
          case "session.created":
            callbacks.onSessionCreated?.(msg);
            break;
          case "vad.speech_start":
            callbacks.onVadSpeechStart?.();
            break;
          case "vad.speech_end":
            callbacks.onVadSpeechEnd?.();
            break;
          case "transcript.partial":
            callbacks.onTranscriptPartial?.(msg.text as string, msg.segment_id as number);
            break;
          case "transcript.final":
            callbacks.onTranscriptFinal?.(msg.text as string, msg.segment_id as number);
            break;
          case "tts.speaking_start":
            callbacks.onTtsSpeakingStart?.(msg.request_id as string);
            break;
          case "tts.speaking_end":
            callbacks.onTtsSpeakingEnd?.(
              msg.request_id as string,
              (msg.cancelled as boolean) ?? false,
            );
            break;
          case "session.hold":
            callbacks.onSessionHold?.();
            break;
          case "session.rate_limit":
            callbacks.onRateLimit?.(msg.delay_ms as number);
            break;
          case "session.frames_dropped":
            callbacks.onFramesDropped?.(msg.dropped_ms as number);
            break;
          case "error":
            callbacks.onError?.(
              msg.message as string,
              msg.recoverable as boolean | undefined,
            );
            break;
        }
      } catch {
        // ignore malformed JSON
      }
    }
  };

  ws.onclose = () => {
    callbacks.onClose?.();
  };

  ws.onerror = () => {
    callbacks.onError?.("WebSocket connection error");
  };

  return ws;
}

// --- TTS via REST ---

export interface SpeechPayload {
  model: string;
  input: string;
  voice?: string;
  speed?: number;
  response_format?: "wav" | "pcm";
}

// --- Streaming TTS helpers (via WebSocket) ---

export function sendTtsSpeak(ws: WebSocket, text: string, voice?: string): void {
  if (ws.readyState !== WebSocket.OPEN) return;
  ws.send(
    JSON.stringify({
      type: "tts.speak",
      text,
      voice: voice ?? "default",
      request_id: `req_${Date.now()}`,
    }),
  );
}

export function sendTtsCancel(ws: WebSocket): void {
  if (ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "tts.cancel" }));
}

// --- TTS via REST ---

export async function synthesizeSpeech(payload: SpeechPayload): Promise<Blob> {
  const response = await fetch(`${baseUrl()}/api/v1/audio/speech`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: payload.model,
      input: payload.input,
      voice: payload.voice ?? "default",
      speed: payload.speed ?? 1.0,
      response_format: payload.response_format ?? "wav",
    }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `TTS failed (${response.status})`);
  }

  return response.blob();
}
