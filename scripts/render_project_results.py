"""Render the saved research summaries without inventing missing metrics."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    evidence = ROOT / "docs" / "results"
    book = json.loads((evidence / "order_book_summary.json").read_text(encoding="utf-8"))
    execution = json.loads((evidence / "execution_metrics.json").read_text(encoding="utf-8"))
    background, panel, ink, muted = "#101827", "#1a2638", "#edf3fa", "#a9b9cd"
    bid_color, ask_color = "#51d6b5", "#78a9ff"
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 12,
        "text.color": ink, "axes.labelcolor": muted,
        "xtick.color": muted, "ytick.color": muted,
        "axes.facecolor": panel, "figure.facecolor": background,
        "axes.edgecolor": panel, "savefig.facecolor": background,
    })
    fig = plt.figure(figsize=(16, 10), dpi=160)
    fig.text(.055, .94, "TREASURY FUTURES EXECUTION ANALYTICS & TCA ENGINE", fontsize=28, weight="bold")
    fig.text(.055, .903, "CME rates futures  /  Recorded research results  /  ZNH6  /  2026-02-24 session",
             fontsize=13, color=muted)
    spread = book["final_best_ask_px"] - book["final_best_bid_px"]
    cards = [("BOOK SNAPSHOTS", f'{book["snapshots"]:,}'),
             ("FINAL RESTING ORDERS", f'{book["final_num_orders"]:,}'),
             ("FINAL SPREAD", f"{spread} tick"),
             ("EXECUTION FILLS", f'{execution["fills"]:,}')]
    for index, (label, value) in enumerate(cards):
        x = .055 + index * .228
        fig.text(x, .815, value, fontsize=30, weight="bold", color=bid_color)
        fig.text(x, .78, label, fontsize=10, color=muted)

    book_ax = fig.add_axes((.10, .365, .37, .30))
    sizes = [book["final_best_bid_sz"], book["final_best_ask_sz"]]
    prices = [book["final_best_bid_px"], book["final_best_ask_px"]]
    book_ax.barh([1, 0], sizes, color=[bid_color, ask_color], height=.42)
    book_ax.set_yticks([1, 0], [f"Bid\n{prices[0]:,} ticks", f"Ask\n{prices[1]:,} ticks"])
    book_ax.set_xlim(0, max(sizes) * 1.3)
    book_ax.set_ylim(-.6, 1.6)
    book_ax.set_xlabel("Displayed quantity (lots)")
    book_ax.set_title("Final best bid and ask", loc="left", color=ink, pad=18, fontsize=17)
    for y, size in zip([1, 0], sizes):
        book_ax.text(size + max(sizes) * .035, y, f"{size:,}", va="center", weight="bold")

    exec_ax = fig.add_axes((.60, .365, .33, .30))
    quantities = [execution["submitted_qty"], execution["filled_qty"]]
    exec_ax.bar([0, 1], quantities, color=[ask_color, bid_color], width=.43)
    exec_ax.set_xticks([0, 1], ["Submitted", "Filled"])
    exec_ax.set_ylim(0, max(quantities + [1]) * 1.35)
    exec_ax.set_ylabel("Quantity (lots)")
    exec_ax.set_title("Separate saved execution run", loc="left", color=ink, pad=18, fontsize=17)
    for x, qty in enumerate(quantities):
        exec_ax.text(x, qty + max(quantities + [1]) * .04, str(qty), ha="center", weight="bold", fontsize=16)
    for ax in (book_ax, exec_ax):
        ax.spines[["top", "right"]].set_visible(False)

    fig.text(.055, .255, "WHAT THIS SHOWS", fontsize=11, color=bid_color, weight="bold")
    fig.text(.055, .222, "Order-level reconstruction and saved execution metrics; no profitability conclusion.", fontsize=14)
    fig.text(.055, .174, "No fills: slippage and markouts are unavailable. Execution configuration was not preserved.",
             fontsize=12, color=muted)
    fig.text(.055, .143, "HFTBacktest integration currently maps and validates feeds; a second-engine execution run is not implemented.",
             fontsize=12, color=muted)
    fig.text(.055, .081, "Sources: docs/results/order_book_summary.json + execution_metrics.json", fontsize=10, color=muted)
    fig.text(.055, .057, "Historical local artifacts. Book and execution summaries are separate runs; raw data is excluded from the repository.",
             fontsize=10, color=muted)
    output = ROOT / "docs" / "assets" / "project_results.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()

