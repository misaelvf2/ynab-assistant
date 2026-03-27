"""
Report generation — markdown and HTML output.
"""

from datetime import date
from pathlib import Path

from ynab_assistant.utils import REPORTS_DIR


def save_report(
    report_type: str, content: str, month_str: str = None
) -> tuple[Path, Path]:
    """Save a report to the reports directory in both Markdown and HTML formats.

    Args:
        report_type: Type of report (e.g., 'eating-out', 'spending', 'net-worth')
        content: Markdown content of the report
        month_str: Optional month string (YYYY-MM) for the report filename

    Returns:
        Tuple of (markdown_path, html_path)
    """
    import markdown

    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today()
    if month_str:
        base_filename = f"{month_str}_{report_type}"
    else:
        base_filename = f"{today.isoformat()}_{report_type}"

    # Save markdown
    md_path = REPORTS_DIR / f"{base_filename}.md"
    with open(md_path, "w") as f:
        f.write(content)

    # Convert to HTML and save
    html_content = markdown.markdown(content, extensions=["tables", "fenced_code"])
    html_full = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_type.replace("-", " ").title()} Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; line-height: 1.6; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        h3 {{ color: #7f8c8d; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .executive-summary {{ background: #f8f9fa; border-left: 4px solid #3498db; padding: 20px; margin: 20px 0; }}
        strong {{ color: #2c3e50; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""

    html_path = REPORTS_DIR / f"{base_filename}.html"
    with open(html_path, "w") as f:
        f.write(html_full)

    return md_path, html_path
