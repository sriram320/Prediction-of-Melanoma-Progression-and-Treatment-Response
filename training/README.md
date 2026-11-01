# MelanoTrack · Model training

This folder trains the real model that replaces the platform's mock (`ml_service`, `MODEL_ADAPTER=mock`). It follows
the team's design documents (Week 5 to 9) and reuses the team's code.

| Folder | What it is |
|---|---|
| `melanotrack_ml/` | The team's Week 5-9 code and results (segmentation, registration, features, sequence simulator, temporal models). See its README. |
| `melanotrack_ml/splits/isic2017_splits.csv` | The ISIC 2017 split used everywhere: the 430 test images of Weeks 5-9 (81 melanomas), plus train/validation split by near-duplicate group. Built by `melanotrack_ml/scripts/make_splits.py`. |
| `notebooks/` | Google Colab notebooks, one per training step. Edit the `.py` file, then rebuild the `.ipynb`. |
| `tools/build_notebooks.py` | Builds `notebooks/*.ipynb` from `notebooks/*.py` and checks every cell compiles. |

## The steps (Week 6 design)

| Step | Module | Model | Data | Status |
|---|---|---|---|---|
| 1 | M3 segmentation | U-Net, ResNet-34 encoder, 512 px, 8-way TTA confidence | ISIC 2017 + ISIC 2018 Task 1 | Notebook ready: `01_segmentation_unet.ipynb` |
| 2 | M5 per-visit encoder | EfficientNet-B3, fine-tuned (melanoma vs benign) + Grad-CAM++ | ISIC 2017 splits, HAM10000, ISIC 2019/2020 (de-duplicated against the test set) | Next |
| 3 | M7/M8/M11 sequence model | GRU-128 + attention, 5-seed ensemble, focal loss, temperature scaling, conformal set, Mahalanobis OOD | Simulated sequences (Week 7 simulator) now; real serial dermoscopy when access is granted | Later |
| 4 | Packaging | ONNX models + `ml_service/app/adapters/longitudinal.py`, test vectors, model card | | Later |

Registration (M4, skin-anchored SIFT) and the 29 descriptors (M5) are classical code from `melanotrack_ml/src/`
and need no training. Real serial data: the University of Queensland's longitudinal dermoscopy dataset
(*Scientific Data* 2025, doi:10.1038/s41597-025-05880-2) needs an access request; the Basel SDDI sets are restricted.

## Running a notebook in Colab

1. The notebooks clone this repository from GitHub, so the `training/` folder must be pushed first.
2. In Colab: *File → Open notebook → GitHub*, paste the repository URL, open `training/notebooks/<notebook>.ipynb`
   (or upload the `.ipynb` file).
3. *Runtime → Change runtime type → T4 GPU*, then *Runtime → Run all*. Allow Google Drive access when asked.
4. Optional first run: set `QUICK_RUN = True` in the first code cell (about 5 minutes) to check everything works.

Everything a notebook produces goes to Google Drive, never to GitHub:

```text
MyDrive/melanotrack/
  data/          resized copies of the public datasets (made once, reused by later sessions)
  checkpoints/   training checkpoints (a disconnected session resumes from last.pt)
  models/melanotrack-longitudinal/<version>/   exported ONNX models + JSON metadata and metrics
```

To use a trained model on the laptop, copy `models/melanotrack-longitudinal/<version>/` from Drive into
`ml_service/models/melanotrack-longitudinal/<version>/` (git-ignored).

## Rules

- Never commit weights (`*.pt`, `*.onnx`), datasets or checkpoints. `.gitignore` blocks them.
- Never upload hospital or patient data to Colab or Drive. Training uses public research datasets only.
- The public datasets are licensed for research use (mostly CC BY-NC). A model trained on them is a research
  prototype: the platform keeps a "not for clinical use" watermark when it is active.
- Keep the 430-image test set untouched for final scores only; tune thresholds on the validation split.

## Changes to the team's code

`melanotrack_ml/` is a copy of the team's Week 5-9 code. Changes so far:

- `src/data.py`, `src/unet.py`: the hard-coded `/home/claude/...` paths can be overridden with `MELANO_ISIC_ROOT`,
  `MELANO_META_ROOT`, `MELANO_CACHE` and `MELANO_WEIGHTS`. The scripts still contain the original paths.
- `src/unet.py`: without a local weights file, the encoder downloads timm's default ImageNet weights (for ResNet-34 the
  same `a1` checkpoint the team used).
- `splits/isic2017_splits.csv` and `scripts/make_splits.py`: today's scikit-learn does not reproduce the original
  split, so the saved 430 test ids are used and train/validation is re-split by near-duplicate group (seed 0).
