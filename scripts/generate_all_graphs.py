#!/usr/bin/env python3
"""Comprehensive Dependency Visualization using pydeps

Generates three types of dependency graphs:
1. Per-package internal dependencies (classes/modules within package)
2. Cross-package dependencies (how packages import from each other)
3. API orchestration view (how umbrella package uses everything)

Usage:
    python scripts/generate_all_graphs.py
    python scripts/generate_all_graphs.py --package canvod-aux
    python scripts/generate_all_graphs.py --type internal
    python scripts/generate_all_graphs.py --type cross-package
    python scripts/generate_all_graphs.py --type api
"""

import argparse
import subprocess
from pathlib import Path


class DependencyGraphGenerator:
    """Generate comprehensive dependency graphs using pydeps."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.packages_dir = root_dir / "packages"
        self.graphs_dir = root_dir / "dependency-graphs"
        self.graphs_dir.mkdir(exist_ok=True)

    def get_packages(self) -> list[str]:
        """Get list of all packages."""
        packages = []
        for pkg_dir in self.packages_dir.iterdir():
            if pkg_dir.is_dir() and (pkg_dir / "src").exists():
                packages.append(pkg_dir.name)
        return sorted(packages)

    def generate_package_internal(self, package_name: str) -> Path:
        """Generate internal dependency graph for a single package.
        Shows how modules/classes within the package depend on each other.
        """
        pkg_dir = self.packages_dir / package_name
        src_dir = pkg_dir / "src"
        output_file = self.graphs_dir / f"{package_name}-internal.svg"

        print(f"📦 Generating internal dependencies for {package_name}...")

        # Find the main module (canvod.readers, canvod.auxiliary, etc.)
        module_path = None
        for path in src_dir.glob("canvod/*"):
            if path.is_dir() and not path.name.startswith("_"):
                module_path = f"canvod.{path.name}"
                break

        if not module_path:
            print(f"  ⚠️  Could not find module for {package_name}")
            return None

        cmd = [
            str(Path.home() / ".local/bin/uv"),
            "run",
            "pydeps",
            module_path,
            "--max-bacon=2",  # Only show 2 levels deep
            "--cluster",  # Cluster by module
            "--noshow",  # Don't open browser
            "-o",
            str(output_file),
            "--exclude=tests",
            "--exclude=setup",
            "--rmprefix",
            "canvod.",  # Simplify labels
        ]

        try:
            subprocess.run(cmd, cwd=pkg_dir, capture_output=True, check=True, text=True)
            print(f"  ✅ Created {output_file.name}")
            return output_file
        except subprocess.CalledProcessError as e:
            print(f"  ❌ Error: {e.stderr}")
            return None

    def generate_cross_package(self) -> Path:
        """Generate cross-package dependency graph.
        Shows how packages import from each other.
        """
        output_file = self.graphs_dir / "cross-package-dependencies.svg"

        print("🔗 Generating cross-package dependencies...")

        # Create a temporary script that imports all packages
        temp_script = self.graphs_dir / "_temp_all_imports.py"
        imports = []
        for pkg in self.get_packages():
            module_name = pkg.replace("-", ".")
            imports.append(
                f"try:\n    import {module_name}\nexcept ImportError:\n    pass"
            )

        temp_script.write_text("\n".join(imports))

        cmd = [
            str(Path.home() / ".local/bin/uv"),
            "run",
            "pydeps",
            str(temp_script),
            "--max-bacon=2",
            "--cluster",
            "--noshow",
            "-o",
            str(output_file),
            "--only",
            "canvod",  # Only show canvod packages
        ]

        try:
            subprocess.run(
                cmd, cwd=self.root_dir, capture_output=True, check=True, text=True
            )
            print(f"  ✅ Created {output_file.name}")
            temp_script.unlink()  # Clean up
            return output_file
        except subprocess.CalledProcessError as e:
            print(f"  ❌ Error: {e.stderr}")
            if temp_script.exists():
                temp_script.unlink()
            return None

    def generate_api_orchestration(self) -> Path:
        """Generate API orchestration graph.
        Shows how the umbrella package (canvodpy) uses all other packages.
        """
        output_file = self.graphs_dir / "api-orchestration.svg"
        canvodpy_dir = self.root_dir / "canvodpy"

        if not canvodpy_dir.exists():
            print("⚠️  canvodpy umbrella package not found")
            return None

        print("🎯 Generating API orchestration view...")

        cmd = [
            str(Path.home() / ".local/bin/uv"),
            "run",
            "pydeps",
            "canvodpy",
            "--max-bacon=3",
            "--cluster",
            "--noshow",
            "-o",
            str(output_file),
            "--only",
            "canvod",
        ]

        try:
            subprocess.run(
                cmd, cwd=self.root_dir, capture_output=True, check=True, text=True
            )
            print(f"  ✅ Created {output_file.name}")
            return output_file
        except subprocess.CalledProcessError as e:
            print(f"  ❌ Error: {e.stderr}")
            return None

    def generate_all_internal(self):
        """Generate internal graphs for all packages."""
        packages = self.get_packages()
        print(
            f"\n📊 Generating internal dependencies for {len(packages)} packages...\n"
        )

        for pkg in packages:
            self.generate_package_internal(pkg)
            print()

    def generate_all(self):
        """Generate all dependency graphs."""
        print("=" * 70)
        print("COMPREHENSIVE DEPENDENCY GRAPH GENERATION")
        print("=" * 70)
        print()

        # 1. Internal dependencies for each package
        self.generate_all_internal()

        # 2. Cross-package dependencies
        print("=" * 70)
        self.generate_cross_package()
        print()

        # 3. API orchestration
        print("=" * 70)
        self.generate_api_orchestration()
        print()

        print("=" * 70)
        print("✅ All graphs generated in:", self.graphs_dir)
        print("=" * 70)

    def create_index_html(self):
        """Create an HTML index to view all graphs."""
        packages = self.get_packages()

        html = """<!DOCTYPE html>
<html>
<head>
    <title>canVODpy Dependency Graphs</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
            background: #f5f5f5;
        }
        h1 { color: #003366; border-bottom: 3px solid #66ccff; }
        h2 { color: #0066cc; margin-top: 40px; }
        .graph-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .graph-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .graph-card h3 {
            margin-top: 0;
            color: #003366;
        }
        .graph-card img {
            width: 100%;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        .overview-graph {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .overview-graph img {
            width: 100%;
            max-width: 1000px;
            margin: 0 auto;
            display: block;
        }
    </style>
</head>
<body>
    <h1>🔍 canVODpy Dependency Graphs</h1>
    <p><strong>Generated:</strong> <code>just deps-all</code></p>

    <h2>🎯 API Orchestration</h2>
    <div class="overview-graph">
        <p>How the umbrella package (<code>canvodpy</code>) orchestrates all other packages.</p>
        <img src="api-orchestration.svg" alt="API Orchestration">
    </div>

    <h2>🔗 Cross-Package Dependencies</h2>
    <div class="overview-graph">
        <p>How packages import from each other.</p>
        <img src="cross-package-dependencies.svg" alt="Cross-Package Dependencies">
    </div>

    <h2>📦 Per-Package Internal Dependencies</h2>
    <p>How modules and classes within each package depend on each other.</p>

    <div class="graph-grid">
"""

        for pkg in packages:
            graph_file = f"{pkg}-internal.svg"
            if (self.graphs_dir / graph_file).exists():
                html += f"""
        <div class="graph-card">
            <h3>{pkg}</h3>
            <img src="{graph_file}" alt="{pkg} internal dependencies">
        </div>
"""

        html += """
    </div>

    <hr style="margin: 40px 0;">
    <p style="text-align: center; color: #666;">
        Generated with <a href="https://github.com/thebjorn/pydeps">pydeps</a>
    </p>
</body>
</html>
"""

        index_file = self.graphs_dir / "index.html"
        index_file.write_text(html)
        print(f"📄 Created index.html - open {index_file}")
        return index_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate comprehensive dependency graphs"
    )
    parser.add_argument(
        "--type",
        choices=["internal", "cross-package", "api", "all"],
        default="all",
        help="Type of graph to generate",
    )
    parser.add_argument(
        "--package", help="Generate only for specific package (with --type internal)"
    )
    parser.add_argument(
        "--open", action="store_true", help="Open index.html after generation"
    )
    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent
    generator = DependencyGraphGenerator(root_dir)

    if args.type == "all":
        generator.generate_all()
        generator.create_index_html()
        if args.open:
            import webbrowser

            webbrowser.open((generator.graphs_dir / "index.html").as_uri())

    elif args.type == "internal":
        if args.package:
            generator.generate_package_internal(args.package)
        else:
            generator.generate_all_internal()
            generator.create_index_html()

    elif args.type == "cross-package":
        generator.generate_cross_package()

    elif args.type == "api":
        generator.generate_api_orchestration()


if __name__ == "__main__":
    main()
