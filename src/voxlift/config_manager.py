# src/voxlift/config_manager.py

import os
import argparse
import yaml
from typing import Any, Dict

DEFAULT_CONFIG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
)


def load_config_file(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Charge et parse un fichier YAML de configuration.
    Si le fichier n'existe pas, renvoie un dict vide.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Définit les flags CLI pour surcharger la config.
    Ajoute ici toutes les options dont on a parlé.
    """
    parser = argparse.ArgumentParser(
        prog="voxlift",
        description="Voxlift CLI - local YouTube download and transcription"
    )
    parser.add_argument("--url", "-u", type=str, help="URL vidéo ou playlist YouTube")
    parser.add_argument("--download-format", "-f", type=str, help="Format de téléchargement (best, mp4, mkv, mov, bestaudio)")
    parser.add_argument("--output-path", "-o", type=str, help="Répertoire de sortie")
    parser.add_argument("--max-playlist-items", type=int, help="Nombre max de vidéos dans une playlist")
    parser.add_argument("--transcription-language", "-l", type=str, help="Langue pour Whisper (auto_detect, en, fr, ...)")
    parser.add_argument("--transcription-model", "-m", type=str, help="Modèle Whisper (tiny, base, ...)")
    parser.add_argument("--transcription-backend", type=str, help="Backend: whisper or faster-whisper")
    parser.add_argument("--transcription-compute-type", type=str, help="faster-whisper compute type (int8_float16, int8, float16, auto)")
    parser.add_argument("--download-workers", type=int, help="Nb de workers téléchargement")
    parser.add_argument("--transcribe-workers", type=int, help="Nb de workers transcription")
    parser.add_argument("--max-retries", type=int, help="Nb max de tentatives en cas d'erreur")
    parser.add_argument("--require-internet", action="store_true", help="Forcer la vérification de la connexion Internet")
    parser.add_argument("--logging-level", type=str, help="Niveau de log (DEBUG, INFO, ...)")
    return parser


def merge_configs(file_cfg: Dict[str, Any], cli_args: argparse.Namespace) -> Dict[str, Any]:
    """
    Fusionne (file_cfg) et (cli_args) en donnant priorité aux CLI args non null.
    Retourne un dict final prêt à passer aux modules.
    """
    cfg = file_cfg.copy()
    for key, value in vars(cli_args).items():
        if value is not None:
            # normalize cli key to match YAML keys si nécessaire
            cfg[key.replace('-', '_')] = value
    return cfg


def load_config() -> Dict[str, Any]:
    """
    Point d'entrée unique pour récupérer la config consolidée :
      1. Charge le YAML
      2. Parse les arguments CLI
      3. Fusionne et retourne le dict final.
    """
    parser = build_arg_parser()
    args = parser.parse_args()
    file_cfg = load_config_file()
    final_cfg = merge_configs(file_cfg, args)
    return final_cfg


if __name__ == "__main__":
    # pour tester en CLI : `python config_manager.py --help`
    cfg = load_config()
    print("Configuration finale :", cfg)
