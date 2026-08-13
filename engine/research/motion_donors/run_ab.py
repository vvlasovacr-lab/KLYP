from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SANDBOX = ROOT / "sandbox_runtime"
PREVIEWS = ROOT / "previews"
PERFORMANCE = ROOT / "performance"
COMPARISONS = ROOT / "comparisons"
REMOTION = Path(r"C:\ShortsAI\remotion\node_modules\.bin\remotion.cmd")
FFPROBE = Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
NODE_BIN = Path(r"C:\Users\kolom\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin")

CANDIDATES = [
    {"id": "soft-reveal", "source": "degueba/onda", "curve": "overdamped spring + 6px blur + 10px rise", "verdict": "PROMOTE"},
    {"id": "phrase-build", "source": "degueba/onda", "curve": "4-frame restrained word stagger", "verdict": "PROMOTE"},
    {"id": "accent-highlight", "source": "degueba/onda", "curve": "two-phase text then highlight bar", "verdict": "KEEP_CURRENT"},
    {"id": "number-punch", "source": "degueba/onda", "curve": "calm number then label sequence", "verdict": "KEEP_CURRENT"},
    {"id": "decaying-micro-shake", "source": "degueba/onda", "curve": "seeded per-frame displacement with linear decay", "verdict": "PROMOTE"},
    {"id": "clean-dissolve", "source": "remotion-dev/remotion + RVE reference", "curve": "overlapping cubic opacity", "verdict": "KEEP_CURRENT"},
    {"id": "controlled-blur-transition", "source": "degueba/onda + official Remotion reference", "curve": "symmetric 7px blur arc", "verdict": "PROMOTE"},
    {"id": "clean-push", "source": "degueba/onda", "curve": "restrained 42px cubic push", "verdict": "BACKLOG"},
    {"id": "ui-callout", "source": "degueba/onda", "curve": "overdamped bubble + line draw", "verdict": "BACKLOG"},
    {"id": "subtle-vignette", "source": "degueba/onda", "curve": "static edge treatment", "verdict": "KEEP_CURRENT"},
    {"id": "rare-whip-pan", "source": "reactvideoeditor/remotion-templates", "curve": "150px displacement + 14px blur", "verdict": "REJECT"},
]


def run(command: list[str], cwd: Path) -> tuple[float, str]:
    env = os.environ.copy()
    env["PATH"] = str(NODE_BIN) + os.pathsep + str(FFMPEG.parent) + os.pathsep + env.get("PATH", "")
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return elapsed, result.stdout + result.stderr


def main() -> None:
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    PERFORMANCE.mkdir(parents=True, exist_ok=True)
    COMPARISONS.mkdir(parents=True, exist_ok=True)
    measurements = []
    for candidate in CANDIDATES:
        for variant in ("current", "donor"):
            composition = f"{candidate['id']}-{variant}"
            target = PREVIEWS / f"{composition}.mp4"
            elapsed, log = run([
                str(REMOTION), "render", "src/index.jsx", composition, str(target),
                "--codec", "h264", "--crf", "20", "--concurrency", "1", "--log", "error",
                f"--browser-executable={CHROME}",
            ], SANDBOX)
            probe = subprocess.run([
                str(FFPROBE), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate:format=duration",
                "-of", "json", str(target),
            ], text=True, encoding="utf-8", capture_output=True, check=True)
            measurements.append({
                "candidate": candidate["id"], "variant": variant,
                "render_seconds": round(elapsed, 3), "file_bytes": target.stat().st_size,
                "probe": json.loads(probe.stdout), "render_log_tail": log[-500:],
            })
            frame = PREVIEWS / f"{composition}.jpg"
            subprocess.run([str(FFMPEG), "-y", "-ss", "0.65", "-i", str(target), "-frames:v", "1", "-q:v", "2", str(frame)], capture_output=True, check=True)

    report = {
        "mode": "MOTION_DONOR_AB", "resolution": "540x960", "fps": 30,
        "runtime_dependencies_added": [], "candidates": CANDIDATES, "measurements": measurements,
    }
    (PERFORMANCE / "motion_performance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    lookup = {(x["candidate"], x["variant"]): x for x in measurements}
    for c in CANDIDATES:
        a, b = lookup[(c["id"], "current")], lookup[(c["id"], "donor")]
        rows.append(f'''<section><h2>{c["id"]} <span>{c["verdict"]}</span></h2><p>{c["curve"]} · source: {c["source"]}</p><div class="pair"><figure><video controls loop muted src="../previews/{c["id"]}-current.mp4"></video><figcaption>CURRENT · {a["render_seconds"]}s</figcaption></figure><figure><video controls loop muted src="../previews/{c["id"]}-donor.mp4"></video><figcaption>DONOR/ADAPTED · {b["render_seconds"]}s</figcaption></figure></div></section>''')
    html = '''<!doctype html><html><meta charset="utf-8"><title>ShortsAI Motion Donor A/B</title><style>body{margin:0;background:#0d0f12;color:#f2f2f2;font:16px Arial;padding:32px}h1{margin-bottom:4px}section{max-width:1160px;margin:28px auto;padding:22px;background:#171a20;border:1px solid #2b3039;border-radius:16px}h2 span{font-size:12px;color:#e4c654;margin-left:12px}.pair{display:flex;gap:24px;flex-wrap:wrap}figure{margin:0}video{width:270px;height:480px;background:#000;border-radius:10px}figcaption{padding:8px 0;color:#aeb5c1}p{color:#c3c8d0}</style><body><h1>ShortsAI MOTION_DONOR_AB</h1><p>Frozen content/timing/font/safe-zone; only motion recipe differs.</p>''' + "".join(rows) + "</body></html>"
    (COMPARISONS / "motion_donor_ab.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
