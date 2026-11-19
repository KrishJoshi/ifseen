// The smallest possible automation: run code whenever any watcher fires.
//
//   ifseen serve doorbell           # start a recipe on the server
//   npx tsx examples/on-fire.ts
import { IfseenClient } from "ifseen";

const client = new IfseenClient({ token: process.env.IFSEEN_TOKEN });

const off = client.on("fire", async (e) => {
  console.log(`${new Date(e.time * 1000).toLocaleTimeString()} ${e.watcher}/${e.rule}: ${e.when}`);
  // e.g. await fetch("https://example.com/hook", { method: "POST", body: JSON.stringify(e) });
});

process.on("SIGINT", () => {
  off();
  process.exit(0);
});
