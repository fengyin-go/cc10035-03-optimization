"""统一资源接口：查询、导出、登记和动作按模块 key 分派到领域服务。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services import service_for

router = APIRouter(prefix="/api", tags=["业务资源"])


def require_service(module: str):
    service = service_for(module)
    if service is None:
        raise HTTPException(status_code=404, detail=f"未知业务模块：{module}")
    return service


@router.get("/{module}", response_model=PageResult[dict])
def list_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, total = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{module}/export")
def export_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, _ = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=1, size=1_000_000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *service.LIST_FIELDS, "status"])
    for item in items:
        values = [item.get("id"), *(item.get(field, "") for field in service.LIST_FIELDS),
                  item.get("status", "")]
        writer.writerow([
            "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
            for value in values
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{module}.csv"'},
    )


@router.get("/{module}/snapshot-difference", response_model=dict)
def snapshot_difference(
    module: str,
    page_uri: str = Query(default="", alias="页面URI"),
) -> dict[str, Any]:
    """快照差异数据视图：按实际采集顺序列出同页快照与比较区间。"""
    service = require_service(module)
    builder = getattr(service, "build_difference_view", None)
    if builder is None:
        raise HTTPException(status_code=404, detail=f"{module} 不支持快照差异视图")
    if not page_uri.strip():
        raise HTTPException(status_code=400, detail="缺少查询参数：页面URI")
    return builder(page_uri)


@router.get("/{module}/reports", response_model=dict)
def list_reports(
    module: str,
    page_uri: str | None = Query(default=None, alias="页面URI"),
) -> dict[str, Any]:
    """质量报告列表：每次生成都会保留当时的证据，供迟到快照复核。"""
    service = require_service(module)
    lister = getattr(service, "list_snapshot_reports", None)
    if lister is None:
        raise HTTPException(status_code=404, detail=f"{module} 不支持质量报告")
    return lister(page_uri)


@router.post("/{module}/reports", response_model=dict)
def create_report(module: str, payload: EntryPayload) -> dict[str, Any]:
    service = require_service(module)
    creator = getattr(service, "create_snapshot_report", None)
    if creator is None:
        raise HTTPException(status_code=404, detail=f"{module} 不支持质量报告")
    result = creator(payload.values)
    if not result.get("ok"):
        return result
    return result


@router.get("/{module}/{entry_id}", response_model=dict)
def get_entry(module: str, entry_id: int) -> dict[str, Any]:
    service = require_service(module)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    return entry


@router.post("/{module}", response_model=ActionResult)
def create_entry(module: str, payload: EntryPayload) -> ActionResult:
    service = require_service(module)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry.get("duplicate"):
        return ActionResult(
            ok=True, message=f"该{service.ENTITY}已登记，复用快照 {entry.get('id')}", entry=entry)
    return ActionResult(ok=True, message=f"{service.ENTITY}已登记", entry=entry)


@router.post("/{module}/{entry_id}/actions", response_model=ActionResult)
def run_action(module: str, entry_id: int, payload: ActionPayload) -> ActionResult:
    service = require_service(module)
    entry, message = service.run_action(entry_id, payload.action.strip())
    return ActionResult(ok=entry is not None, message=message, entry=entry)
