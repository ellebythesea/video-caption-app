import openai
import os
import subprocess
import tempfile
from typing import Optional
import re

from config import OPENAI_API_KEY, TRIM_SILENCE, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS, AUDIO_BITRATE
from logger import log_message
from news import get_latest_news_summary


def _get_ffmpeg_path() -> str:
    """Return a usable ffmpeg executable path.

    Prefers the imageio-ffmpeg bundled binary when available, otherwise falls
    back to the system's `ffmpeg` in PATH.
    """
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _extract_downsampled_audio(input_path: str, trim_silence: bool = TRIM_SILENCE) -> Optional[str]:
    """Extract mono 16kHz audio at low bitrate, optionally trimming silence.

    Returns the path to a temporary .wav file, or None on failure.
    """
    try:
        ffmpeg = _get_ffmpeg_path()
        # Create a temp wav file for the output
        tmp_fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)  # ffmpeg will write to this path

        # Build ffmpeg command
        cmd = [
            ffmpeg,
            "-y",  # overwrite output
            "-i",
            input_path,
            "-vn",  # drop video
            "-ac",
            str(AUDIO_CHANNELS),
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-b:a",
            str(AUDIO_BITRATE),
        ]

        # Optional silence trimming (conservative thresholds)
        if trim_silence:
            # Trim near-silence at start/end; keep mid-speech pauses
            af = (
                "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB:"
                "stop_periods=1:stop_duration=0.8:stop_threshold=-40dB"
            )
            cmd.extend(["-af", af])

        cmd.append(out_path)

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            log_message(
                f"ffmpeg audio extract failed (rc={proc.returncode}): {proc.stderr.decode(errors='ignore')[:500]}"
            )
            try:
                os.unlink(out_path)
            except Exception:
                pass
            return None

        return out_path
    except FileNotFoundError:
        # ffmpeg not found
        log_message("ffmpeg not found; sending original file to Whisper.")
        return None
    except Exception as e:
        log_message(f"Audio preprocessing error: {e}")
        return None

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def transcribe_video(video_path):
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        # Extract and compress audio first for faster uploads/processing
        processed = _extract_downsampled_audio(video_path)
        src_path = processed or video_path
        with open(src_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return transcript.text
    except Exception as e:
        log_message(f"Error transcribing video: {str(e)}")
        return None
    finally:
        # Cleanup temp file if we created one
        try:
            if 'processed' in locals() and processed and os.path.exists(processed):
                os.unlink(processed)
        except Exception:
            pass

def apply_chatgpt_prompt(transcript, prompt="", news_context=""):
    try:
        # Cleaned prompt structure: all guidance in the system message; user carries only context and transcript
        SYS_PROMPT = (
            "You are a sharp political analyst. Rewrite the transcript into a short, clear social post "
            "under 1300 characters. Use 1–2 simple paragraphs. Expand with verified facts, dates, and "
            "numbers when relevant. Include direct transcript quotes where available. Verify names and "
            "quotes carefully. End with 8–13 relevant hashtags. Avoid speculation, flourish, links, or "
            "Trump’s current office status."
        )
        # Optionally allow an extra hint without polluting the user message
        if prompt:
            SYS_PROMPT = SYS_PROMPT + " Additional instructions: " + str(prompt).strip()
        if not news_context or news_context.startswith("LATEST NEWS CONTEXT:\nNo recent news") or news_context.startswith("LATEST NEWS CONTEXT:\nUnable"):
            news_context = "LATEST NEWS CONTEXT:\nNo external news context available. Focus solely on the transcript for analysis.\n\n"
        user_content = f"{news_context}\n\nTRANSCRIPT:\n{transcript}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=500,
            temperature=0.35,
        )
        text = response.choices[0].message.content.strip()

        # Post-process to avoid phrases like "Former President Trump"
        def sanitize_caption(s: str) -> str:
            # Replace variants with "President Trump" and preserve possessive
            def repl_president(m):
                suffix = m.group(1) or ""
                return "President Trump" + suffix

            patterns = [
                r"(?i)\bformer\s+(?:u\.?s\.?\s+)?president\s+(?:donald\s+(?:j\.?\s+)?trump|trump)(’s|'s)?",
                r"(?i)\bex[-\s]?president\s+(?:donald\s+(?:j\.?\s+)?trump|trump)(’s|'s)?",
            ]
            for pat in patterns:
                s = re.sub(pat, repl_president, s)
            return s

        return sanitize_caption(text)
    except Exception as e:
        log_message(f"Error with ChatGPT API: {str(e)}")
        return f"Error processing with ChatGPT: {str(e)}"

def process_caption(transcript, prompt=""):
    news_context = get_latest_news_summary(transcript)
    return apply_chatgpt_prompt(transcript, prompt, news_context)
