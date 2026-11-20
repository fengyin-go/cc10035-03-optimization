"""质量检查领域服务：对抽取结果进行多维度质量把关。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QualityCheckService(BaseModuleService):
    MODULE = "quality_check"
    ENTITY = "检查规则"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["规则名称", "检查字段", "检查类型", "阈值设置", "告警动作", "适用模块", "是否阻断"]
    REQUIRED_FIELDS = ["规则名称", "检查字段", "检查类型"]
    STATUS_ORDER = ["草稿", "已启用", "已停用"]
    ACTION_RULES = {"启用规则": "草稿", "停用规则": "已启用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    def check_entity_quality(self, entity_id: str) -> dict[str, Any]:
        """对单个实体抽取结果进行质量评分。"""
        entry = store.find("entity_extract", int(entity_id) if entity_id.isdigit() else 0)
        if entry is None:
            alt = [r for r in store.rows("entity_extract") if r.get("实体ID") == entity_id]
            if not alt:
                return {"ok": False, "reason": "实体不存在"}
            entry = alt[0]

        confidence_str = entry.get("置信度", "0.5")
        try:
            confidence = float(confidence_str)
        except (ValueError, TypeError):
            confidence = 0.5

        has_id = bool(entry.get("实体ID", "").strip())
        has_type = bool(entry.get("实体类型", "").strip())
        has_name = bool(entry.get("实体名称", "").strip())
        has_source = bool(entry.get("页面来源", "").strip())
        has_snippet = bool(entry.get("原文片段", "").strip())

        checks = {
            "confidence_threshold": confidence >= 0.5,
            "entity_id_present": has_id,
            "entity_type_present": has_type,
            "entity_name_present": has_name,
            "source_page_present": has_source,
            "original_snippet_present": has_snippet,
        }
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        score = round(passed / total, 2)

        quality_rules = [
            r for r in store.rows(self.MODULE)
            if r.get("status") == "已启用" and r.get("适用模块") in ("entity_extract", "*", "全部")
        ]
        return {
            "ok": True,
            "entity_id": entity_id,
            "quality_score": score,
            "checks": checks,
            "applied_rules": len(quality_rules),
            "passed_all": passed == total,
            "result": "通过" if passed == total else "预警",
        }

    def run_quality_pipeline(self) -> dict[str, Any]:
        """对所有已启用检查规则的跨模块批量质量审计。"""
        rules = [r for r in store.rows(self.MODULE) if r.get("status") == "已启用"]
        results: list[dict[str, Any]] = []
        for rule in rules:
            applicable_module = rule.get("适用模块", "")
            if applicable_module in ("entity_extract", "*"):
                target_rows = store.rows("entity_extract")
                for row in target_rows:
                    results.append({
                        "rule_name": rule.get("规则名称"),
                        "target_module": "entity_extract",
                        "target_id": row.get("id"),
                        "check_type": rule.get("检查类型"),
                        "threshold": rule.get("阈值设置"),
                        "blocking": rule.get("是否阻断") == "是",
                        "passed": self.check_entity_quality(row.get("实体ID", str(row.get("id", ""))))["passed_all"],
                    })
            if applicable_module in ("page_snapshot", "*"):
                target_rows = store.rows("page_snapshot")
                for row in target_rows:
                    results.append({
                        "rule_name": rule.get("规则名称"),
                        "target_module": "page_snapshot",
                        "target_id": row.get("id"),
                        "check_type": rule.get("检查类型"),
                        "threshold": rule.get("阈值设置"),
                        "blocking": rule.get("是否阻断") == "是",
                        "passed": row.get("DOM哈希", "") != row.get("文本哈希", ""),
                    })

        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        return {
            "ok": True,
            "total_checks": total,
            "passed_checks": passed,
            "pass_ratio": round(passed / total, 2) if total > 0 else 0.0,
            "results": results[:20],
        }

    def check_snapshot_consistency(self, snapshot_id: int) -> dict[str, Any]:
        """校验页面快照一致性，联动质量检查→探针→快照的验证链路。"""
        from app.services.page_snapshot import PageSnapshotService
        pss = PageSnapshotService()
        feed = pss.feed_quality_check(snapshot_id)
        if not feed["ok"]:
            return feed

        rule_count = len([r for r in store.rows(self.MODULE)
                          if r.get("status") == "已启用"
                          and r.get("适用模块") in ("page_snapshot", "*")])
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "has_changes": feed["has_changes"],
            "change_count": feed.get("change_count", 0),
            "check_items": feed["check_items"],
            "recommend_rule_update": feed["recommend_rule_update"],
            "active_check_rules": rule_count,
            "verdict": "需更新模板" if feed["recommend_rule_update"] else "通过",
        }

    def create_snapshot_report(self, values: dict[str, Any]) -> dict[str, Any]:
        """按快照采集顺序生成质量报告，检查清单由快照差异回写。"""
        from app.services.page_snapshot import PageSnapshotService
        return PageSnapshotService().generate_quality_report(values)

    def list_snapshot_reports(self, page_uri: str | None = None) -> dict[str, Any]:
        from app.services.page_snapshot import PageSnapshotService
        reports = PageSnapshotService().list_reports(page_uri)
        return {"ok": True, "items": reports, "total": len(reports)}

    def snapshot_difference_view(self, page_uri: str) -> dict[str, Any]:
        from app.services.page_snapshot import PageSnapshotService
        return PageSnapshotService().build_difference_view(page_uri)

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        rules = store.rows(self.MODULE)
        base["quality_stats"] = {
            "total_rules": len(rules),
            "active_rules": sum(1 for r in rules if r.get("status") == "已启用"),
            "blocking_rules": sum(1 for r in rules if r.get("是否阻断") == "是"),
            "snapshot_reports": len(store.quality_reports()),
        }
        return base