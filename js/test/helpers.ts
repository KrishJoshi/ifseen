import { type ChildProcess, spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";

/** Absolute path of a fixture (tests run from build-test/test/). */
export function fixture(name: string): string {
  return fileURLToPath(new URL(`../../test/fixtures/${name}`, import.meta.url));
}

export function fixtureBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(fixture(name)));
}

export interface Recorded {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | undefined;
}

export type Responder = (req: Recorded, index: number) => Response | Promise<Response>;

/** A fetch stand-in that records requests and answers from `responder`. */
export function mockFetch(responder: Responder) {
  const calls: Recorded[] = [];
  const fn = async (input: string, init: RequestInit = {}): Promise<Response> => {
    const headers: Record<string, string> = {};
    new Headers(init.headers).forEach((v, k) => {
      headers[k] = v;
    });
    const req: Recorded = {
      url: input,
      method: init.method ?? "GET",
      headers,
      body: typeof init.body === "string" ? init.body : undefined,
    };
    calls.push(req);
    if (init.signal?.aborted) throw init.signal.reason;
    return responder(req, calls.length - 1);
  };
  return Object.assign(fn, { calls });
}

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

/** A streaming response that emits the given byte chunks, then ends (or stays open). */
export function streamResponse(chunks: (string | Uint8Array)[], opts: { keepOpen?: boolean; signal?: AbortSignal } = {}): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const c of chunks) {
        controller.enqueue(typeof c === "string" ? enc.encode(c) : c);
        await new Promise((r) => setTimeout(r, 1));
      }
      if (!opts.keepOpen) controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

// -- integration helpers ----------------------------------------------------------------------


/** The Python repo root (js/ lives inside it). */
export const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

/** `ifseen` CLI and Python from the repo's venv, overridable with IFSEEN_BIN / IFSEEN_PYTHON. */
export const IFSEEN_BIN = process.env.IFSEEN_BIN ?? `${REPO_ROOT}.venv/bin/ifseen`;
export const PYTHON_BIN = process.env.IFSEEN_PYTHON ?? `${REPO_ROOT}.venv/bin/python`;
export const haveIfseen = existsSync(IFSEEN_BIN);
export const havePython = existsSync(PYTHON_BIN);

export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

export interface Spawned {
  proc: ChildProcess;
  output: () => string;
  stop: () => Promise<void>;
}

export function spawnProcess(cmd: string, args: string[], signal: NodeJS.Signals = "SIGINT"): Spawned {
  const proc = spawn(cmd, args, {
    cwd: REPO_ROOT,
    env: { ...process.env, NO_COLOR: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  proc.stdout?.on("data", (d: Buffer) => (out += d.toString()));
  proc.stderr?.on("data", (d: Buffer) => (out += d.toString()));
  return {
    proc,
    output: () => out,
    stop: () =>
      new Promise<void>((resolve) => {
        if (proc.exitCode !== null || proc.signalCode !== null) return resolve();
        const killer = setTimeout(() => proc.kill("SIGKILL"), 5000);
        proc.once("exit", () => {
          clearTimeout(killer);
          resolve();
        });
        proc.kill(signal);
      }),
  };
}

/** Poll `probe` until it resolves truthy, or fail after `timeoutMs`. */
export async function waitFor(probe: () => Promise<boolean>, timeoutMs: number, what: string, log?: () => string) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      if (await probe()) return;
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}${log ? `\n${log()}` : ""}`);
    await new Promise((r) => setTimeout(r, 100));
  }
}
