import os
import sys
import webbrowser
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from .config_manager import load_config_file
from .logging_manager import init_logger
from .orchestrator import process_url
from .webapp import app as web_app  # for uvicorn


app = typer.Typer(add_completion=False, help="YouTube → Transcript pipeline (audio-only, local).")
console = Console()


def _default_output_dir() -> str:
    # Default under project downloads/ or ~/Documents/Transcripts
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "downloads")
    if os.path.isdir(candidate):
        return candidate
    return os.path.expanduser("~/Documents/Transcripts")


@app.command()
def process(
    url: str = typer.Option(..., "--url", "-u", help="YouTube URL"),
    out: str = typer.Option(_default_output_dir(), "--out", "-o", help="Output directory"),
    model: str = typer.Option("base", "--model", "-m", help="Whisper model size (tiny, base, small, ...)"),
    lang: str = typer.Option("auto", "--lang", "-l", help="Language code or 'auto'"),
    force: bool = typer.Option(False, "--force", help="Re-transcribe even if transcript exists"),
    json_events: bool = typer.Option(False, "--json", help="Emit NDJSON progress to stdout"),
    open_result: bool = typer.Option(False, "--open", help="Open transcript in default editor on completion"),
):
    """Download audio-only, transcribe to .txt, update index."""
    cfg = load_config_file()
    # Merge with CLI options
    cfg["output_path"] = out
    cfg["transcription_language"] = lang
    cfg["transcription_model"] = model

    # Init logs
    init_logger(level=cfg.get("logging_level", "INFO"))

    try:
        result = process_url(url=url, output_dir=out, config=cfg, force=force, json_events=json_events)
        transcript = result["transcript"]
        if not json_events:
            console.print(Panel.fit(f"Transcript: {transcript}", title="Done", border_style="green"))
        if open_result and os.path.exists(transcript):
            try:
                # Prefer opening the directory in Finder
                webbrowser.open("file://" + os.path.dirname(transcript))
            except Exception:
                pass
    except Exception as e:
        if json_events:
            # Keep raw error message on stdout
            print(f"{{\"event\":\"error\",\"message\":{e!s}}}")
        else:
            console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def web(
    port: int = typer.Option(8787, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    open_browser: bool = typer.Option(True, "--open-browser", help="Open http page on start"),
):
    """Run web UI server (FastAPI)."""
    import uvicorn
    url = f"http://{host}:{port}"
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(web_app, host=host, port=port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
