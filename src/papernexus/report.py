from __future__ import annotations

from .models import ResearchRouteResult


TIER_TITLES = {
    "read_first": "Read first",
    "background": "Background",
    "frontier": "Frontier",
    "optional_branch": "Optional branch",
}


def render_markdown(result: ResearchRouteResult) -> str:
    lines = [
        "# PaperNexus research route",
        "",
        "> This report contains evidence-backed citation paths. Citation does not prove causal influence.",
        "",
        "## Seeds",
        "",
    ]
    for seed_id in result.seeds:
        paper = result.papers[seed_id]
        lines.append(f"- [{seed_id}] {paper.title} ({paper.year or 'year unknown'})")

    lines.extend(["", "## Research routes", ""])
    if not result.routes:
        lines.append("No confirmed multi-paper route was found in this sample.")
    for route in result.routes:
        titles = [
            f"[{paper_id}] {result.papers[paper_id].title}"
            for paper_id in route.paper_ids
        ]
        lines.append(f"### {route.id} (score {route.score:.3f})")
        lines.append("")
        lines.append(" -> ".join(titles))
        lines.append("")
        lines.append(route.explanation)
        lines.append("")

    lines.extend(["## Turning-point candidates", ""])
    turning_points = sorted(
        (
            evidence
            for evidence in result.candidates.values()
            if "turning_point" in evidence.roles
        ),
        key=lambda evidence: evidence.route_score,
        reverse=True,
    )[:5]
    if not turning_points:
        lines.append("No turning-point candidate was detected in the sampled graph.")
    for evidence in turning_points:
        paper = result.papers[evidence.paper_id]
        lines.append(
            f"- **{paper.title}** ({paper.year or 'year unknown'}) - has both incoming "
            "and outgoing confirmed citation edges in this sample; "
            f"local bridge score `{evidence.bridge_score:.3f}`."
        )
    lines.append("")

    lines.extend(["## Priority reading list", ""])
    for tier in TIER_TITLES:
        tier_items = [item for item in result.reading_list if item.tier == tier]
        if not tier_items:
            continue
        lines.extend([f"### {TIER_TITLES[tier]}", ""])
        for item in tier_items:
            paper = result.papers[item.paper_id]
            link = paper.doi or paper.oa_url
            title = f"[{paper.title}]({link})" if link else paper.title
            lines.append(
                f"- **{title}** ({paper.year or 'year unknown'}) - {item.reason}. "
                f"Evidence: `{item.evidence_status}`."
            )

    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- None reported by the pipeline.")
    lines.extend(["", "## Provenance and limitations", ""])
    lines.append(f"- Generated: {result.provenance['generated_at']}")
    lines.append(f"- Provider: {result.provenance['provider']}")
    lines.append(f"- Algorithm: {result.provenance['algorithm_version']}")
    for limitation in result.provenance["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)
