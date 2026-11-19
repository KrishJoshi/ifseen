// Create a watcher on a running `ifseen serve` and print its live events.
//
//   ifseen serve --dry-run          # or with a real provider key in the env
//   npx tsx examples/watch-events.ts /path/to/snapshot.jpg
//
// Set IFSEEN_URL / IFSEEN_TOKEN for a remote, token-protected server.
import { IfseenApiError, IfseenClient } from "ifseen";

const client = new IfseenClient({
  baseUrl: process.env.IFSEEN_URL ?? "http://127.0.0.1:8899",
  token: process.env.IFSEEN_TOKEN,
});

const file = process.argv[2] ?? "door.jpg";
console.log(await client.health());

const controller = new AbortController();
process.on("SIGINT", () => controller.abort());

try {
  await client.createWatcher({
    id: "example",
    source: { file }, // a path on the server's machine; also { url }, { camera: 0 }, "screen"...
    every: "2s",
    rules: [
      { name: "person", when: "A person is at the front door.", threshold: 0.85, for: 2, cooldown: "1m" },
      { name: "parcel", when: "A parcel has been left on the doorstep." },
    ],
  });
} catch (e) {
  if (!(e instanceof IfseenApiError && e.code === "already_exists")) throw e;
}

// Ctrl+C to stop. The stream reconnects on its own if the server restarts.
for await (const event of client.events({
  watcher: "example",
  signal: controller.signal,
  onOpen: ({ reconnect }) => reconnect && console.log("(reconnected - events aren't replayed)"),
})) {
  switch (event.event) {
    case "decision":
      console.log("decision", event.probs);
      break;
    case "fire": {
      console.log(`FIRE ${event.rule} (${(event.probability * 100).toFixed(0)}%)`);
      const jpeg = await client.snapshot("example");
      console.log(`  snapshot: ${jpeg.byteLength} bytes`);
      break;
    }
    case "error":
      console.log("error", event.message, event.retry_in ? `(retrying in ${event.retry_in}s)` : "");
      break;
    case "unknown":
      console.log("newer event kind", event.kind);
      break;
    default:
      console.log(event.event);
  }
}

await client.deleteWatcher("example");
