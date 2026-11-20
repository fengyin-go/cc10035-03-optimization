"""页面快照领域服务：保存和比对页面状态快照。

采集顺序以「抓取时间」为准，登记顺序只作为同一时刻的兜底排序。
迟到补采的快照会插进已有快照序列，因此质量报告必须保留它当初采用的
快照对，同时把插入后产生的新比较区间作为差异视图的一部分暴露出来。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


TIME_PATTERN = re.compile(
    r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def parse_capture_time(value: Any) -> datetime | None:
    """解析抓取时间，兼容 2026-11-20、2026/11/20 09:30、ISO 带时区等写法。"""
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace("/", "-")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    match = TIME_PATTERN.search(text)
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
        )
    except ValueError:
        return None


def _snapshot_order_key(row: dict[str, Any]) -> tuple[int, datetime, int]:
    """有抓取时间的按时间排在前，缺时间的按登记顺序垫后，避免打乱已有序列。"""
    captured = parse_capture_time(row.get("抓取时间"))
    if captured is not None:
        return (0, captured, int(row.get("id", 0)))
    return (1, datetime.min, int(row.get("id", 0)))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(row: dict[str, Any]) -> tuple[str, str, str, str]:
    captured = parse_capture_time(row.get("抓取时间"))
    # 同一时刻的两种写法（空格/T）视为同一份快照，避免重复登记漏判。
    captured_key = captured.isoformat() if captured else _normalize_text(row.get("抓取时间"))
    return (
        _normalize_text(row.get("页面URI")).casefold(),
        _normalize_text(row.get("DOM哈希")),
        _normalize_text(row.get("文本哈希")),
        captured_key,
    )


def _snapshot_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": row.get("id"),
        "快照ID": row.get("快照ID"),
        "抓取时间": row.get("抓取时间"),
        "DOM哈希": row.get("DOM哈希", ""),
        "文本哈希": row.get("文本哈希", ""),
        "页面URI": row.get("页面URI", ""),
    }


def _pair_key(left_id: Any, right_id: Any) -> tuple[int, int]:
    """比较区间是有方向的：永远从先采到的一份指向后采到的一份。"""
    return (int(left_id or 0), int(right_id or 0))


class PageSnapshotService(BaseModuleService):
    MODULE = "page_snapshot"
    ENTITY = "快照记录"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["快照ID", "页面URI", "DOM哈希", "文本哈希", "抓取时间", "页面大小", "是否变更"]
    REQUIRED_FIELDS = ["快照ID", "页面URI", "DOM哈希"]
    STATUS_ORDER = ["已保存", "已比对", "已过期"]
    ACTION_RULES = {"执行比对": "已保存", "标记过期": "已比对"}
    NEGATIVE_ACTIONS = []

    # ---------- 登记 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """重复登记同一份快照时返回已有记录，不再生成新的比较区间。"""
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not _normalize_text(values.get(field))
        ]
        if missing:
            return None, missing

        values = dict(values)
        fingerprint = _fingerprint(values)
        for row in store.rows(self.MODULE):
            if _fingerprint(row) == fingerprint:
                existing = dict(row)
                existing["duplicate"] = True
                existing["duplicate_of"] = row.get("id")
                store.duplicate_registrations().append({
                    "duplicate_id": row.get("id"),
                    "snapshot_id": row.get("快照ID"),
                    "页面URI": row.get("页面URI"),
                    "canonical_id": row.get("id"),
                    "抓取时间": row.get("抓取时间"),
                    "attempted_at": datetime.now().isoformat(timespec="seconds"),
                })
                return existing, []

        entry, missing = super().create_entry(values)
        if entry is not None:
            entry["duplicate"] = False
        return entry, missing

    # ---------- 快照序列与比较区间 ----------

    def page_snapshots(self, page_uri: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """返回按实际采集顺序排列的去重快照，以及被判定为重复登记的记录。"""
        target = _normalize_text(page_uri).casefold()
        rows = [
            row for row in store.rows(self.MODULE)
            if _normalize_text(row.get("页面URI")).casefold() == target
        ]
        rows.sort(key=_snapshot_order_key)

        unique: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = [
            dict(item) for item in store.duplicate_registrations()
            if _normalize_text(item.get("页面URI")).casefold() == target
        ]
        seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            marker = _fingerprint(row)
            if marker in seen:
                duplicates.append({
                    "duplicate_id": row.get("id"),
                    "snapshot_id": row.get("快照ID"),
                    "canonical_id": seen[marker].get("id"),
                    "抓取时间": row.get("抓取时间"),
                })
                continue
            seen[marker] = row
            unique.append(row)
        return unique, duplicates

    @staticmethod
    def _build_intervals(unique: list[dict[str, Any]]) -> list[dict[str, Any]]:
        intervals: list[dict[str, Any]] = []
        for left, right in zip(unique, unique[1:]):
            dom_changed = _normalize_text(left.get("DOM哈希")) != _normalize_text(right.get("DOM哈希"))
            text_changed = _normalize_text(left.get("文本哈希")) != _normalize_text(right.get("文本哈希"))
            intervals.append({
                "区间ID": f"{left.get('id')}->{right.get('id')}",
                "前快照": _snapshot_evidence(left),
                "后快照": _snapshot_evidence(right),
                "前快照ID": left.get("id"),
                "后快照ID": right.get("id"),
                "前抓取时间": left.get("抓取时间"),
                "后抓取时间": right.get("抓取时间"),
                "前DOM哈希": left.get("DOM哈希", ""),
                "后DOM哈希": right.get("DOM哈希", ""),
                "前文本哈希": left.get("文本哈希", ""),
                "后文本哈希": right.get("文本哈希", ""),
                "DOM是否变化": dom_changed,
                "文本是否变化": text_changed,
                "变化项数": (1 if dom_changed else 0) + (1 if text_changed else 0),
            })
        return intervals

    # ---------- 单快照比对（兼容旧调用） ----------

    def compare_snapshots(self, snapshot_id: int) -> dict[str, Any]:
        """比对一份快照与它之前最近一次采集，按抓取时间而不是登记顺序取前一份。"""
        snapshot = store.find(self.MODULE, snapshot_id)
        if snapshot is None:
            return {"ok": False, "reason": "快照不存在"}
        unique, _ = self.page_snapshots(str(snapshot.get("页面URI", "")))
        ids = [int(row.get("id", 0)) for row in unique]
        if snapshot_id not in ids:
            # 重复登记行不在去重序列里，退回到它指向的原始快照。
            duplicates = {
                int(item["duplicate_id"]): int(item["canonical_id"])
                for item in self.page_snapshots(str(snapshot.get("页面URI", "")))[1]
            }
            if snapshot_id in duplicates:
                snapshot_id = duplicates[snapshot_id]
                unique, _ = self.page_snapshots(str(snapshot.get("页面URI", "")))
                ids = [int(row.get("id", 0)) for row in unique]
            if snapshot_id not in ids:
                return {"ok": False, "reason": "快照不存在"}

        index = ids.index(snapshot_id)
        current = unique[index]
        previous = unique[index - 1] if index > 0 else None
        current_dom = _normalize_text(current.get("DOM哈希"))
        current_text = _normalize_text(current.get("文本哈希"))
        prev_dom = _normalize_text(previous.get("DOM哈希")) if previous else ""
        prev_text = _normalize_text(previous.get("文本哈希")) if previous else ""
        dom_changed = bool(previous) and current_dom != prev_dom
        text_changed = bool(previous) and current_text != prev_text

        return {
            "ok": True,
            "snapshot_id": current.get("id"),
            "page_uri": current.get("页面URI"),
            "has_previous": previous is not None,
            "previous_snapshot_id": previous.get("id") if previous else None,
            "dom_changed": dom_changed,
            "text_changed": text_changed,
            "change_count": (1 if dom_changed else 0) + (1 if text_changed else 0),
            "current_dom_hash": current_dom,
            "previous_dom_hash": prev_dom,
            "current_text_hash": current_text,
            "previous_text_hash": prev_text,
            "current_time": current.get("抓取时间"),
            "previous_time": previous.get("抓取时间") if previous else None,
        }

    def feed_quality_check(self, snapshot_id: int) -> dict[str, Any]:
        """将快照比对结果提供给质量检查。"""
        compare_result = self.compare_snapshots(snapshot_id)
        if not compare_result["ok"]:
            return compare_result

        same_page = True
        check_items = [
            {
                "name": "同页快照约束",
                "passed": same_page,
                "detail": f"仅比较页面 {compare_result['page_uri']} 的快照",
            },
            {
                "name": "DOM一致性",
                "passed": not compare_result["dom_changed"],
                "detail": (
                    f"{compare_result['previous_dom_hash'] or '无前序快照'} → "
                    f"{compare_result['current_dom_hash']}"
                ),
            },
            {
                "name": "文本一致性",
                "passed": not compare_result["text_changed"],
                "detail": (
                    f"{compare_result['previous_text_hash'] or '无前序快照'} → "
                    f"{compare_result['current_text_hash']}"
                ),
            },
        ]
        return {
            "ok": True,
            "snapshot_id": compare_result["snapshot_id"],
            "page_uri": compare_result["page_uri"],
            "has_changes": compare_result["change_count"] > 0,
            "change_count": compare_result["change_count"],
            "check_items": check_items,
            "recommend_rule_update": compare_result["dom_changed"],
            "compare_result": compare_result,
        }

    # ---------- 质量报告 ----------

    @staticmethod
    def _report_pairs(report: dict[str, Any]) -> list[tuple[int, int]]:
        """兼容历史报告的两种写法：新报告的区间列表，或只带两个快照标识。"""
        pairs: list[tuple[int, int]] = []
        raw_pairs = report.get("adopted_pairs")
        if isinstance(raw_pairs, list):
            for pair in raw_pairs:
                if not isinstance(pair, dict):
                    continue
                left = pair.get("left_snapshot_id", pair.get("前快照ID"))
                right = pair.get("right_snapshot_id", pair.get("后快照ID"))
                if left is not None and right is not None:
                    pairs.append(_pair_key(left, right))
        if pairs:
            return pairs

        left = report.get("left_snapshot_id", report.get("前快照ID"))
        right = report.get("right_snapshot_id", report.get("后快照ID"))
        if left is not None and right is not None:
            return [_pair_key(left, right)]

        snapshot_ids = report.get("snapshot_ids")
        if isinstance(snapshot_ids, list) and len(snapshot_ids) >= 2:
            return [
                _pair_key(snapshot_ids[index], snapshot_ids[index + 1])
                for index in range(len(snapshot_ids) - 1)
            ]
        return []

    @staticmethod
    def _pair_evidence(
        left_id: int, right_id: int, rows_by_id: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        left = rows_by_id.get(left_id)
        right = rows_by_id.get(right_id)
        left_dom = _normalize_text(left.get("DOM哈希")) if left else ""
        right_dom = _normalize_text(right.get("DOM哈希")) if right else ""
        left_text = _normalize_text(left.get("文本哈希")) if left else ""
        right_text = _normalize_text(right.get("文本哈希")) if right else ""
        dom_changed = bool(left and right) and left_dom != right_dom
        text_changed = bool(left and right) and left_text != right_text
        return {
            "left_snapshot_id": left_id,
            "right_snapshot_id": right_id,
            "left_time": left.get("抓取时间") if left else None,
            "right_time": right.get("抓取时间") if right else None,
            "left_dom_hash": left_dom,
            "right_dom_hash": right_dom,
            "left_text_hash": left_text,
            "right_text_hash": right_text,
            "dom_changed": dom_changed,
            "text_changed": text_changed,
            "change_count": (1 if dom_changed else 0) + (1 if text_changed else 0),
            "missing_snapshot": not (left and right),
        }

    def _report_view(self, report: dict[str, Any]) -> dict[str, Any]:
        page_uri = str(report.get("页面URI", ""))
        unique, _ = self.page_snapshots(page_uri)
        rows_by_id = {int(row.get("id", 0)): row for row in unique}
        intervals = self._build_intervals(unique)
        current_keys = {
            _pair_key(item["前快照ID"], item["后快照ID"]) for item in intervals
        }
        pairs = self._report_pairs(report)
        evidence = [self._pair_evidence(left, right, rows_by_id) for left, right in pairs]

        adopted_ids = {snapshot_id for pair in pairs for snapshot_id in pair}
        created_seq = report.get("created_snapshot_seq")
        if created_seq is None:
            created_seq = max(adopted_ids, default=0)
        created_seq = int(created_seq)
        end_time = report.get("evidence_end_time")
        if not end_time and pairs:
            end_row = rows_by_id.get(pairs[-1][1])
            end_time = end_row.get("抓取时间") if end_row else None
        end_dt = parse_capture_time(end_time) if end_time else None
        late_ids: list[int] = []
        for row in unique:
            row_id = int(row.get("id", 0))
            if row_id in adopted_ids or row_id <= created_seq:
                continue
            captured = parse_capture_time(row.get("抓取时间"))
            # 报告之后才登记，却落在报告证据截止时间之前，就是迟到采集。
            if end_dt is not None and captured is not None and captured < end_dt:
                late_ids.append(row_id)

        conflicts: list[dict[str, Any]] = []
        for left, right in pairs:
            if _pair_key(left, right) in current_keys:
                continue
            left_index = next(
                (index for index, row in enumerate(unique) if int(row.get("id", 0)) == left),
                None,
            )
            actual_next = None
            if left_index is not None and left_index + 1 < len(unique):
                actual_next = int(unique[left_index + 1].get("id", 0))
            conflicts.append({
                "报告编号": report.get("报告编号"),
                "报告快照对": [left, right],
                "当前实际相邻快照对": [left, actual_next] if actual_next is not None else None,
                "迟到快照ID": late_ids,
                "缺少证据": left not in rows_by_id or right not in rows_by_id,
                "说明": (
                    "报告引用的快照不属于该页面或已不存在，无法复核这段变化"
                    if left not in rows_by_id or right not in rows_by_id
                    else "迟到快照插入后，报告引用的两次抓取不再相邻，"
                         "报告采用的变化数不能代表当前相邻区间"
                ),
            })

        total_changes = sum(item["change_count"] for item in evidence)
        stale = bool(conflicts) or bool(late_ids) or any(
            item["missing_snapshot"] for item in evidence
        )
        status = "缺证据" if any(item["missing_snapshot"] for item in evidence) else (
            "需复核" if stale else "有效"
        )
        pair_label = "、".join(f"#{left}→#{right}" for left, right in pairs)
        return {
            "id": report.get("id"),
            "报告编号": report.get("报告编号"),
            "页面URI": page_uri,
            "生成时间": report.get("generated_at"),
            "证据来源": f"页面快照 {pair_label}" if pair_label else "页面快照",
            "采用快照对": [[left, right] for left, right in pairs],
            "采用快照标识": pair_label,
            "证据明细": evidence,
            "DOM结论": "有变化" if any(item["dom_changed"] for item in evidence) else "无变化",
            "文本结论": "有变化" if any(item["text_changed"] for item in evidence) else "无变化",
            "变化项数": total_changes,
            "检查清单": report.get("check_items", []),
            "规则更新建议": bool(report.get("recommend_rule_update")),
            "迟到快照ID": late_ids,
            "冲突": conflicts,
            "状态": status,
            "是否需复核": stale,
        }

    def generate_quality_report(self, values: dict[str, Any]) -> dict[str, Any]:
        """按实际采集顺序取相邻两份快照生成质量报告。"""
        page_uri = _normalize_text(values.get("页面URI") or values.get("page_uri"))
        if not page_uri:
            return {"ok": False, "message": "缺少必填字段：页面URI"}

        unique, duplicates = self.page_snapshots(page_uri)
        rows_by_id = {int(row.get("id", 0)): row for row in unique}

        explicit_ids = values.get("snapshot_ids") or values.get("快照ID列表")
        if not explicit_ids:
            left = values.get("left_snapshot_id") or values.get("前快照ID")
            right = values.get("right_snapshot_id") or values.get("后快照ID")
            if left and right:
                explicit_ids = [left, right]

        if explicit_ids:
            try:
                requested = [int(item) for item in explicit_ids]
            except (TypeError, ValueError):
                return {"ok": False, "message": "快照标识必须是数字"}
            pairs: list[tuple[int, int]] = []
            for left_id, right_id in zip(requested, requested[1:]):
                left_row = rows_by_id.get(left_id)
                right_row = rows_by_id.get(right_id)
                if left_row is None or right_row is None:
                    return {"ok": False, "message": "快照不存在或不属于同一页面"}
                if int(left_row.get("id", 0)) == int(right_row.get("id", 0)):
                    continue
                ordered = sorted(
                    [left_row, right_row],
                    key=_snapshot_order_key,
                )
                pairs.append((int(ordered[0].get("id", 0)), int(ordered[1].get("id", 0))))
            if not pairs:
                return {"ok": False, "message": "至少需要两份不同的同页快照"}
        else:
            if len(unique) < 2:
                return {"ok": False, "message": "同页快照不足两份，无法生成报告"}
            pairs = [(int(unique[-2].get("id", 0)), int(unique[-1].get("id", 0)))]

        evidence = [self._pair_evidence(left, right, rows_by_id) for left, right in pairs]
        check_items: list[dict[str, Any]] = [
            {
                "name": "同页快照约束",
                "passed": True,
                "detail": f"仅比较页面 {page_uri} 的快照",
            },
        ]
        for item in evidence:
            check_items.append({
                "name": f"DOM一致性 #{item['left_snapshot_id']}→#{item['right_snapshot_id']}",
                "passed": not item["dom_changed"],
                "detail": f"{item['left_dom_hash'] or '缺失'} → {item['right_dom_hash'] or '缺失'}",
            })
            check_items.append({
                "name": f"文本一致性 #{item['left_snapshot_id']}→#{item['right_snapshot_id']}",
                "passed": not item["text_changed"],
                "detail": f"{item['left_text_hash'] or '缺失'} → {item['right_text_hash'] or '缺失'}",
            })

        max_seq = max((int(row.get("id", 0)) for row in unique), default=0)
        latest_time = None
        for row in unique:
            captured = parse_capture_time(row.get("抓取时间"))
            if captured is not None and (latest_time is None or captured > latest_time):
                latest_time = captured
        last_pair = pairs[-1]
        end_row = rows_by_id.get(last_pair[1])
        end_time = end_row.get("抓取时间") if end_row else (
            latest_time.isoformat(sep=" ") if latest_time else None
        )

        report_id = store.next_report_id()
        report: dict[str, Any] = {
            "id": report_id,
            "报告编号": f"QR-{report_id:04d}",
            "页面URI": page_uri,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "created_snapshot_seq": max_seq,
            "evidence_end_time": end_time,
            "adopted_pairs": [
                {
                    "left_snapshot_id": item["left_snapshot_id"],
                    "right_snapshot_id": item["right_snapshot_id"],
                    "left_time": item["left_time"],
                    "right_time": item["right_time"],
                    "left_dom_hash": item["left_dom_hash"],
                    "right_dom_hash": item["right_dom_hash"],
                    "left_text_hash": item["left_text_hash"],
                    "right_text_hash": item["right_text_hash"],
                    "dom_changed": item["dom_changed"],
                    "text_changed": item["text_changed"],
                    "change_count": item["change_count"],
                }
                for item in evidence
            ],
            "left_snapshot_id": pairs[0][0],
            "right_snapshot_id": pairs[-1][1],
            "snapshot_ids": [pairs[0][0], pairs[-1][1]],
            "dom_changed": any(item["dom_changed"] for item in evidence),
            "text_changed": any(item["text_changed"] for item in evidence),
            "change_count": sum(item["change_count"] for item in evidence),
            "check_items": check_items,
            "recommend_rule_update": any(item["dom_changed"] for item in evidence),
            "重复登记": duplicates,
        }
        store.quality_reports().append(report)
        return {
            "ok": True,
            "message": f"质量报告 {report['报告编号']} 已生成",
            "report": self._report_view(report),
        }

    def list_reports(self, page_uri: str | None = None) -> list[dict[str, Any]]:
        target = _normalize_text(page_uri).casefold()
        reports = [
            report for report in store.quality_reports()
            if not target
            or _normalize_text(report.get("页面URI")).casefold() == target
        ]
        return [self._report_view(report) for report in reports]

    def latest_report(self, page_uri: str) -> dict[str, Any] | None:
        reports = self.list_reports(page_uri)
        return reports[-1] if reports else None

    # ---------- 差异数据视图 ----------

    def _stored_report(self, report: dict[str, Any] | None) -> dict[str, Any] | None:
        if not report:
            return None
        return next(
            (item for item in store.quality_reports()
             if int(item.get("id", 0)) == int(report["id"])),
            None,
        )

    def build_difference_view(self, page_uri: str) -> dict[str, Any]:
        """按实际采集顺序输出快照与相邻区间，并标出当前报告采用的证据。"""
        page_uri = _normalize_text(page_uri)
        unique, duplicates = self.page_snapshots(page_uri)
        intervals = self._build_intervals(unique)
        report = self.latest_report(page_uri)
        stored = self._stored_report(report)
        adopted_keys: set[tuple[int, int]] = set()
        if stored is not None:
            adopted_keys = {
                _pair_key(left, right) for left, right in self._report_pairs(stored)
            }

        late_ids = set(report.get("迟到快照ID", [])) if report else set()
        current_keys = {_pair_key(item["前快照ID"], item["后快照ID"]) for item in intervals}
        # 冲突只落在真正顶替了报告快照对的那段相邻区间上。
        conflict_keys = {
            _pair_key(*item["当前实际相邻快照对"])
            for item in (report or {}).get("冲突", [])
            if isinstance(item.get("当前实际相邻快照对"), list)
            and len(item["当前实际相邻快照对"]) == 2
        }

        for index, interval in enumerate(intervals):
            key = _pair_key(interval["前快照ID"], interval["后快照ID"])
            interval["采集序号"] = index + 1
            interval["与报告冲突"] = key in conflict_keys
            if key in adopted_keys:
                interval["来源"] = "当前报告"
                interval["与报告冲突"] = False
            elif interval["前快照ID"] in late_ids or interval["后快照ID"] in late_ids:
                interval["来源"] = "迟到快照"
            else:
                interval["来源"] = "未引用"
            interval["迟到快照涉及"] = (
                interval["前快照ID"] in late_ids or interval["后快照ID"] in late_ids
            )
            interval["当前相邻"] = key in current_keys

        # 报告采用的快照对可能已被迟到快照拆开，仍要在视图里保留原始证据。
        adopted_evidence: list[dict[str, Any]] = []
        rows_by_id = {int(row.get("id", 0)): row for row in unique}
        if stored is not None:
            for index, (left, right) in enumerate(self._report_pairs(stored)):
                key = _pair_key(left, right)
                if key in current_keys:
                    continue
                evidence = self._pair_evidence(left, right, rows_by_id)
                adopted_evidence.append({
                    "区间ID": f"{left}->{right}",
                    "采集序号": None,
                    "前快照": rows_by_id.get(left) and _snapshot_evidence(rows_by_id[left]),
                    "后快照": rows_by_id.get(right) and _snapshot_evidence(rows_by_id[right]),
                    "前快照ID": left,
                    "后快照ID": right,
                    "前抓取时间": evidence["left_time"],
                    "后抓取时间": evidence["right_time"],
                    "前DOM哈希": evidence["left_dom_hash"],
                    "后DOM哈希": evidence["right_dom_hash"],
                    "前文本哈希": evidence["left_text_hash"],
                    "后文本哈希": evidence["right_text_hash"],
                    "DOM是否变化": evidence["dom_changed"],
                    "文本是否变化": evidence["text_changed"],
                    "变化项数": evidence["change_count"],
                    "来源": "当前报告",
                    "当前相邻": False,
                    "与报告冲突": True,
                    "迟到快照涉及": False,
                    "说明": (
                        "报告引用的快照已缺失，无法复核这段变化"
                        if evidence["missing_snapshot"]
                        else "迟到快照插入后该快照对已不再相邻，这是报告当时采用的证据"
                    ),
                    "报告区间序号": index + 1,
                })

        ordered_rows = []
        for index, row in enumerate(unique):
            ordered_rows.append({
                "id": row.get("id"),
                "快照ID": row.get("快照ID"),
                "抓取时间": row.get("抓取时间"),
                "DOM哈希": row.get("DOM哈希", ""),
                "文本哈希": row.get("文本哈希", ""),
                "页面URI": row.get("页面URI", ""),
                "采集序号": index + 1,
                "迟到": int(row.get("id", 0)) in late_ids,
            })

        late_rows = [
            item for item in ordered_rows if item["迟到"]
        ]
        adopted_view = [
            *[interval for interval in intervals if interval["来源"] == "当前报告"],
            *adopted_evidence,
        ]
        report_evidence_total = (
            sum(item["变化项数"] for item in adopted_view) if report else 0
        )
        return {
            "ok": True,
            "页面URI": page_uri,
            "快照数": len(unique),
            "重复登记数": len(duplicates),
            "快照": ordered_rows,
            "比较区间": intervals,
            "迟到快照": late_rows,
            "重复登记": duplicates,
            "当前报告": report,
            "当前报告采用的证据": adopted_view,
            "报告采用快照对仍相邻": not adopted_evidence,
            "迟到快照涉及的新比较区间": [
                interval for interval in intervals if interval["来源"] == "迟到快照"
            ],
            "冲突": (report or {}).get("冲突", []),
            "变化项数合计": sum(item["变化项数"] for item in intervals),
            "报告变化项数": report_evidence_total,
        }

    # ---------- 统计 ----------

    def compute_staleness(self) -> dict[str, Any]:
        """计算快照过时率。"""
        rows = store.rows(self.MODULE)
        total = len(rows)
        expired = sum(1 for r in rows if r.get("status") == "已过期")
        changed = sum(1 for r in rows if r.get("是否变更") == "是" or r.get("是否变更") == "true")
        return {
            "total_snapshots": total,
            "expired_count": expired,
            "changed_count": changed,
            "staleness_ratio": round(expired / total, 2) if total > 0 else 0.0,
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["staleness"] = self.compute_staleness()
        base["quality_reports"] = len(store.quality_reports())
        return base
