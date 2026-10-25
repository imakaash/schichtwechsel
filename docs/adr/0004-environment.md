# 4. Conda for the local environment, dependencies in pyproject

Date: 2026-10-25
Status: accepted

## Context

Local development uses VS Code with a conda environment. Later the same code runs in a Docker image on Azure.

## Decision

- `environment.yml` pins only the Python version and installs the project with pip in editable mode.
- All Python dependencies are declared once, in `pyproject.toml`.
- Python 3.12: newest version with reliable wheels for the ML stack planned next (LightGBM, SHAP, lifelines).
- `src/` layout, so tests run against the installed package and not whatever happens to be in the working directory.

## Consequences

- The Docker image can `pip install .` without conda, using the same dependency list. No drift between two lists.
- Packages that need conda-forge binaries can still be added to `environment.yml` if required.
