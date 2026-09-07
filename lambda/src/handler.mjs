import { timingSafeEqual } from "node:crypto";
import { SSMClient, GetParameterCommand } from "@aws-sdk/client-ssm";
import { retrieve } from "./retrieve.mjs";
import { formatPassages, generate } from "./generate.mjs";

const ssmClient = new SSMClient({});

// Lazy one-time fetch, cached for the life of the execution environment —
// same "lazy init flag inside the handler" pattern as the SDK skill's
// Lambda Best Practices section, just caching a value instead of a boolean.
let cachedApiKey = null;
async function getApiKey() {
  if (cachedApiKey) return cachedApiKey;
  const response = await ssmClient.send(
    new GetParameterCommand({
      Name: process.env.API_KEY_PARAM_NAME,
      WithDecryption: true, // required for SecureString — plaintext otherwise
    }),
  );
  cachedApiKey = response.Parameter.Value;
  return cachedApiKey;
}

// Buffer.compare / === on secrets leaks timing information about how many
// leading bytes matched. timingSafeEqual takes the same time regardless —
// cheap to do right, so no reason not to.
function safeEqual(a, b) {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

function jsonResponse(statusCode, body) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json",
      // Belt-and-suspenders: HttpApi's CorsConfiguration (set in
      // template.yaml) handles OPTIONS preflight and normally stamps this
      // on responses too, but the API Gateway skill flags Lambda-proxy CORS
      // as a common gap — cheap to also set it here directly.
      "access-control-allow-origin": "*",
    },
    body: JSON.stringify(body),
  };
}

export const handler = async (event) => {
  const providedKey = event.headers?.["x-api-key"];
  const expectedKey = await getApiKey();
  if (!providedKey || !safeEqual(providedKey, expectedKey)) {
    return jsonResponse(401, { error: "missing or invalid x-api-key" });
  }

  let payload;
  try {
    payload = JSON.parse(event.body ?? "{}");
  } catch {
    return jsonResponse(400, { error: "body must be valid JSON" });
  }

  const { question, jurisdiction } = payload;
  if (typeof question !== "string" || question.trim() === "") {
    return jsonResponse(400, { error: "question is required" });
  }
  if (jurisdiction && !["UK", "AU"].includes(jurisdiction)) {
    return jsonResponse(400, { error: "jurisdiction must be UK or AU" });
  }

  const topK = Number(process.env.TOP_K ?? 5);

  try {
    const chunks = await retrieve(
      process.env.KNOWLEDGE_BASE_ID,
      question,
      topK,
      jurisdiction ?? null,
    );

    if (chunks.length === 0) {
      // Mirrors the NO_CHUNKS case in run_generation.py: nothing retrieved,
      // so there's nothing to ground an answer in. Distinct from the model
      // choosing to refuse — no generation call happens at all.
      return jsonResponse(200, {
        outcome: "NO_CHUNKS",
        answer: null,
        retrieved: [],
      });
    }

    const passages = formatPassages(chunks);
    const result = await generate(process.env.MODEL_ARN, question, passages);

    return jsonResponse(200, {
      outcome: "ANSWERED",
      answer: result.text,
      stopReason: result.stopReason,
      usage: result.usage,
      retrieved: chunks.map((c) => ({
        score: c.score,
        filename: c.filename,
        jurisdiction: c.jurisdiction,
      })),
    });
  } catch (err) {
    // Full detail to CloudWatch (via the Lambda execution role's logging
    // permissions), generic message to the caller — an internet-facing
    // endpoint should never echo a raw AWS exception or stack trace back.
    console.error("bedrock call failed", err);
    return jsonResponse(502, { error: "upstream retrieval/generation failed" });
  }
};
