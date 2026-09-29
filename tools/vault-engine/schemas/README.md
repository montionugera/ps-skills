# Schemas & Metadata Contracts

All canonical notes in this vault adhere to strict versioned schemas stored as JSON Schemas in this directory.

## Core Schemas

1. **`idea/v1` (`idea-v1.json`)**: Ideas, features, and opportunity notes. Stored in `01_Ideas/`.
2. **`project/v1` (`project-v1.json`)**: Finite initiatives with definitions of done. Stored in `02_Projects/`.
3. **`area/v1` (`area-v1.json`)**: Ongoing domains of responsibility with standards and KPIs. Stored in `03_Areas/`.

## Validation Rule

Agents must validate note frontmatter against the respective schema before writing to canonical paths or releasing locks.
Run `python3 _meta/scripts/vault_engine.py validate [path]` to check validity.
