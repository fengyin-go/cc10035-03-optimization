"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 质量报告是快照比对的取证结果，不属于资源模块，但需要跨请求保留。
        self._quality_reports: list[dict[str, Any]] = []
        self._next_report_id = 1
        # 重复登记只记录一次尝试，不写入快照表，避免产生多余比较区间。
        self._duplicate_registrations: list[dict[str, Any]] = []

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def quality_reports(self) -> list[dict[str, Any]]:
        return self._quality_reports

    def next_report_id(self) -> int:
        report_id = self._next_report_id
        self._next_report_id += 1
        return report_id

    def duplicate_registrations(self) -> list[dict[str, Any]]:
        return self._duplicate_registrations

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
