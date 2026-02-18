"""RAG context retrieval activity using Bedrock Knowledge Base.

Retrieves relevant documentation to help the LLM explain health state.
Per RAG corpus guidance: excludes raw metrics/PromQL (those belong in code).
"""

import boto3
from temporalio import activity

from copilot.models import FetchRagContextInput  # noqa: TC001


@activity.defn
async def fetch_rag_context(input: FetchRagContextInput) -> list[str]:
    """Retrieve relevant documentation from Bedrock Knowledge Base.

    This activity fetches context to help the LLM explain health state.
    The RAG corpus contains operational documentation, not raw metrics.

    Args:
        input: FetchRagContextInput with KB ID, factors, region, max results

    Returns:
        List of relevant document excerpts
    """
    activity.logger.info(f"Fetching RAG context for {len(input.contributing_factors)} factors")

    if not input.contributing_factors:
        return []

    # Build query from contributing factors
    query_text = " ".join(input.contributing_factors)

    try:
        bedrock_agent = boto3.client("bedrock-agent-runtime", region_name=input.region)

        response = bedrock_agent.retrieve(
            knowledgeBaseId=input.knowledge_base_id,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": input.max_results}
            },
        )

        # Extract text content from results
        results = []
        for result in response.get("retrievalResults", []):
            content = result.get("content", {}).get("text", "")
            if content:
                # Skip if it looks like raw metrics/PromQL
                if _is_metrics_content(content):
                    activity.logger.debug("Skipping metrics content from RAG")
                    continue
                results.append(content)

        activity.logger.info(f"Retrieved {len(results)} relevant documents")
        return results

    except Exception as e:
        activity.logger.warning(f"RAG retrieval error: {e}")
        return []


def _is_metrics_content(content: str) -> bool:
    """Check if content appears to be raw metrics/PromQL.

    Per RAG corpus guidance, raw metrics belong in code, not RAG.
    """
    metrics_indicators = [
        "sum(rate(",
        "histogram_quantile(",
        "increase(",
        "avg(",
        "{service_name=",
        "[1m])",
        "[5m])",
        "_bucket{",
        "_total{",
        "_count{",
    ]

    content_lower = content.lower()
    indicator_count = sum(1 for ind in metrics_indicators if ind.lower() in content_lower)

    # If more than 3 indicators, likely metrics content
    return indicator_count > 3
