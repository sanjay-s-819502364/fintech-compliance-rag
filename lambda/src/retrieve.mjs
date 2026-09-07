import {
  BedrockAgentRuntimeClient,
  RetrieveCommand,
} from "@aws-sdk/client-bedrock-agent-runtime";

// One client per Lambda execution environment, not per invocation — see
// "Lambda Best Practices" in the AWS SDK v3 skill: initialize outside the
// handler so warm invocations reuse the same TCP connections instead of
// renegotiating TLS on every request.
const client = new BedrockAgentRuntimeClient({});

function jurisdictionFromUri(uri) {
  if (uri.includes("/uk-fca/")) return "UK";
  if (uri.includes("/au-asic/")) return "AU";
  if (uri.includes("/distractors/")) return "DISTRACTOR";
  return "UNKNOWN";
}

/**
 * Fetch chunks from the managed Knowledge Base.
 *
 * Mirrors retrieve() in src/generate_answer.py, minus the managed/vector
 * branching — this KB is confirmed managed-type, so there's only one shape
 * to support.
 */
export async function retrieve(knowledgeBaseId, question, topK, jurisdiction) {
  const searchConfig = { numberOfResults: topK };
  if (jurisdiction) {
    searchConfig.filter = {
      equals: { key: "jurisdiction", value: jurisdiction },
    };
  }

  const response = await client.send(
    new RetrieveCommand({
      knowledgeBaseId,
      retrievalQuery: { text: question },
      retrievalConfiguration: {
        managedSearchConfiguration: searchConfig,
      },
    }),
  );

  return (response.retrievalResults ?? []).map((item) => {
    const uri = item.location?.s3Location?.uri ?? "";
    return {
      score: item.score,
      uri,
      filename: uri.split("/").pop(),
      jurisdiction: jurisdictionFromUri(uri),
      text: item.content?.text ?? "",
    };
  });
}
