import {
  BedrockRuntimeClient,
  ConverseCommand,
} from "@aws-sdk/client-bedrock-runtime";

const client = new BedrockRuntimeClient({});

// Ported verbatim from SYSTEM_PROMPT in src/generate_answer.py. This is the
// grounding contract — kept in sync with the Python version by hand.
const SYSTEM_PROMPT = `You answer questions about financial regulation using ONLY the numbered passages provided. You are used by compliance staff, where an invented or misattributed rule is a regulatory breach, not merely an error.

Rules:
1. Use only the passages. Do not use anything you know from training.
2. After every factual claim, cite the passage it came from as [1], [2], etc.
3. If the passages do not answer the question, say so plainly and stop. Do not substitute a related rule, a different jurisdiction's rule, or a general principle.
4. The passages are tagged with a jurisdiction. Never present one jurisdiction's requirement as another's. If passages from only one jurisdiction are present, say which one your answer covers.
5. If passages conflict, say so rather than choosing silently.

Preferred refusal wording when the passages do not cover the question:
"The provided sources do not address this."`;

/**
 * Number the passages and tag each with jurisdiction and source.
 * Mirrors format_passages() in generate_answer.py.
 */
export function formatPassages(chunks) {
  return chunks
    .map(
      (c, i) =>
        `[${i + 1}] jurisdiction=${c.jurisdiction} source=${c.filename}\n${c.text}`,
    )
    .join("\n\n");
}

/**
 * Answer from the passages only. No guardrail wiring yet — that's a
 * deliberate follow-up once retrieve -> generate works end to end, not an
 * oversight. Mirrors generate() in generate_answer.py.
 */
export async function generate(modelArn, question, passages) {
  const response = await client.send(
    new ConverseCommand({
      modelId: modelArn,
      system: [{ text: SYSTEM_PROMPT }],
      messages: [
        {
          role: "user",
          content: [
            {
              text: `Question: ${question}\n\nPassages:\n${passages}\n\nAnswer the question using only the passages above.`,
            },
          ],
        },
      ],
      // Always set explicitly — an unset maxTokens defaults to the model's
      // maximum and silently reserves far more quota than needed, a common
      // cause of ThrottlingException (per the amazon-bedrock skill).
      inferenceConfig: { temperature: 0.0, maxTokens: 800 },
    }),
  );

  return {
    text: response.output.message.content[0].text,
    stopReason: response.stopReason,
    usage: response.usage ?? {},
  };
}
