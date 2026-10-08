"""Run-summary formatting. Statistics live in memory for one run only."""

import os
from pathlib import Path


def percentage(count, total):
    """Return a display-safe percentage for a count within a total."""
    return "n/a" if total == 0 else f"{count / total:.1%}"


def format_duration(seconds):
    return f"{seconds:.2f}s"


def final_label_rows(final_labels, label_order):
    """Return ordered final-label rows, including categories with zero results."""
    labels = [*label_order, None]
    return [
        ("None" if label is None else label, final_labels[label]) for label in labels
    ]


def build_markdown_summary(title, metrics, final_labels, label_order, duration):
    """Build a GitHub Actions Job Summary without retaining any run data."""
    scanned = metrics[0][1]
    classified = sum(final_labels.values())
    lines = [f"## {title}", "", "| Metric | Count | Share of scanned |", "| --- | ---: | ---: |"]
    lines.extend(
        f"| {name} | {count} | {percentage(count, scanned)} |"
        for name, count in metrics
    )
    lines.extend(["", "### Final label counts", "", "| Final label | Count | Share of classified |", "| --- | ---: | ---: |"])
    lines.extend(
        f"| {label} | {count} | {percentage(count, classified)} |"
        for label, count in final_label_rows(final_labels, label_order)
    )
    lines.extend(["", f"**Execution duration:** {format_duration(duration)}"])
    return "\n".join(lines) + "\n"


def append_github_step_summary(markdown, environ=None):
    """Append Markdown to Actions' summary file when that environment exists."""
    summary_path = (environ or os.environ).get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False
    try:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(markdown)
    except OSError as error:
        print(f"Could not write GitHub Actions job summary: {error}")
        return False
    return True
