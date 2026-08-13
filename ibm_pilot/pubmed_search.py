from __future__ import annotations

import json
import httpx

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool()
def search_pubmed(
    keywords: str,
    return_info: str = '["title", "publication_date", "PubMed_citation"]',
) -> dict:
    """Search PubMed for scientific research papers.

    Use this tool only for legitimate scientific literature searches.
    Returns paper titles, publication dates, and PubMed IDs/citations.
    """

    try:
        info = json.loads(return_info)
        if not isinstance(info, list):
            info = ["title", "publication_date", "PubMed_citation"]
    except (json.JSONDecodeError, TypeError):
        info = ["title", "publication_date", "PubMed_citation"]

    query = (keywords or "").strip()

    if not query:
        return {
            "status": "ERROR",
            "message": "A PubMed search query is required."
        }

    try:
        # Step 1: Search PubMed
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": 5,
            "sort": "relevance",
        }

        search_response = httpx.get(
            search_url,
            params=search_params,
            timeout=20.0,
        )
        search_response.raise_for_status()

        search_data = search_response.json()
        ids = search_data.get("esearchresult", {}).get("idlist", [])

        if not ids:
            return {
                "status": "OK",
                "query": query,
                "papers": [],
                "message": "No PubMed papers were found for this query."
            }

        # Step 2: Retrieve paper details
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

        fetch_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
        }

        fetch_response = httpx.get(
            fetch_url,
            params=fetch_params,
            timeout=20.0,
        )
        fetch_response.raise_for_status()

        data = fetch_response.json()
        result = data.get("result", {})

        papers = []

        for pmid in ids:
            paper = result.get(pmid, {})

            if not paper:
                continue

            papers.append({
                "title": paper.get("title", ""),
                "publication_date": paper.get("pubdate", ""),
                "PubMed_citation": f"PMID: {pmid}",
            })

        return {
            "status": "OK",
            "query": query,
            "papers_found": len(papers),
            "papers": papers,
        }

    except Exception as exc:
        return {
            "status": "ERROR",
            "message": f"PubMed search failed: {str(exc)}",
        }
