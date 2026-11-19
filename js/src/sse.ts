/** One dispatched Server-Sent Events message. */
export interface SseMessage {
  /** `event:` field, `"message"` if absent. */
  event: string;
  /** `data:` lines joined with `\n`. */
  data: string;
  /** Last `id:` seen on the stream (persists across messages, per the spec). */
  id: string | undefined;
}

export interface SseParserCallbacks {
  onMessage(message: SseMessage): void;
  /** `: comment` lines, e.g. the server's `connected` / `keep-alive`. */
  onComment?(comment: string): void;
  /** A valid `retry:` field (milliseconds). */
  onRetry?(ms: number): void;
}

/**
 * An incremental parser for the `text/event-stream` format (WHATWG HTML §9.2), fed decoded
 * text in arbitrary chunks. Lines may end in CRLF, LF or CR, and a CRLF may be split across
 * chunks.
 */
export class SseParser {
  private buffer = "";
  private data: string[] = [];
  private eventType = "";
  private lastId: string | undefined;
  private sawCr = false;
  private first = true;
  private readonly cb: SseParserCallbacks;

  constructor(callbacks: SseParserCallbacks) {
    this.cb = callbacks;
  }

  feed(chunk: string): void {
    if (!chunk) return;
    let text = chunk;
    if (this.first) {
      this.first = false;
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    }
    // a CR ended the previous chunk: a leading LF here belongs to that line ending
    if (this.sawCr && text[0] === "\n") text = text.slice(1);
    this.sawCr = false;
    this.buffer += text;

    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const c = this.buffer[i];
      if (c !== "\n" && c !== "\r") continue;
      this.line(this.buffer.slice(start, i));
      if (c === "\r") {
        if (i + 1 < this.buffer.length) {
          if (this.buffer[i + 1] === "\n") i++;
        } else {
          this.sawCr = true;
        }
      }
      start = i + 1;
    }
    this.buffer = this.buffer.slice(start);
  }

  /** Forget any half-received message (call when a connection drops). */
  reset(): void {
    this.buffer = "";
    this.data = [];
    this.eventType = "";
    this.sawCr = false;
    this.first = true;
  }

  private line(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line[0] === ":") {
      this.cb.onComment?.(line.slice(1).replace(/^ /, ""));
      return;
    }
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value[0] === " ") value = value.slice(1);
    switch (field) {
      case "data":
        this.data.push(value);
        break;
      case "event":
        this.eventType = value;
        break;
      case "id":
        if (!value.includes("\0")) this.lastId = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) this.cb.onRetry?.(Number(value));
        break;
      default:
        break; // unknown fields are ignored
    }
  }

  private dispatch(): void {
    const type = this.eventType;
    this.eventType = "";
    if (!this.data.length) return;
    const data = this.data.join("\n");
    this.data = [];
    this.cb.onMessage({ event: type || "message", data, id: this.lastId });
  }
}
