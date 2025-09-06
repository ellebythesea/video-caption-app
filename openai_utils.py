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
            "under 1300 characters. Use 1–2 simple paragraphs. Prefer direct quotes and concrete facts "
            "(names, dates, numbers) drawn only from the transcript and provided news context. Verify "
            "names and quotes carefully. End with 8–13 relevant hashtags. Do not add interpretations, "
            "opinions, calls to action, rhetoric, or generalized conclusions (e.g., avoid phrases like "
            "'this shows', 'the call to action', 'spirit of', 'reminds us'). Omit any detail that cannot "
            "be supported by the transcript or news context. Keep a neutral, third‑person tone. Avoid "
            "links, flourish, or any mention of Trump’s current office status."
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
            temperature=0.3,
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

        def filter_subjective_sentences(s: str) -> str:
            """Remove subjective/opinionated sentences and keep quotes/facts.

            Heuristics:
            - Always keep the final hashtag paragraph.
            - Keep sentences containing direct quotes (", ’…’) or digits/dates.
            - Drop sentences containing subjective cue phrases.
            """
            subjective_cues = [
                "the message is clear",
                "call to action",
                "this shows",
                "this demonstrates",
                "highlights",
                "signal of",
                "spirit of",
                "reminds us",
                "not invincible",
                "can challenge",
                "resistance",
                "unity and",
                "unity can",
                "rhetoric",
                "misuse of power",
                "political maneuvers",
                "the takeaway",
                "clear:",
            ]

            def is_hashtag_paragraph(p: str) -> bool:
                count = sum(1 for t in p.split() if t.startswith("#"))
                return count >= 3 or (count and count >= max(1, len(p.split()) // 3))

            paragraphs = [p.strip() for p in s.split("\n\n") if p.strip()]
            if not paragraphs:
                return s

            # Identify hashtag paragraph (last one that looks like hashtags)
            hashtag_idx = None
            for i in range(len(paragraphs) - 1, -1, -1):
                if is_hashtag_paragraph(paragraphs[i]):
                    hashtag_idx = i
                    break

            cleaned_paragraphs: list[str] = []
            for i, p in enumerate(paragraphs):
                if hashtag_idx is not None and i == hashtag_idx:
                    cleaned_paragraphs.append(p)
                    continue

                # Split into sentences on punctuation boundaries
                sentences = re.split(r"(?<=[.!?])\s+", p)
                kept: list[str] = []
                for sent in sentences:
                    sent_norm = sent.strip()
                    if not sent_norm:
                        continue
                    low = sent_norm.lower()
                    if any(cue in low for cue in subjective_cues):
                        continue
                    # Keep if contains a quote or number/date-like token
                    if (
                        '"' in sent_norm
                        or '“' in sent_norm
                        or '”' in sent_norm
                        or '’' in sent_norm
                        or re.search(r"\d{4}|\d+", sent_norm)
                    ):
                        kept.append(sent_norm)
                        continue
                    # Otherwise, be conservative and drop
                    continue

                if kept:
                    cleaned_paragraphs.append(" ".join(kept))

            return "\n\n".join(cleaned_paragraphs).strip() or s

        text = sanitize_caption(text)
        text = filter_subjective_sentences(text)
        return text
    except Exception as e:
        log_message(f"Error with ChatGPT API: {str(e)}")
        return f"Error processing with ChatGPT: {str(e)}"

def process_caption(transcript, prompt=""):
    news_context = get_latest_news_summary(transcript)
    return apply_chatgpt_prompt(transcript, prompt, news_context)
