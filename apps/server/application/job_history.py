"""Actor-owned keyset traversal with live per-job authorization before projection."""

from sqlalchemy import text

from apps.server.domain.errors import DomainError


def history_page(
    auth,
    table,
    predicate,
    parameters,
    authorize,
    project,
    after=None,
    limit=25,
    since=None,
    until=None,
    status=None,
):
    assert table in {"export_job", "import_job"}
    if any(value and value.utcoffset() is None for value in (since, until)):
        raise DomainError("INVALID_FILTER", "Thời điểm cần múi giờ.")
    if since and until and since > until:
        raise DomainError("INVALID_FILTER", "Ngày bắt đầu phải trước ngày kết thúc.")
    params = dict(
        parameters, actor=auth.principal.user_id, after=after, since=since, until=until, status=status
    )
    clauses = ["requested_by=:actor", predicate]
    for key, operator in (("since", ">="), ("until", "<")):
        if params[key] is not None:
            clauses.append(f"created_at{operator}:{key}")
    if status:
        clauses.append("status=:status")
    # Cursor resolves only inside the current actor. Unknown/foreign IDs reveal nothing.
    if after:
        anchor = auth.connection.execute(
            text(f"SELECT created_at,id FROM wms.{table} WHERE id=:after AND requested_by=:actor"), params
        ).first()
        if anchor is None:
            raise DomainError("INVALID_FILTER", "Con trỏ lịch sử không hợp lệ; tải lại trang đầu.")
        params.update(anchor_time=anchor.created_at, anchor_id=anchor.id)
        clauses.append("(created_at,id)<(:anchor_time,:anchor_id)")
    items = []
    while True:
        rows = (
            auth.connection.execute(
                text(
                    f"SELECT * FROM wms.{table} WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC,id DESC LIMIT 100"
                ),
                params,
            )
            .mappings()
            .all()
        )
        for row in rows:
            try:
                authorize(row)
            except DomainError as error:
                if error.code not in {"FORBIDDEN", "NOT_FOUND"}:
                    raise
                continue
            items.append(project(row))
            if len(items) > limit:
                return dict(items=items[:limit], next_after=items[limit - 1]["id"])
        if len(rows) < 100:
            return dict(items=items, next_after=None)
        params.update(anchor_time=rows[-1]["created_at"], anchor_id=rows[-1]["id"])
        boundary = "(created_at,id)<(:anchor_time,:anchor_id)"
        if boundary not in clauses:
            clauses.append(boundary)
