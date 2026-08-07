export type SSEHandler = (event: string, data: Record<string, unknown>) => void;

export async function consumeSSE(
  response: Response,
  onEvent: SSEHandler
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        currentEvent = "message";
        continue;
      }

      if (trimmed.startsWith("event:")) {
        currentEvent = trimmed.slice(6).trim();
        continue;
      }

      if (trimmed.startsWith("data:")) {
        const dataStr = trimmed.slice(5).trim();
        if (!dataStr || dataStr === "[DONE]") continue;

        try {
          const data = JSON.parse(dataStr) as Record<string, unknown>;
          onEvent(currentEvent, data);
        } catch {
          // skip malformed JSON
        }
      }
    }
  }
}
