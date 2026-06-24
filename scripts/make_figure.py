#!/usr/bin/env python3
"""Generate the certificate-geometry figure deterministically."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42
mpl.rcParams["font.family"] = "sans-serif"
mpl.rcParams["font.sans-serif"] = ["DejaVu Sans"]


def build(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0), constrained_layout=True)

    ax = axes[0]
    a = np.array([0.0, 1.0])
    b = np.array([1.0, 0.0])
    c = np.array([0.4, 0.4])
    x = np.linspace(-0.05, 1.05, 200)
    ax.plot(x, 0.8 - x, "k-", linewidth=1.6)
    ax.plot([a[0], b[0]], [a[1], b[1]], "--", linewidth=1.0, color="0.45")
    for point, label, offset, marker in [
        (a, "A", (0.025, 0.025), "o"),
        (b, "B", (0.025, 0.025), "^"),
        (c, "C", (0.025, 0.025), "s"),
    ]:
        ax.scatter(*point, s=34, marker=marker, zorder=3, color="black")
        ax.text(point[0] + offset[0], point[1] + offset[1], label, fontsize=10)
    ax.annotate(
        r"$\lambda=(1/2,1/2)$",
        xy=(0.18, 0.62),
        xytext=(0.06, 0.77),
        arrowprops={"arrowstyle": "->", "linewidth": 0.8},
        fontsize=9,
    )
    ax.text(0.04, 1.045, "(a)", fontsize=12, fontweight="bold")
    ax.text(0.08, 0.08, "supportable", fontsize=10)

    ax = axes[1]
    a = np.array([0.0, 1.0])
    b = np.array([1.0, 0.0])
    c = np.array([0.6, 0.6])
    mean = (a + b) / 2
    ax.plot([a[0], b[0]], [a[1], b[1]], "--", linewidth=1.1, color="0.45")
    for point, label, offset, marker, size in [
        (a, "A", (0.025, 0.025), "o", 34),
        (b, "B", (0.025, 0.025), "^", 34),
        (c, "C", (0.025, 0.025), "s", 40),
        (mean, r"$\bar y$", (-0.10, -0.08), "D", 34),
    ]:
        ax.scatter(*point, s=size, marker=marker, zorder=3, color="black")
        ax.text(point[0] + offset[0], point[1] + offset[1], label, fontsize=10)
    ax.annotate("", xy=c, xytext=mean, arrowprops={"arrowstyle": "->", "linewidth": 1.0})
    ax.plot([mean[0], c[0]], [mean[1], mean[1]], ":", linewidth=0.9, color="0.35")
    ax.plot([c[0], c[0]], [mean[1], c[1]], ":", linewidth=0.9, color="0.35")
    ax.text(0.69, 0.51, r"$\eta=0.1$", fontsize=9)
    ax.text(0.05, 0.18, r"$q=(1/2,1/2)$", fontsize=9)
    ax.text(0.05, 0.10, r"$\bar y-C=(-0.1,-0.1)$", fontsize=9)
    ax.text(0.04, 1.045, "(b)", fontsize=12, fontweight="bold")
    ax.text(0.66, 0.82, "efficient but\nunsupported", fontsize=9, ha="center")

    for ax in axes:
        ax.set_xlim(-0.08, 1.08)
        ax.set_ylim(-0.08, 1.08)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(r"$F_1$")
        ax.set_ylabel(r"$F_2$")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out")

    png = output_dir / "certificate_geometry.png"
    eps = output_dir / "certificate_geometry.eps"
    fig.savefig(png, dpi=1200, bbox_inches="tight", metadata={})
    fig.savefig(eps, bbox_inches="tight", format="eps", metadata={})
    plt.close(fig)
    # Strip non-semantic EPS header fields deterministically.
    eps_lines = []
    for line in eps.read_text(encoding="latin-1").splitlines():
        if line.startswith(("%%CreationDate:", "%%Creator:")):
            continue
        eps_lines.append(line)
    eps.write_text("\n".join(eps_lines) + "\n", encoding="latin-1")
    # Re-encode PNG without ancillary textual chunks.
    from PIL import Image
    with Image.open(png) as image:
        image.save(png, format="PNG", optimize=False)
    return png, eps


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("figures"))
    args = parser.parse_args()
    png, eps = build(args.output_dir)
    print(png)
    print(eps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
