// One-shot check straight against a decision provider (no Python needed).
//
//   GEMINI_API_KEY=... npx tsx examples/check-image.ts door.jpg
//   TYPESAFE_API_KEY=... PROVIDER=jev npx tsx examples/check-image.ts door.jpg
//
// PROVIDER_URL overrides the endpoint (a proxy, or tests/fake_server.py for a free dry run).
//
// Server-side only: this sends your API key with the request.
import { AuthError, BillingError, checkDetailed, type ProviderName } from "ifseen";

const image = process.argv[2];
if (!image) {
  console.error("usage: check-image.ts <image.jpg|png>");
  process.exit(2);
}

try {
  const result = await checkDetailed(
    image, // a file path; bytes, a Blob or base64 work too
    {
      parcel: "A parcel has been left on the doorstep.",
      person: { when: "A person is at the front door.", falseMeans: "A reflection, poster or statue." },
    },
    {
      provider: (process.env.PROVIDER as ProviderName | undefined) ?? "gemini",
      baseUrl: process.env.PROVIDER_URL,
      context: "Doorbell camera.",
    },
  );
  for (const [name, p] of Object.entries(result.probs)) {
    console.log(`${name.padEnd(8)} ${(p * 100).toFixed(1).padStart(5)}%`);
  }
  console.log(`${result.provider}: ${result.tokens} tokens, ${result.latencyMs.toFixed(0)} ms, ~$${result.costUsd.toFixed(6)}`);
} catch (e) {
  if (e instanceof AuthError) console.error("bad API key");
  else if (e instanceof BillingError) console.error("billing problem:", e.message);
  else throw e;
  process.exit(1);
}
