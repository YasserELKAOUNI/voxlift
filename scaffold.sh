#!/usr/bin/env bash
# scaffold.sh
# Usage: ./scaffold.sh

set -euo pipefail

# 1. Initialise Git (si pas déjà fait)
if [ ! -d .git ]; then
  echo "🔧 Initialisation de Git"
  git init
fi

# 2. Création des dossiers
echo "📁 Création des dossiers…"
mkdir -p docs \
         src/yww \
         tests/unit \
         tests/integration \
         .github/workflows

# 3. Fichiers vides
echo "📄 Création des fichiers vides…"
# docs
touch docs/architecture.md

# src package
touch src/yww/__init__.py
touch src/yww/config_manager.py
touch src/yww/logging_manager.py
touch src/yww/downloader.py
touch src/yww/storage.py
touch src/yww/transcriber.py
touch src/yww/orchestrator.py

# tests
touch tests/unit/test_config_manager.py
touch tests/unit/test_logging_manager.py
touch tests/unit/test_downloader.py
touch tests/unit/test_transcriber.py
touch tests/unit/test_storage.py
touch tests/unit/test_orchestrator.py
touch tests/integration/test_e2e.py

# CI
touch .github/workflows/ci.yml

# Racine
touch README.md LICENSE .gitignore pyproject.toml

# 4. Ajout de contenu minimal dans .gitignore
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*.so

# Virtual env
.venv/
env/
venv/

# Logs
logs/
*.log

# Editor
.vscode/
.idea/

# Mac
.DS_Store
EOF

echo "✅ Structure créée ! Tu peux maintenant remplir tes fichiers et lancer ton éditeur."
