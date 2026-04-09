#!/usr/bin/env python3
"""
模块依赖关系分析工具
分析Python项目中的模块依赖关系，识别循环依赖和高耦合模块
"""

import ast
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple


class DependencyAnalyzer:
    def __init__(self, project_root: str, source_dir: str = "simple_trade"):
        self.project_root = Path(project_root)
        self.source_dir = self.project_root / source_dir
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.module_files: Dict[str, Path] = {}

    def analyze(self):
        """分析所有Python文件的依赖关系"""
        print(f"正在分析 {self.source_dir} 目录...")

        # 收集所有Python文件
        for py_file in self.source_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            module_name = self._get_module_name(py_file)
            self.module_files[module_name] = py_file

            # 分析导入语句
            imports = self._extract_imports(py_file)
            self.dependencies[module_name] = imports

        print(f"共分析 {len(self.module_files)} 个模块")

    def _get_module_name(self, file_path: Path) -> str:
        """将文件路径转换为模块名"""
        rel_path = file_path.relative_to(self.project_root)
        parts = list(rel_path.parts[:-1]) + [rel_path.stem]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def _extract_imports(self, file_path: Path) -> Set[str]:
        """提取文件中的导入语句"""
        imports = set()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".")[0]
                        if module == "simple_trade":
                            imports.add(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("simple_trade"):
                        imports.add(node.module)

        except Exception as e:
            print(f"警告: 无法解析 {file_path}: {e}")

        return imports

    def find_circular_dependencies(self) -> List[List[str]]:
        """查找循环依赖"""
        cycles = []
        visited = set()

        def dfs(module: str, path: List[str]):
            if module in path:
                # 找到循环
                cycle_start = path.index(module)
                cycle = path[cycle_start:] + [module]
                if cycle not in cycles and list(reversed(cycle)) not in cycles:
                    cycles.append(cycle)
                return

            if module in visited:
                return

            visited.add(module)
            path.append(module)

            for dep in self.dependencies.get(module, []):
                # 只关注项目内部的依赖
                if dep.startswith("simple_trade"):
                    dfs(dep, path.copy())

        for module in self.dependencies:
            visited.clear()
            dfs(module, [])

        return cycles

    def calculate_coupling(self) -> Dict[str, int]:
        """计算每个模块的耦合度（被依赖次数）"""
        coupling = defaultdict(int)

        for module, deps in self.dependencies.items():
            for dep in deps:
                if dep.startswith("simple_trade"):
                    coupling[dep] += 1

        return dict(coupling)

    def find_high_coupling_modules(self, threshold: int = 10) -> List[Tuple[str, int]]:
        """查找高耦合模块"""
        coupling = self.calculate_coupling()
        high_coupling = [(mod, count) for mod, count in coupling.items() if count >= threshold]
        return sorted(high_coupling, key=lambda x: x[1], reverse=True)

    def generate_report(self) -> str:
        """生成分析报告"""
        report = []
        report.append("=" * 80)
        report.append("模块依赖关系分析报告")
        report.append("=" * 80)
        report.append("")

        # 1. 循环依赖
        report.append("## 1. 循环依赖检测")
        report.append("")
        cycles = self.find_circular_dependencies()

        if cycles:
            report.append(f"⚠️  发现 {len(cycles)} 个循环依赖:")
            report.append("")
            for i, cycle in enumerate(cycles, 1):
                report.append(f"### 循环 {i}:")
                for j, module in enumerate(cycle):
                    if j < len(cycle) - 1:
                        report.append(f"  {module}")
                        report.append(f"    ↓")
                    else:
                        report.append(f"  {module} (回到起点)")
                report.append("")
        else:
            report.append("✅ 未发现循环依赖")
            report.append("")

        # 2. 高耦合模块
        report.append("## 2. 高耦合模块 (被依赖次数 >= 10)")
        report.append("")
        high_coupling = self.find_high_coupling_modules(threshold=10)

        if high_coupling:
            report.append(f"发现 {len(high_coupling)} 个高耦合模块:")
            report.append("")
            for module, count in high_coupling:
                report.append(f"  - {module}: 被 {count} 个模块依赖")
        else:
            report.append("✅ 未发现高耦合模块")

        report.append("")

        # 3. 模块依赖统计
        report.append("## 3. 模块依赖统计")
        report.append("")

        # 依赖最多的模块
        dep_counts = [(mod, len(deps)) for mod, deps in self.dependencies.items()]
        dep_counts.sort(key=lambda x: x[1], reverse=True)

        report.append("### 依赖最多的模块 (Top 10):")
        report.append("")
        for module, count in dep_counts[:10]:
            if count > 0:
                report.append(f"  - {module}: 依赖 {count} 个模块")

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)


def main():
    analyzer = DependencyAnalyzer("d:\\Program Files\\futu_trade_sys")
    analyzer.analyze()

    report = analyzer.generate_report()

    # 保存报告
    output_file = Path("d:\\Program Files\\futu_trade_sys\\discuss\\dependency-analysis.txt")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告已保存到: {output_file}")


if __name__ == "__main__":
    main()
