# Job Isolation, Batch Evaluation, and Director Inspector

The production editing chain is unchanged:

`Whisper → Speech Edit → AI Director → Director Execution Plan → Clip Visual Adapter → Montage Plan → Remotion → Final MP4`

## Commands

Run one production job:

```powershell
py run.py --file input/video.mp4
```

Run the same production pipeline and additionally create developer diagnostics:

```powershell
py run.py --file input/video.mp4 --debug
```

Create plans and Director Inspector without rendering:

```powershell
py run.py --file input/video.mp4 --preview --debug
```

Put future evaluation sources in `input_tests/` and run them sequentially:

```powershell
py batch_eval.py --input input_tests
```

Use an unseen set without changing any profile:

```powershell
py batch_eval.py --input input_holdout --debug
```

Batch mode always uses the same `AutomatedPipeline.process_one()` used by `run.py`.
It does not tune profiles and an error in one job does not stop the next source.

## Per-job layout

Every attempt creates a unique `job_id` and directory:

```text
work/jobs/<job_id>/
├── input/source_reference.json
├── artifacts/
│   ├── transcript.json
│   ├── retimed.json
│   ├── speech_edit_plan.json
│   ├── director_style.json
│   ├── director_plan.json
│   ├── director_execution_plan.json
│   ├── clip_visual_plan.json
│   ├── montage_plan.json
│   ├── quality_report.json
│   ├── evaluation_summary.json       # batch only
│   └── director_debug.json           # --debug only
├── previews/director_inspector.html  # --debug only
├── logs/job.log
├── logs/error.txt                    # failed jobs only
├── output/<source>_final.mp4
├── temp/remotion_props.json
└── job_manifest.json
```

The source is referenced, never deleted or modified. Shared fonts, B-roll, SFX, music,
profiles, and presets remain read-only project assets. A completed MP4 is also published
to `output/` with the job's unique suffix.

`job_manifest.json` is the status API for a future queue. Stages are `CREATED`,
`ANALYZING`, `SPEECH_EDIT`, `DIRECTING`, `EXECUTING`, `RENDERING`, `QUALITY_CHECK`,
`COMPLETED`, and `FAILED`. It contains source/output duration, profile, artifact paths,
error, job output, and published output.

Failed jobs retain every artifact that was created before the failure. Find the traceback
in `logs/error.txt` and the last successful stage in `job_manifest.json`.

## Reports and debug data

Batch reports are written under `logs/batch/<run>/batch_report.json` and
`batch_report.html`. Each job also receives `artifacts/evaluation_summary.json`.
Missing metrics are `null`; the reporter never invents scores.

`director_debug.json` is assembled only from the existing Director, Execution, Style,
and Quality artifacts. The HTML Inspector shows the final video (when rendered) next to
the semantic timeline. It reports `NONE` or `SKIPPED` when an action or reason does not
exist. Debug mode does not add an overlay to or otherwise change the production MP4.
