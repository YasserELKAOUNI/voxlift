"""
Voxlift CLI - Extract voice from video, locally.

Usage:
    voxlift <url>                   # Quick transcribe
    voxlift transcribe <url>        # Full options
    voxlift serve                   # Web UI
    voxlift list                    # Show transcripts
    voxlift search <query>          # Search transcripts
"""

import os
import sys
from datetime import timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .config_manager import load_config_file
from .logging_manager import init_logger


# ─────────────────────────────────────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="voxlift",
    help="Extract voice from video. Local, private, fast.",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# App metadata
__version__ = "0.6.0"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _default_transcripts_dir() -> str:
    """Get default transcripts directory."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(repo_root, "transcripts")
    if os.path.isdir(candidate):
        return candidate
    return os.path.expanduser("~/Documents/Voxlift")


def _format_duration(seconds: Optional[int]) -> str:
    """Format seconds as human-readable duration."""
    if not seconds:
        return "—"
    return str(timedelta(seconds=seconds))


def _print_banner():
    """Print app banner."""
    banner = Text()
    banner.append("┌─────────────────────────────────────┐\n", style="cyan")
    banner.append("│  ", style="cyan")
    banner.append("VOXLIFT", style="bold white")
    banner.append("  ", style="cyan")
    banner.append("Voice → Text", style="dim")
    banner.append("           │\n", style="cyan")
    banner.append("│  ", style="cyan")
    banner.append("Local • Private • Fast", style="dim italic")
    banner.append("            │\n", style="cyan")
    banner.append("└─────────────────────────────────────┘", style="cyan")
    console.print(banner)
    console.print()


def _print_success(message: str, details: Optional[str] = None):
    """Print success message."""
    console.print(f"[green]✓[/green] {message}")
    if details:
        console.print(f"  [dim]{details}[/dim]")


def _print_error(message: str):
    """Print error message."""
    console.print(f"[red]✗[/red] {message}")


def _print_info(message: str):
    """Print info message."""
    console.print(f"[blue]ℹ[/blue] {message}")


# ─────────────────────────────────────────────────────────────────────────────
# Version Callback
# ─────────────────────────────────────────────────────────────────────────────

def version_callback(value: bool):
    if value:
        console.print(f"[bold]voxlift[/bold] version [cyan]{__version__}[/cyan]")
        raise typer.Exit()


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit."
    ),
):
    """
    [bold cyan]Voxlift[/bold cyan] — Extract voice from video.

    Paste a YouTube URL, get a transcript. Everything runs locally on your Mac.
    """
    pass


@app.command()
def transcribe(
    url: str = typer.Argument(..., help="YouTube URL to transcribe"),
    model: str = typer.Option(
        "small", "--model", "-m",
        help="Whisper model: [dim]tiny, base, small, medium, large[/dim]"
    ),
    lang: str = typer.Option(
        "auto", "--lang", "-l",
        help="Language code or 'auto' to detect"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output directory [dim](default: ./transcripts)[/dim]"
    ),
    format: str = typer.Option(
        "srt", "--format", "-f",
        help="Output format: [dim]srt, vtt, txt[/dim]"
    ),
    start: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start time [dim](e.g., 1:30 or 90)[/dim]"
    ),
    end: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End time [dim](e.g., 5:00 or 300)[/dim]"
    ),
    keep_audio: bool = typer.Option(
        False, "--keep-audio", "-k",
        help="Keep audio file after transcription"
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Re-transcribe even if already exists"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q",
        help="Minimal output"
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Output as JSON (for scripting)"
    ),
):
    """
    Transcribe a YouTube video to text.

    [bold]Examples:[/bold]

        voxlift transcribe "https://youtube.com/watch?v=..."

        voxlift transcribe URL -m medium -l en

        voxlift transcribe URL --start 1:30 --end 5:00
    """
    from .audio_extractor import extract_audio, cleanup_temp_file
    from .transcriber import transcribe_audio
    from .storage import save_transcript
    from .media import parse_timecode

    if not quiet and not json_output:
        _print_banner()
        _print_info(f"Processing: {url}")

    # Parse time range
    start_sec = parse_timecode(start) if start else None
    end_sec = parse_timecode(end) if end else None

    output_dir = output or _default_transcripts_dir()
    os.makedirs(output_dir, exist_ok=True)

    cfg = load_config_file()
    init_logger(level="WARNING" if quiet else cfg.get("logging_level", "INFO"))

    temp_file = None

    try:
        # Step 1: Extract audio
        if not quiet and not json_output:
            console.print()
            console.print("[dim]Step 1/3[/dim] Extracting audio...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
            disable=quiet or json_output,
        ) as progress:
            task = progress.add_task("Downloading...", total=None)

            temp_file, info = extract_audio(
                url=url,
                start_time=start_sec,
                end_time=end_sec,
            )
            progress.update(task, description="Download complete")

        video_id = info.get("id", "unknown")
        title = info.get("title", "Untitled")
        duration = info.get("duration", 0)

        if not quiet and not json_output:
            _print_success(f"Audio extracted: {title}")
            console.print(f"  [dim]Duration: {_format_duration(duration)}[/dim]")

        # Step 2: Transcribe
        if not quiet and not json_output:
            console.print()
            console.print("[dim]Step 2/3[/dim] Transcribing...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            disable=quiet or json_output,
        ) as progress:
            task = progress.add_task(f"Using {model} model...", total=None)

            result = transcribe_audio(
                audio_path=temp_file,
                model_name=model,
                language=None if lang == "auto" else lang,
            )
            progress.update(task, description="Transcription complete")

        text = result["text"]
        segments = result["segments"]
        detected_lang = result.get("language", lang)

        if not quiet and not json_output:
            _print_success(f"Transcribed ({len(segments)} segments)")
            console.print(f"  [dim]Language: {detected_lang}[/dim]")

        # Step 3: Save
        if not quiet and not json_output:
            console.print()
            console.print("[dim]Step 3/3[/dim] Saving transcript...")

        metadata = {
            "title": title,
            "uploader": info.get("uploader", "Unknown"),
            "url": url,
            "duration": duration,
        }

        filepath = save_transcript(
            video_id=video_id,
            text=text,
            segments=segments,
            metadata=metadata,
            output_format=format,
            transcripts_dir=output_dir,
        )

        # Cleanup
        if not keep_audio and temp_file:
            cleanup_temp_file(temp_file)
            temp_file = None

        # Output
        if json_output:
            import json
            print(json.dumps({
                "status": "success",
                "video_id": video_id,
                "title": title,
                "duration": duration,
                "language": detected_lang,
                "segments": len(segments),
                "file": filepath,
            }))
        else:
            console.print()
            panel = Panel(
                f"[bold]{title}[/bold]\n\n"
                f"[dim]File:[/dim] {filepath}\n"
                f"[dim]Format:[/dim] {format.upper()}\n"
                f"[dim]Segments:[/dim] {len(segments)}",
                title="[green]✓ Transcription Complete[/green]",
                border_style="green",
            )
            console.print(panel)

    except Exception as e:
        # Cleanup on error
        if temp_file:
            cleanup_temp_file(temp_file)

        if json_output:
            import json
            print(json.dumps({"status": "error", "message": str(e)}))
        else:
            _print_error(str(e))
        raise typer.Exit(1)


@app.command()
def serve(
    port: int = typer.Option(8765, "--port", "-p", help="Port number"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser"),
):
    """
    Start the web UI server.

    [bold]Example:[/bold]

        voxlift serve

        voxlift serve --port 9000
    """
    import webbrowser
    import uvicorn
    from .webapp import app as web_app

    _print_banner()

    url = f"http://{host}:{port}"
    console.print(f"[green]●[/green] Starting server at [bold cyan]{url}[/bold cyan]")
    console.print()
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(web_app, host=host, port=port, log_level="warning")


@app.command(name="list")
def list_transcripts(
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Transcripts directory"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max items to show"),
):
    """
    List all transcripts.

    [bold]Example:[/bold]

        voxlift list

        voxlift list -n 50
    """
    from .storage import list_transcripts as get_transcripts

    output_dir = output or _default_transcripts_dir()
    index_file = os.path.join(output_dir, "..", "transcripts_index.json")

    # Try alternate location
    if not os.path.exists(index_file):
        index_file = os.path.join(os.path.dirname(output_dir), "transcripts_index.json")

    transcripts = get_transcripts(index_file=index_file)

    if not transcripts:
        _print_info("No transcripts found.")
        console.print(f"[dim]Directory: {output_dir}[/dim]")
        return

    table = Table(title="Transcripts", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold", max_width=50)
    table.add_column("Channel", style="cyan", max_width=20)
    table.add_column("Duration", justify="right")
    table.add_column("Date", style="dim")

    for i, t in enumerate(transcripts[:limit], 1):
        title = t.get("title", "—")[:50]
        channel = t.get("uploader", "—")[:20]
        duration = _format_duration(t.get("duration"))
        date = t.get("created_at", "—")[:10]

        table.add_row(str(i), title, channel, duration, date)

    console.print(table)

    if len(transcripts) > limit:
        console.print(f"\n[dim]Showing {limit} of {len(transcripts)} transcripts[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search term"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Transcripts directory"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
):
    """
    Search transcript contents.

    [bold]Example:[/bold]

        voxlift search "machine learning"

        voxlift search "hello world" -n 5
    """
    from .storage import search_transcripts

    output_dir = output or _default_transcripts_dir()
    index_file = os.path.join(os.path.dirname(output_dir), "transcripts_index.json")

    results = search_transcripts(query, index_file=index_file)

    if not results:
        _print_info(f"No results for: {query}")
        return

    console.print(f"[bold]Found {len(results)} result(s) for:[/bold] {query}\n")

    for i, r in enumerate(results[:limit], 1):
        title = r.get("title", "Untitled")
        channel = r.get("uploader", "Unknown")

        console.print(f"[bold cyan]{i}.[/bold cyan] {title}")
        console.print(f"   [dim]{channel}[/dim]")

        # Show snippet with highlighted match
        text = r.get("text", "")
        query_lower = query.lower()
        text_lower = text.lower()
        pos = text_lower.find(query_lower)

        if pos >= 0:
            start = max(0, pos - 50)
            end = min(len(text), pos + len(query) + 50)
            snippet = text[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."

            # Highlight match
            snippet = snippet.replace("\n", " ")
            console.print(f"   [dim italic]\"{snippet}\"[/dim italic]")

        console.print()


@app.command()
def info():
    """
    Show system information and status.
    """
    from .transcriber import get_model_info

    _print_banner()

    info = get_model_info()

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Version", __version__)
    table.add_row("Device", info.get("device", "cpu"))
    table.add_row("MPS Available", "Yes" if info.get("mps_available") else "No")
    table.add_row("Backend", info.get("backend", "whisper"))
    table.add_row("Compute Type", info.get("compute_type", "float32"))
    table.add_row("Cached Models", ", ".join(info.get("cached_models", [])) or "None")

    console.print(table)


@app.command()
def open_folder(
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Transcripts directory"
    ),
):
    """
    Open transcripts folder in Finder.
    """
    import subprocess

    output_dir = output or _default_transcripts_dir()

    if os.path.isdir(output_dir):
        subprocess.run(["open", output_dir])
        _print_success(f"Opened: {output_dir}")
    else:
        _print_error(f"Directory not found: {output_dir}")
        raise typer.Exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
