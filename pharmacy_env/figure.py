"""Draw the results figure (SVG, standard library only) from the evaluation output.

    python3 -m pharmacy_env.eval > results/eval_output.txt
    python3 -m pharmacy_env.figure results/eval_output.txt results/scores.svg

For each task: one bar per model configuration (mean score), a dot per run, the pass threshold
(mean over the seeds the models were run on) and the reference at 1.00.
"""
import re
import sys
from collections import defaultdict

TASKS = ["T1", "T2", "T3", "T4", "T5"]
TASK_NAMES = {"T1": "Safety incidents", "T2": "Shortage + allergies", "T3": "Surges + budget",
              "T4": "Ward requests", "T5": "Two-week rota"}
SERIES = [  # label in eval output, legend text, colour (validated categorical slots 1-3)
    ("deepseek-4-1-flash-1017", "DeepSeek V4.1 Flash", "#2a78d6"),
    ("deepseek-4-1-flash-1017 (high)", "DeepSeek V4.1 Flash, reasoning high", "#eb6834"),
    ("kimi-k3-1-pro (low)", "Kimi K3.1 Pro", "#1baf7a"),
]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def parse(path):
    runs, thresholds = defaultdict(list), {}
    task = None
    for line in open(path):
        m = re.match(r"^(T\d|C\d)\s+seed0", line)
        if m:
            task = m.group(1)
        m = re.match(r"^\s+pass threshold\s+([-\d. ]+)$", line)
        if m and task:
            thresholds[task] = [float(x) for x in m.group(1).split()]
        m = re.match(r"^\s+(T\d)\s+(\d)\s+(\d+)\s+(.+?)\s+(handover|full)\s+(-?[\d.]+)\s", line)
        if m:
            runs[(m.group(1), m.group(4).strip())].append((int(m.group(2)), float(m.group(6))))
    return runs, thresholds


def svg(runs, thresholds):
    W, H = 920, 490
    left, right, top, bottom = 56, 20, 92, 84
    pw, ph = W - left - right, H - top - bottom
    lo, hi = -0.2, 1.2
    y = lambda v: top + ph * (hi - max(lo, min(hi, v))) / (hi - lo)
    group = pw / len(TASKS)
    bw = 34
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">' % (W, H, W, H),
           '<rect width="100%%" height="100%%" fill="%s"/>' % SURFACE,
           '<text x="%d" y="28" font-size="17" font-weight="600" fill="%s">Model score per task '
           '(do nothing = 0, reference pharmacist = 1)</text>' % (left, INK)]
    # legend
    lx = left
    for _, text, col in SERIES:
        out.append('<rect x="%d" y="44" width="12" height="12" rx="2" fill="%s"/>' % (lx, col))
        out.append('<text x="%d" y="54" font-size="12.5" fill="%s">%s</text>' % (lx + 17, INK2, text))
        lx += 17 + 7.2 * len(text) + 22
    out.append('<line x1="%d" y1="69" x2="%d" y2="69" stroke="%s" stroke-width="2" stroke-dasharray="5 3"/>'
               % (left, left + 22, INK))
    out.append('<text x="%d" y="73" font-size="12.5" fill="%s">pass threshold (mean of seeds run)</text>'
               % (left + 28, INK2))
    out.append('<text x="%d" y="73" font-size="12.5" fill="%s">dots = individual runs; numbers under the axis '
               '= mean</text>' % (left + 290, INK2))
    # grid and axis
    for v in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                   % (left, y(v), W - right, y(v), GRID))
        out.append('<text x="%d" y="%.1f" font-size="11" fill="%s" text-anchor="end">%.1f</text>'
                   % (left - 8, y(v) + 4, INK2, v))
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1.5"/>'
               % (left, y(1.0), W - right, y(1.0), INK2))
    out.append('<text x="%d" y="%.1f" font-size="11" fill="%s" text-anchor="end">reference</text>'
               % (W - right, y(1.0) - 5, INK2))
    for i, task in enumerate(TASKS):
        gx = left + i * group
        cx0 = gx + group / 2 - (len(SERIES) * bw + (len(SERIES) - 1) * 2) / 2
        seeds = sorted({s for (t, _), rs in runs.items() if t == task for s, _ in rs})
        thr = thresholds.get(task, [])
        thr_mean = sum(thr[s] for s in seeds) / len(seeds) if seeds and thr else None
        for j, (key, text, col) in enumerate(SERIES):
            rs = runs.get((task, key), [])
            if not rs:
                continue
            x = cx0 + j * (bw + 2)
            mean = sum(sc for _, sc in rs) / len(rs)
            top_y, base = y(max(mean, 0)), y(min(mean, 0))
            out.append('<path d="M%.1f %.1f V%.1f a4 4 0 0 1 4 -4 H%.1f a4 4 0 0 1 4 4 V%.1f Z" fill="%s" '
                       'fill-opacity="0.85"><title>%s, %s: mean %.2f over %d runs</title></path>'
                       % (x, base, top_y + 4, x + bw - 4, base, col, task, text, mean, len(rs)))
            out.append('<text x="%.1f" y="%.1f" font-size="11" fill="%s" text-anchor="middle">%.2f</text>'
                       % (x + bw / 2, y(lo) + 14, INK, mean))
            for k, (_, sc) in enumerate(sorted(rs, key=lambda r: r[1])):
                out.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s" stroke="%s" stroke-width="1.5"/>'
                           % (x + bw / 2 + (k % 2 * 2 - 1) * 5 * (k > 0), y(sc), SURFACE, INK))
        if thr_mean is not None:
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2" '
                       'stroke-dasharray="5 3"><title>%s pass threshold %.2f</title></line>'
                       % (cx0 - 6, y(thr_mean), cx0 + len(SERIES) * (bw + 2) + 4, y(thr_mean), INK, task, thr_mean))
        out.append('<text x="%.1f" y="%d" font-size="13" font-weight="600" fill="%s" text-anchor="middle">%s</text>'
                   % (gx + group / 2, H - bottom + 40, INK, task))
        out.append('<text x="%.1f" y="%d" font-size="11.5" fill="%s" text-anchor="middle">%s</text>'
                   % (gx + group / 2, H - bottom + 57, INK2, TASK_NAMES[task]))
    out.append('</svg>')
    return "\n".join(out)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "results/eval_output.txt"
    dst = sys.argv[2] if len(sys.argv) > 2 else "results/scores.svg"
    runs, thresholds = parse(src)
    with open(dst, "w") as f:
        f.write(svg(runs, thresholds))
    print("wrote", dst)


if __name__ == "__main__":
    main()
