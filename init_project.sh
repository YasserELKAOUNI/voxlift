#!/usr/bin/env bash
# init_project.sh
# Usage: ./init_project.sh <project-directory>

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <project-directory>"
  exit 1
fi

PROJECT_DIR=$1

echo "🚀 Création du projet dans : ${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}"
cd "${PROJECT_DIR}"

echo "🔧 Initialisation de Git"
git init

echo "🔨 Création de la structure de dossiers"
mkdir -p docs \
         src/yww \
         tests/unit \
         tests/integration \
         .github/workflows

echo "📦 Initialisation de Poetry (si Poetry n’est pas installé, installe-le d’abord : https://python-poetry.org/)"
poetry init --name youtube-whisper-wrapper \
            --description "Wrapper yt-dlp + Whisper" \
            --author "Yasser" \
            --python "^3.10" \
            --dependency yt-dlp \
            --dependency openai-whisper \
            --dependency torch \
            --dependency ffmpeg \
            --dev-dependency pytest \
            --dev-dependency black \
            --dev-dependency flake8 \
            --dev-dependency mypy \
            --dev-dependency pre-commit \
            --no-interaction

echo "📥 Installation des dépendances"
poetry install

echo "🗒️ Création des fichiers vides"
touch README.md LICENSE pyproject.toml \
      src/yww/__init__.py \
      src/yww/config_manager.py \
      src/yww/logging_manager.py \
      src/yww/downloader.py \
      src/yww/storage.py \
      src/yww/transcriber.py \
      src/yww/orchestrator.py \
      .github/workflows/ci.yml

echo "🔗 Installation des hooks pre-commit"
poetry run pre-commit install

echo "✨ Structure initiale créée avec succès !"
echo "Tu peux maintenant ouvrir le projet :"
echo "  cd ${PROJECT_DIR} && code .  # ou ton éditeur favori"

