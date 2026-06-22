from __future__ import annotations

import csv
import html
import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


def _display(value: Any) -> str:
    if value is None:
        return ""

    if hasattr(value, "value"):
        value = value.value

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return format(value, "f")

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    return str(value)


def _xlsx_value(value: Any) -> Any:
    if value is None:
        return None

    if hasattr(value, "value"):
        value = value.value

    if isinstance(value, (datetime, date, Decimal, int, float, bool)):
        return value

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    return str(value)


def _is_money_column(column: str) -> bool:
    return any(
        marker in column
        for marker in (
            "cost",
            "price",
            "amount",
            "value",
            "total",
            "rate",
        )
    )


def render_csv(
    columns: list[str],
    labels: dict[str, str],
    rows: list[dict[str, Any]],
) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow([labels[column] for column in columns])

    for row in rows:
        writer.writerow([_display(row.get(column)) for column in columns])

    return ("\ufeff" + output.getvalue()).encode("utf-8")


def render_xlsx(
    columns: list[str],
    labels: dict[str, str],
    rows: list[dict[str, Any]],
) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Export"
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = (
        f"A1:{get_column_letter(len(columns))}{max(1, len(rows) + 1)}"
    )

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)

    for index, column in enumerate(columns, start=1):
        cell = worksheet.cell(row=1, column=index, value=labels[column])
        cell.fill = header_fill
        cell.font = header_font

    for row_index, row in enumerate(rows, start=2):
        for column_index, column in enumerate(columns, start=1):
            cell = worksheet.cell(
                row=row_index,
                column=column_index,
                value=_xlsx_value(row.get(column)),
            )

            if _is_money_column(column) and isinstance(
                row.get(column),
                (Decimal, int, float),
            ):
                cell.number_format = "#,##0.00"

            if isinstance(row.get(column), datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"

            if isinstance(row.get(column), date):
                cell.number_format = "yyyy-mm-dd"

    for index, column in enumerate(columns, start=1):
        values = [labels[column]] + [
            _display(row.get(column))
            for row in rows[:200]
        ]
        width = min(max(max((len(value) for value in values), default=10) + 2, 12), 42)
        worksheet.column_dimensions[
            get_column_letter(index)
        ].width = width

    output = BytesIO()
    workbook.save(output)

    return output.getvalue()


def render_pdf(
    title: str,
    columns: list[str],
    labels: dict[str, str],
    rows: list[dict[str, Any]],
    filters: dict[str, Any],
) -> bytes:
    from xhtml2pdf import pisa

    rendered_filters = [
        (
            html.escape(str(key).replace("_", " ").title()),
            html.escape(_display(value)),
        )
        for key, value in filters.items()
        if value not in (None, "", False)
    ]

    filter_html = (
        "<p class='filters'>No filters applied</p>"
        if not rendered_filters
        else "<ul class='filters'>"
        + "".join(
            f"<li><strong>{key}:</strong> {value}</li>"
            for key, value in rendered_filters
        )
        + "</ul>"
    )

    header_html = "".join(
        f"<th>{html.escape(labels[column])}</th>"
        for column in columns
    )

    row_html = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_display(row.get(column)))}</td>"
            for column in columns
        )
        + "</tr>"
        for row in rows
    )

    document = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          @page {{
            size: A4 landscape;
            margin: 18mm 12mm;
          }}
          body {{
            font-family: Helvetica;
            color: #1d2433;
            font-size: 8.5pt;
          }}
          .brand {{
            color: #1f4e78;
            font-size: 17pt;
            font-weight: bold;
            letter-spacing: 1px;
          }}
          h1 {{
            font-size: 15pt;
            margin: 5px 0 3px;
          }}
          .meta {{
            color: #667085;
            margin: 0 0 10px;
          }}
          .filters {{
            margin: 4px 0 12px;
            padding-left: 14px;
          }}
          table {{
            width: 100%;
            border-collapse: collapse;
          }}
          th {{
            background: #1f4e78;
            color: white;
            font-weight: bold;
          }}
          th, td {{
            border: 0.4pt solid #d0d5dd;
            padding: 4px;
            vertical-align: top;
          }}
          tr:nth-child(even) {{
            background: #f8fafc;
          }}
        </style>
      </head>
      <body>
        <div class="brand">PORSA</div>
        <h1>{html.escape(title)}</h1>
        <p class="meta">Generated at {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")} · Rows: {len(rows)}</p>
        {filter_html}
        <table>
          <thead><tr>{header_html}</tr></thead>
          <tbody>{row_html}</tbody>
        </table>
      </body>
    </html>
    """

    output = BytesIO()
    result = pisa.CreatePDF(document, dest=output, encoding="utf-8")

    if result.err:
        raise ValueError("PDF rendering failed")

    return output.getvalue()


def render_export(
    export_format: str,
    title: str,
    columns: list[str],
    labels: dict[str, str],
    rows: list[dict[str, Any]],
    filters: dict[str, Any],
) -> tuple[bytes, str, str]:
    if export_format == "csv":
        return (
            render_csv(columns, labels, rows),
            "text/csv; charset=utf-8",
            "csv",
        )

    if export_format == "xlsx":
        return (
            render_xlsx(columns, labels, rows),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )

    if export_format == "pdf":
        return (
            render_pdf(title, columns, labels, rows, filters),
            "application/pdf",
            "pdf",
        )

    raise ValueError("Unsupported export format")
